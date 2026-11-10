"""site/ai.html: the AI and ML layer of the tracker (payment screen, payee classifier, grant groups, MCP server, briefs).

Every number on the page is read at build time from the export the site is built from (d_payment_screen*, d_source_issues,
d_payee_class*, d_grant_groups*), from the docs (docs/models/*.md, docs/mcp.md, docs/briefs.md, docs/briefs_sample.csv),
from the code (the MCP server's registered tools, the brief guardrail) or from a measurement made during the build (the
MCP golden set, the security test count). Nothing is typed in. The same facts are written to data/ai_layer.json.

    facts = collect(src)          # dict, JSON-safe
    html = body(facts)            # the page body (site.page() adds the shell)
    write(out, src)               # both, into out/ (site.py calls this)
"""
import ast
import csv
import html
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPO = "https://github.com/EVO3-Ecosystem/gmi-savings-tracker"
DOCS = ROOT / "docs"
GOLDEN_YAML = ROOT / "tests" / "fixtures" / "mcp_golden.yaml"
GOLDEN_RESULTS = DOCS / "mcp_golden_results.json"  # used when present; otherwise the golden set is run during the build
REVIEW_SHEET = "docs/reviews/payment_screen_review_sheet.csv"
TOP_QUEUE = 15
TOP_GROUPS = 10
MASK = "Payee not named (may be an individual)"

TOKENS = """<style>
:root{--a-panel:#fff;--a-chip:#efeee9;--a-ok:#1a7f37;--a-warn:#9a6700;--a-bad:#b42318;--a-code:#f0efeb}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--a-panel:#1e1e1d;--a-chip:#2a2a28;--a-ok:#7ee2a8;--a-warn:#f2cc60;--a-bad:#ff8a80;--a-code:#1a1a19}}
:root[data-theme="dark"]{--a-panel:#1e1e1d;--a-chip:#2a2a28;--a-ok:#7ee2a8;--a-warn:#f2cc60;--a-bad:#ff8a80;--a-code:#1a1a19}
.ai-toc{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px;margin:16px 0;padding:0;list-style:none}
.ai-toc li{border:1px solid var(--s-line);border-radius:8px;padding:10px 12px;background:var(--a-panel);font-size:14px}
.ai-toc a{font-weight:600;text-decoration:none}.ai-toc a:hover{text-decoration:underline}.ai-toc p{margin:4px 0 0;color:var(--s-muted)}
section.ai{border-top:1px solid var(--s-line);margin-top:28px;padding-top:4px}
section.ai h2{margin-top:.8em}
.ai-q{font-size:17px;margin:.2em 0 .8em}
.ai-find{border-left:4px solid var(--s-link);background:var(--a-panel);padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0}
.ai-find b:first-child{display:block;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--s-muted)}
dl.ai-dl{margin:0}dl.ai-dl dt{font-weight:600;margin-top:12px}dl.ai-dl dd{margin:2px 0 0}
.chip{display:inline-block;border-radius:999px;padding:0 8px;font-size:12px;background:var(--a-chip);white-space:nowrap}
.ok{color:var(--a-ok)}.warn{color:var(--a-warn)}.bad{color:var(--a-bad)}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tbl{margin:8px 0;max-width:100%}.tbl table{font-size:13px}
.k{color:var(--s-muted);font-size:13px}
pre.ai-pre{background:var(--a-code);border:1px solid var(--s-line);border-radius:8px;padding:10px 12px;overflow:auto;max-height:340px;font-size:12.5px;line-height:1.45;margin:6px 0;max-width:100%}
.copy-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px}
button.copy{font:inherit;font-size:14px;padding:4px 12px;border:1px solid var(--s-line);border-radius:6px;background:var(--a-panel);color:var(--s-fg);cursor:pointer}
button.copy:hover{border-color:var(--s-link)}
blockquote.brief{margin:8px 0;padding:8px 12px;border:1px solid var(--s-line);border-radius:8px;background:var(--a-panel)}
blockquote.brief p{margin:0 0 4px}
ul.ai-list{padding-left:20px}ul.ai-list li{margin:4px 0}
</style>"""


# ------------------------------------------------------------------------------------------------ helpers
def _csv(path):
    p = Path(path)
    return list(csv.DictReader(open(p, newline="", encoding="utf-8"))) if p.exists() else []


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _b(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def money(v):
    """$1.86M, $17.18M, $1.08B, $4,897."""
    v = _f(v)
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:,.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:,.2f}M"
    return f"${v:,.0f}"


def pct(v, digits=1):
    return f"{_f(v) * 100:.{digits}f}%"


def num(v):
    return f"{int(round(_f(v))):,}"


def esc(s):
    return html.escape(str(s if s is not None else ""))


def link(path, text=None):
    return f'<a href="{REPO}/blob/main/{path}">{esc(text or path)}</a>'


def _section(md, title):
    """The text of one '## title' section of a markdown file (up to the next heading of the same or higher level)."""
    m = re.search(rf"^(#+) {re.escape(title)}\s*$", md, re.M)
    if not m:
        return ""
    level = len(m.group(1))
    rest = md[m.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[:end.start()] if end else rest


def _inline(s):
    from src.pipeline import site  # lazy: site imports this module
    return site._inline(s)


# ------------------------------------------------------------------------------------------------ 1. payment screen
def payment_screen(src):
    leads = _csv(src / "d_payment_screen.csv")
    issues = _csv(src / "d_source_issues.csv")
    summ = _csv(src / "d_payment_screen_summary.csv")
    by = {}
    for r in leads:
        k = (r["confidence"], r["review_status"])
        g = by.setdefault(k, {"confidence": k[0], "review_status": k[1], "groups": 0, "records": 0, "review_amount": 0.0})
        g["groups"] += 1
        g["records"] += int(_f(r["n"]))
        g["review_amount"] += _f(r["review_amount"])
    order = {"high": 0, "medium": 1, "low": 2}
    by_rows = sorted(by.values(), key=lambda g: (order.get(g["confidence"], 9), g["review_status"]))
    s0 = summ[0] if summ else {}
    rule_status = {}
    for r in summ:
        rule_status.setdefault(r["rule"], set()).add(r["status"])
    sheet = _csv(ROOT / REVIEW_SHEET)
    decided = sum(1 for r in sheet if (r.get("her_decision") or "").strip())
    out = {
        "leads": len(leads),
        "lead_records": sum(int(_f(r["n"])) for r in leads),
        "lead_total_amount": round(sum(_f(r["total_amount"]) for r in leads), 2),
        "lead_review_amount": round(sum(_f(r["review_amount"]) for r in leads), 2),
        "by_confidence_status": by_rows,
        "source_issues": [{k: r[k] for k in ("issue_id", "issue", "fiscal_year", "agency", "records", "amount", "identical_records",
                                             "screen_groups", "screen_review_amount", "verified_against", "verified_on", "status")} for r in issues],
        "source_issue_groups": sum(int(_f(r["screen_groups"])) for r in issues),
        "source_issue_review_amount": round(sum(_f(r["screen_review_amount"]) for r in issues), 2),
        "rate_basis": s0.get("rate_basis", ""),
        "measured_confirmation_rate": s0.get("measured_confirmation_rate", "") or None,
        "lever_fy": s0.get("lever_fy", ""),
        "lever_rates": [_f(s0.get(k)) for k in ("lever_rate_low", "lever_rate_likely", "lever_rate_high")],
        "reviewed_leads": int(_f(s0.get("reviewed_leads"))),
        "confirmed_leads": int(_f(s0.get("confirmed_leads"))),
        "rule_status": {k: sorted(v) for k, v in rule_status.items()},
        "review_sheet": REVIEW_SHEET,
        "review_sheet_rows": len(sheet),
        "review_sheet_decided": decided,
    }
    out["baseline_groups"] = out["leads"] + out["source_issue_groups"]
    out["baseline_review_amount"] = round(out["lead_review_amount"] + out["source_issue_review_amount"], 2)
    out["finding"] = (f"{out['leads']} payment leads ({money(out['lead_review_amount'])} review dollars) remain once {len(issues)} source "
                      f"issues verified at the State's own sites take {out['source_issue_groups']} groups ({money(out['source_issue_review_amount'])}) "
                      f"out; {out['confirmed_leads']} of {out['reviewed_leads']} leads can be confirmed from the data, so the recovery lever is "
                      f"{pct(max(out['lever_rates'] or [0]), 0)} ({out['rate_basis'] or 'no rate'}).")
    return out


# ------------------------------------------------------------------------------------------------ 2. payee classifier
def payee_classifier(src):
    ev = _csv(src / "d_payee_class_eval.csv")
    get = {(r["method"], r["metric"], r["class"]): r for r in ev}

    def v(method, metric, cls="all"):
        r = get.get((method, metric, cls))
        return None if r is None else _f(r["value"], None)

    def n(method, metric, cls="all"):
        r = get.get((method, metric, cls))
        return None if r is None else int(_f(r["n"]))

    metrics = ["accuracy", "macro_f1", "accuracy_on_default_names", "dollars_classified_share", "dollars_relabeled_share"]
    table = {m: {k: v(k, m) for k in ("rules", "model", "combined")} for m in metrics}
    classes = sorted({r["class"] for r in ev if r["metric"] == "f1"})
    per_class = {c: {k: v(k, "f1", c) for k in ("rules", "model", "combined")} | {"n": n("rules", "f1", c)} for c in classes}
    rows = _csv(src / "d_payee_class.csv")
    queue = [r for r in rows if _b(r.get("review_flag"))]
    queue.sort(key=lambda r: -_f(r.get("paid_all_years")))
    top = []
    for r in queue[:TOP_QUEUE]:
        name = r["payee"]
        if "individual" in (r.get("model_label") or "") + (r.get("rule_class") or "") + (r.get("final_label") or ""):
            name = MASK  # never show a name that may be a person's (the export already masks these; this is a second guard)
        top.append({"payee": name, "payee_key": r["payee_key"], "rule_class": r["rule_class"], "model_label": r["model_label"],
                    "confidence": _f(r["confidence"]), "review_reason": r.get("review_reason", ""), "paid_all_years": round(_f(r["paid_all_years"]), 2)})
    promoted = v("decision", "combined_promoted")
    out = {
        "scored": n("rules", "accuracy"),
        "default_scored": n("rules", "accuracy_on_default_names"),
        "names": n("rules", "dollars_classified_share"),
        "table": table,
        "per_class_f1": per_class,
        "labeled": int(v("sample", "labeled") or 0),
        "excluded_unsure": int(v("sample", "excluded_unsure") or 0),
        "reviewed_by_sierra": int(v("sample", "reviewed_by_sierra") or 0),
        "training_names": int(v("model", "training_names") or 0),
        "promoted": bool(promoted),
        "review_queue": int(v("model", "review_queue") or 0),
        "review_queue_rows": len(queue),
        "review_queue_masked_in_top": sum(1 for t in top if t["payee"] == MASK),
        "top_queue": top,
    }
    r, c = table["macro_f1"]["rules"], table["macro_f1"]["combined"]
    out["why"] = (f"combined macro F1 {c:.2f} {'beats' if c > r else 'does not beat'} the rules' {r:.2f} on the {out['scored']} scored names, "
                  f"so the final label stays the rule label" if not out["promoted"] else f"combined macro F1 {c:.2f} beats the rules' {r:.2f}")
    out["finding"] = (f"The model does not beat the name rules (macro F1 {table['macro_f1']['model']:.2f} vs {r:.2f}; combined {c:.2f}), so it is "
                      f"{'promoted' if out['promoted'] else 'not promoted'}; it is kept as a review queue of {out['review_queue']:,} names, and it "
                      f"relabels {pct(table['dollars_relabeled_share']['combined'], 0)} of dollars when combined with the rules.")
    return out


# ------------------------------------------------------------------------------------------------ 3. grant overlap
CARD_ROW = re.compile(r"^\|\s*\*\*(?P<t>0\.\d+)\*\*\s*\|\s*\*\*(?P<g>[\d,]+)\*\*", re.M)
PRECISION = re.compile(r"Precision of the top-(?P<k>\d+) check:\s*(?P<real>\d+) of (?P<of>\d+)", re.I)
PRECISION_BLOCK = re.compile(r"<!--\s*precision\s*(\{.*?\})\s*-->", re.S)
VERDICT_COLS = ("hand_verdict", "verdict", "hand_check")


def grant_overlap(src):
    groups = _csv(src / "d_grant_groups.csv")
    sens = _csv(src / "d_grant_groups_sensitivity.csv")
    amt_col = next((c for c in (groups[0].keys() if groups else []) if re.fullmatch(r"amount_fy\d{4}", c)), None)
    fy = int(amt_col[-4:]) if amt_col else None
    ag_col = f"grantor_agencies_fy{fy}" if fy else None
    main = next((r for r in sens if _b(r.get("main"))), sens[0] if sens else {})
    leads = [r for r in groups if _b(r.get("overlap_lead"))]
    multi = sorted((r for r in groups if _b(r.get("multi_agency_any_year"))), key=lambda r: -_f(r.get(amt_col)))
    out = {
        "fiscal_year": fy,
        "backend": (groups[0].get("backend") if groups else "") or main.get("backend", ""),
        "threshold": (groups[0].get("cosine_threshold") if groups else "") or main.get("cosine_threshold", ""),
        "descriptions": int(_f(main.get("descriptions"))),
        "groups": len(groups),
        "multi_description_groups": sum(1 for r in groups if int(_f(r.get("n_descriptions"))) >= 2),
        "groups_with_fy_amount": sum(1 for r in groups if _f(r.get(amt_col)) > 0),
        "fy_amount_in_groups": round(sum(_f(r.get(amt_col)) for r in groups), 2),
        "leads": len(leads),
        "lead_amount_fy": round(sum(_f(r.get(amt_col)) for r in leads), 2),
        "lead_descriptions": [r["description"] for r in leads],
        "lead_agencies": [r.get(ag_col, "") for r in leads],
        "multi_agency_any_year": len(multi),
        "multi_agency_any_year_amount_fy": round(sum(_f(r.get(amt_col)) for r in multi), 2),
        "top_multi": [{"description": r["description"], "grantor_agencies": r.get("grantor_agencies", ""), "n_agencies": int(_f(r.get("n_agencies"))),
                       "amount_fy": round(_f(r.get(amt_col)), 2), "first_fy": r.get("first_fy"), "last_fy": r.get("last_fy")} for r in multi[:TOP_GROUPS]],
        "sensitivity": [{k: r.get(k) for k in ("cosine_threshold", "main", "groups", "multi_description_groups", "overlap_leads", "lead_amount_fy",
                                               "multi_agency_any_year", "multi_agency_any_year_amount_fy")} for r in sens],
    }
    out["precision"] = _precision(groups, multi, main)
    p = out["precision"]
    prec = f"top-{p['k']} hand-check precision {p['real']} of {p['of']}" if p.get("real") is not None else "top-20 precision: see the model card"
    out["finding"] = (f"{out['leads']} same-year lead{'s' if out['leads'] != 1 else ''} in FY{fy} ({money(out['lead_amount_fy'])}"
                      + (f": “{out['lead_descriptions'][0]}”" if out["leads"] == 1 else "") + f"); {out['multi_agency_any_year']} groups "
                      f"have 2+ agencies in any year; {prec}. Leads to ask about, not savings, and not additive.")
    return out


def _precision(groups, multi, main):
    """Top-20 precision: from a verdict column in the data, else a machine-readable block or the sentence in the model card
    (only while the card's grouping matches the data), else 'see model card'."""
    col = next((c for c in VERDICT_COLS if groups and c in groups[0]), None)
    if col:
        checked = [r for r in multi if (r.get(col) or "").strip()][:20]
        if checked:
            real = sum(1 for r in checked if (r[col] or "").strip().lower().startswith("real"))
            return {"k": len(checked), "real": real, "of": len(checked), "source": f"d_grant_groups.{col}"}
    card = (DOCS / "models" / "grant_groups.md").read_text() if (DOCS / "models" / "grant_groups.md").exists() else ""
    m = PRECISION_BLOCK.search(card)
    if m:
        try:
            d = json.loads(m.group(1))
            return {"k": int(d.get("k", d.get("of"))), "real": int(d["real"]), "of": int(d["of"]), "source": "docs/models/grant_groups.md (facts block)"}
        except (ValueError, KeyError, TypeError):
            pass
    m = PRECISION.search(card)
    row = {r.group("t"): int(r.group("g").replace(",", "")) for r in CARD_ROW.finditer(card)}
    want = str(main.get("cosine_threshold", ""))
    card_groups = row.get(want) or row.get(want.rstrip("0"))
    if m and card_groups is not None and card_groups == len(groups):
        return {"k": int(m.group("k")), "real": int(m.group("real")), "of": int(m.group("of")), "source": "docs/models/grant_groups.md (hand check)"}
    reason = "no hand check found in the model card" if not m else (
        f"the model card's hand check was made on {card_groups:,} groups; the data now has {len(groups):,}" if card_groups is not None
        else "the model card's hand check could not be matched to this grouping")
    return {"k": 20, "real": None, "of": None, "source": "see model card", "reason": reason}


# ------------------------------------------------------------------------------------------------ 4. MCP server
def mcp_tools():
    """[(name, first line of the description)] registered on src/mcp/server.py's MCPServer (SDK), else read from its source."""
    try:
        import anyio

        from src.mcp.server import build
        ts = anyio.run(build(None).list_tools)
        return [{"name": t.name, "description": (t.description or "").strip().splitlines()[0],
                 "read_only": bool(getattr(getattr(t, "annotations", None), "read_only_hint", False))} for t in ts], "MCP SDK list_tools()"
    except Exception:  # noqa: BLE001 - the SDK is optional: fall back to the source
        tree = ast.parse((ROOT / "src" / "mcp" / "server.py").read_text())
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool" for d in node.decorator_list):
                out.append({"name": node.name, "description": (ast.get_docstring(node) or "").splitlines()[0], "read_only": True})
        return out, "src/mcp/server.py (AST: @server.tool functions)"


def _pick(obj, path):
    if path.startswith("len:"):
        return len(_pick(obj, path[4:]))
    parts = re.findall(r"[^.\[\]]+|\[[^\]]+\]", path)
    cur = obj
    for i, p in enumerate(parts):
        if p.startswith("["):
            k, v = p[1:-1].split("=", 1)
            cur = next(x for x in cur if str(x.get(k)) == v)
        elif p == "*":
            rest = ".".join(parts[i + 1:])
            return [_pick(x, rest) if rest else x for x in cur]
        elif isinstance(cur, list):
            cur = cur[int(p)]
        else:
            cur = cur[p]
    return cur


def _same(got, want, tol):
    if isinstance(want, list):
        return isinstance(got, list) and len(got) == len(want) and all(_same(g, w, tol) for g, w in zip(got, want))
    if want is None or got is None:
        return got is None and want is None
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        return abs(float(got) - float(want)) <= tol
    return str(got) == str(want)


def golden_eval(src):
    """The 30-question golden set of tests/test_mcp.py, run in-process on the export: each answer from the tool (through an
    in-process MCP client when the SDK is installed), each expected value from its own SQL on a separate connection."""
    import duckdb

    from src.mcp import tools
    from src.mcp.store import Store
    golden = yaml.safe_load(GOLDEN_YAML.read_text())
    st = Store(export_dir=src, prefer="export")
    pq = src / "parquet"

    def source(t):
        f = pq / f"{t}.parquet"
        return f"read_parquet('{f}')" if f.exists() else f"read_csv_auto('{src / (t + '.csv')}')"

    def expected(sql, as_list):
        con = duckdb.connect(":memory:")
        try:
            vals = [r[0] for r in con.execute(re.sub(r"\{(\w+)\}", lambda m: source(m.group(1)), sql)).fetchall()]
        finally:
            con.close()
        return vals if as_list else (vals[0] if len(vals) == 1 else ("<rows>", len(vals)))

    answers, via = {}, "tool functions"
    try:
        import anyio
        from mcp import Client

        from src.mcp.server import build

        async def go():
            async with Client(build(st)) as c:
                for q in golden:
                    r = await c.call_tool(q["tool"], q["args"])
                    answers[q["id"]] = None if r.is_error else r.structured_content
        anyio.run(go)
        via = "in-process MCP client"
    except ImportError:
        for q in golden:
            answers[q["id"]] = getattr(tools, q["tool"])(st, **q["args"])
    failed = []
    for q in golden:
        try:
            ok = answers.get(q["id"]) is not None and _same(_pick(answers[q["id"]], q["answer"]), expected(q["expected_sql"], q.get("expect") == "list"), q.get("tol", 0.005))
        except Exception:  # noqa: BLE001 - a missing key or a failed query is a failed question
            ok = False
        if not ok:
            failed.append(q["id"])
    run = st.run.get("run_id")
    st.close()
    return {"passed": len(golden) - len(failed), "total": len(golden), "failed": failed, "via": via, "backend": "export",
            "run_id": run, "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "source": "measured during the site build"}


def security_tests():
    """Number of test cases pytest collects from tests/test_mcp_security.py (parametrized cases counted)."""
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests/test_mcp_security.py"],
                           cwd=ROOT, capture_output=True, text=True, timeout=120)
        m = re.search(r"(\d+) tests? collected", r.stdout)
        if m:
            return int(m.group(1)), "pytest --collect-only"
    except (OSError, subprocess.SubprocessError):
        pass
    tree = ast.parse((ROOT / "tests" / "test_mcp_security.py").read_text())
    return sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test")), "test functions (AST)"


def transcript_excerpt(md, want=("query",)):
    """Calls from the generated transcript in docs/mcp.md: [{call, args, json|error}]."""
    m = re.search(r"<!-- transcript -->(.*?)<!-- /transcript -->", md, re.S)
    if not m:
        return []
    items = []
    for blk in re.split(r"^\*\*Call\*\* ", m.group(1), flags=re.M)[1:]:
        h = re.match(r"`([^`]+)` `([^`]*)`", blk)
        if not h:
            continue
        js = re.search(r"```json\n(.*?)```", blk, re.S)
        err = re.search(r"\*\*Error:\*\* `([^`]*)`", blk)
        items.append({"call": h.group(1), "args": h.group(2), "json": js.group(1).rstrip() if js else None, "error": err.group(1) if err else None})
    return [i for i in items if i["call"] in want]


def mcp(src):
    md = (DOCS / "mcp.md").read_text()
    doc = (ROOT / "src" / "mcp" / "server.py").read_text()
    what = ast.get_docstring(ast.parse(doc)).splitlines()[0]
    ts, via = mcp_tools()
    guard = []
    for m in re.finditer(r"^\d+\.\s+\*\*([^*]+)\*\*\s*(.*?)(?=^\d+\.\s|^\S|\Z)", _section(md, "Guardrails"), re.S | re.M):
        guard.append({"title": m.group(1).strip(), "text": " ".join(m.group(2).split())})
    desk = re.search(r"```json\n(.*?)```", _section(md, "Claude Desktop"), re.S)
    if GOLDEN_RESULTS.exists():
        golden = json.loads(GOLDEN_RESULTS.read_text()) | {"source": str(GOLDEN_RESULTS.relative_to(ROOT))}
    else:
        golden = golden_eval(src)
    n_sec, sec_via = security_tests()
    ex = transcript_excerpt(md)
    out = {"what": what, "tools": ts, "tools_via": via, "guardrails": guard, "golden": golden, "security_tests": n_sec, "security_via": sec_via,
           "desktop_config": desk.group(1).rstrip() if desk else "", "transcript": ex}
    out["finding"] = (f"{len(ts)} read-only tools answer {golden['passed']} of {golden['total']} golden questions exactly "
                      f"(measured {golden['date']}), and {n_sec} security tests hold the server to one SELECT on a locked, read-only connection.")
    return out


# ------------------------------------------------------------------------------------------------ 5. briefs
def briefs(src, k=6):
    import os

    from src.briefs import facts as F
    from src.briefs import guardrail
    from src.briefs.generate import agency_list
    from src.mcp.store import Store
    rows = _csv(DOCS / "briefs_sample.csv")
    md = (DOCS / "briefs.md").read_text()
    steps = [{"title": m.group(1).strip(), "text": " ".join(m.group(2).split())}
             for m in re.finditer(r"^\d+\.\s+\*\*([^*]+)\*\*\s*(.*?)(?=^\d+\.\s|^\S|\Z)", _section(md, "Guardrail"), re.S | re.M)]
    out = {"samples": [{c: r[c] for c in ("agency_code", "agency", "fiscal_year", "brief", "backend", "guardrail", "run_id")} for r in rows[:k]],
           "rows": len(rows), "passed": sum(1 for r in rows if r["guardrail"] == "passed"),
           "backends": sorted({r["backend"] for r in rows}), "steps": steps,
           "key_set_at_build": bool(os.environ.get("GEMINI_API_KEY")), "demo": None}
    # a live demonstration of the guardrail on the first sample: the sentence as written, and one with its first figure changed
    if rows:
        st = Store(export_dir=src, prefer="export")
        try:
            r0 = rows[0]
            f = next((x for x in F.agency_facts(st, int(r0["fiscal_year"])) if x["agency_code"] == r0["agency_code"]), None)
            if f and f["display"].get("payments") in r0["brief"]:
                ags = agency_list(st)
                wrong = F.fmt_money(f["payments"] * 1.1)
                bad = r0["brief"].replace(f["display"]["payments"], wrong, 1)
                out["demo"] = {"agency_code": r0["agency_code"], "original_problems": guardrail.check(r0["brief"], f, ags),
                               "true_value": f["display"]["payments"], "tampered_value": wrong, "tampered": bad,
                               "tampered_problems": guardrail.check(bad, f, ags)}
        finally:
            st.close()
    out["finding"] = (f"{out['passed']} of {out['rows']} sample briefs pass the numeric guardrail; every one was written by the "
                      f"{', '.join(out['backends'])} backend, because live Gemini needs GEMINI_API_KEY.")
    return out


# ------------------------------------------------------------------------------------------------ collect, render, write
def collect(src):
    src = Path(src)
    run = ""
    p = src / "pipeline_runs.csv"
    if p.exists():
        runs = [r for r in _csv(p) if r.get("status") == "passed"]
        run = max(runs, key=lambda r: r["started_utc"]).get("run_id", "") if runs else ""
    return {"run_id": run, "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "payment_screen": payment_screen(src), "payee_classifier": payee_classifier(src), "grant_overlap": grant_overlap(src),
            "mcp": mcp(src), "briefs": briefs(src)}


def _find(text):
    return f'<div class="ai-find"><b>Finding</b>{esc(text)}</div>'


def _dl(items):
    return '<dl class="ai-dl">' + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in items) + "</dl>"


def _table(head, rows, num_cols=()):
    th = "".join(f'<th{" class=num" if i in num_cols else ""}>{esc(h)}</th>' for i, h in enumerate(head))
    tb = "".join("<tr>" + "".join(f'<td{" class=num" if i in num_cols else ""}>{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="tbl"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'


def _status(s):
    tone = {"needs_records": "warn", "likely_legitimate": "ok", "confirmed_duplicate_in_source": "bad"}.get(s, "")
    return f'<span class="chip {tone}">{esc(s)}</span>'


def _sec_payment(d):
    t1 = _table(["Confidence", "Review status", "Groups", "Records", "Review dollars"],
                [[esc(g["confidence"]), _status(g["review_status"]), num(g["groups"]), num(g["records"]), money(g["review_amount"])] for g in d["by_confidence_status"]],
                (2, 3, 4))
    t2 = _table(["Issue", "Agency", "Second-block records", "Second-block $", "Identical to first block", "Screen groups moved", "Verified"],
                [[esc(i["issue_id"]), esc(i["agency"]), num(i["records"]), money(i["amount"]), num(i["identical_records"]), num(i["screen_groups"]),
                  f'{esc(i["verified_on"])}<br><span class="k">{esc(i["verified_against"])}</span>'] for i in d["source_issues"]], (2, 3, 4, 5))
    split = "; ".join(f"{esc(k)}: {esc(', '.join(v))}" for k, v in d["rule_status"].items())
    lever = " / ".join(pct(x, 0) for x in d["lever_rates"])
    return ("<h2>1. Payment screen</h2>"
            '<p class="ai-q"><b>Question.</b> Which State payments should a reviewer look at as a possible duplicate, a line published twice, or a split purchase?</p>'
            + _dl([("Method", "Fixed rules in SQL over the payments data (same agency, vendor and exact amount; record dates within 7 days; the split rule "
                              "needs dated payments), then a confidence score and an evidence review from the published fields only. Rules and thresholds "
                              f"were set before the counts were taken. Rule status on this data: {split}."),
                   ("Result vs baseline", f"Baseline (every flagged group): <b>{num(d['baseline_groups'])}</b> groups, {money(d['baseline_review_amount'])} review dollars. "
                    f"After the source issues are kept apart: <b>{num(d['leads'])}</b> leads, {num(d['lead_records'])} records, {money(d['lead_total_amount'])} in groups, "
                    f"<b>{money(d['lead_review_amount'])}</b> review dollars." + t1),
                   ("Source issues (verified at the source)", f"{len(d['source_issues'])} data-publication issues, {num(d['source_issue_groups'])} screen groups "
                    f"({money(d['source_issue_review_amount'])}) moved out of the leads. They are in the published source, not overpayments." + t2),
                   ("Calculator lever", f'<span class="chip warn">{esc(d["rate_basis"])}</span> {d["confirmed_leads"]} of {d["reviewed_leads"]} leads confirmed '
                    f"from the data; measured confirmation rate: {esc(d['measured_confirmation_rate'] or 'not measured')}; FY{esc(d['lever_fy'])} lever rates low / likely / high: {lever}."),
                   ("Review sheet", f"{link(d['review_sheet'])}: {d['review_sheet_rows']} leads, {d['review_sheet_decided']} with a reviewer decision so far."),
                   ("Limits", "Payments are annual records per agency, payee and ZIP, not individual payments with dates, so the split rule cannot be measured and "
                    "no lead can be confirmed without invoices or payment records. A lead is a question, not an error and not money owed."),
                   ("Code and model card", f"{link('sql/mart/48_d_payment_screen.sql')} · {link('sql/mart/50_d_source_issues.sql')} · {link('docs/models/payment_screen.md', 'model notes')}")])
            + _find(d["finding"]))


def _sec_payee(d):
    t = d["table"]
    lab = {"accuracy": f"Accuracy ({d['scored']} scored names)", "macro_f1": "Macro F1", "accuracy_on_default_names": f"Accuracy on the {d['default_scored']} default-labeled names",
           "dollars_classified_share": "Share of $ classified", "dollars_relabeled_share": "Share of $ relabeled vs the rules"}

    def cell(m, k):
        x = t[m][k]
        return "n/a" if x is None else (pct(x, 0) if m.startswith("dollars") else f"{x:.2f}")
    t1 = _table(["", "Rules (baseline)", "Model", "Combined"], [[esc(lab[m])] + [cell(m, k) for k in ("rules", "model", "combined")] for m in t], (1, 2, 3))
    t2 = _table(["Class", "Scored", "Rules F1", "Model F1", "Combined F1"],
                [[esc(c), num(v["n"])] + [f"{v[k]:.2f}" if v[k] is not None else "n/a" for k in ("rules", "model", "combined")] for c, v in d["per_class_f1"].items()], (1, 2, 3, 4))
    t3 = _table(["#", "Payee", "Rule class", "Model says", "Confidence", "Paid, all years"],
                [[str(i + 1), esc(q["payee"]) if q["payee"] != MASK else f'<i>{esc(MASK)}</i> <span class="k">{esc(q["payee_key"][:10])}</span>',
                  esc(q["rule_class"]), esc(q["model_label"]), f"{q['confidence']:.2f}", money(q["paid_all_years"])] for i, q in enumerate(d["top_queue"])], (0, 4, 5))
    return ("<h2>2. Payee classifier</h2>"
            '<p class="ai-q"><b>Question.</b> Can a text model label who each payment went to (business, government, nonprofit, individual, other) better than the name rules the dashboard uses?</p>'
            + _dl([("Method", f"TF-IDF character n-grams and logistic regression trained on the rule labels of {d['training_names']:,} payee names (every evaluated name and its "
                              f"vendor's other names held out); combined = the rule where a rule decided, the model where the rules fell to the default. Evaluated on {d['labeled']} "
                              f"hand-labeled names ({d['excluded_unsure']} unsure, excluded)."),
                   ("Result vs baseline", t1 + "<p class='k'>Per class F1:</p>" + t2),
                   ("Decision", f'<span class="chip {"ok" if d["promoted"] else "warn"}">{"promoted" if d["promoted"] else "not promoted"}</span> {esc(d["why"])}. '
                    "The model's share of dollars classified mostly repeats the rules' default bucket; the relabeled share is what it adds."),
                   (f"Review queue: {d['review_queue']:,} names (top {len(d['top_queue'])} by dollars)",
                    t3 + f"<p class='k'>{d['review_queue_masked_in_top']} of these {len(d['top_queue'])} names may be a person's and stay masked; the key links back to the database.</p>"),
                   ("Limits", f"The labels are single-annotator (Claude, from the name text alone), pending Sierra's review: {d['reviewed_by_sierra']} of {d['labeled']} reviewed so far. "
                    "The sample is stratified, so per-class numbers have wide intervals; the model learns the rules' labels and inherits their errors, and cannot predict individual/withheld."),
                   ("Code and model card", f"{link('src/models/payee_classifier.py')} · {link('docs/models/payee_classifier.md', 'model card')} · {link('reference/payee_labels_sample.csv', 'labels')}")])
            + _find(d["finding"]))


def _sec_grants(d):
    fy = d["fiscal_year"]
    t1 = _table(["Threshold", "Groups", "2+ descriptions", f"FY{fy} leads", "Lead $", "2+ agencies any year", f"Their FY{fy} $"],
                [[("<b>" + esc(s["cosine_threshold"]) + "</b> (used)") if _b(s["main"]) else esc(s["cosine_threshold"]), num(s["groups"]), num(s["multi_description_groups"]),
                  num(s["overlap_leads"]), money(s["lead_amount_fy"]), num(s["multi_agency_any_year"]), money(s["multi_agency_any_year_amount_fy"])] for s in d["sensitivity"]],
                (1, 2, 3, 4, 5, 6))
    t2 = _table(["Group (representative description)", "Agencies (all years)", f"FY{fy} $"],
                [[esc(g["description"]), esc(g["grantor_agencies"]), money(g["amount_fy"])] for g in d["top_multi"]], (2,))
    p = d["precision"]
    prec = (f"<b>{p['real']} of {p['of']}</b> real ({pct(p['real'] / p['of'], 0)}) in the hand check of the top {p['k']} any-year groups "
            f"<span class='k'>({esc(p['source'])})</span>") if p.get("real") is not None else \
        f"See the {link('docs/models/grant_groups.md', 'model card')} <span class='k'>({esc(p.get('reason', ''))})</span>"
    leads = "; ".join(f"“{esc(a)}” ({esc(b)})" for a, b in zip(d["lead_descriptions"], d["lead_agencies"])) or "none"
    return ("<h2>3. Grant overlap</h2>"
            '<p class="ai-q"><b>Question.</b> Do different grantor agencies fund grants with the same purpose (possible overlap to ask about)?</p>'
            + _dl([("Method", f"{num(d['descriptions'])} distinct grant descriptions embedded with <code>{esc(d['backend'])}</code> and clustered (agglomerative, cosine, "
                              f"threshold {esc(d['threshold'])} set before looking). A lead = a group funded by 2+ grantor agencies in the same year, FY{fy}."),
                   ("Result vs baseline", f"<b>{num(d['groups'])}</b> groups ({num(d['multi_description_groups'])} with 2+ descriptions; {num(d['groups_with_fy_amount'])} with FY{fy} dollars, "
                    f"{money(d['fy_amount_in_groups'])}). Same-year leads: <b>{num(d['leads'])}</b> ({money(d['lead_amount_fy'])}): {leads}. The looser reading, 2+ agencies "
                    f"in any year: {num(d['multi_agency_any_year'])} groups ({money(d['multi_agency_any_year_amount_fy'])} of FY{fy} grants). Sensitivity:" + t1),
                   ("Top-20 precision", prec),
                   (f"Largest {len(d['top_multi'])} any-year groups by FY{fy} dollars", t2),
                   ("Limits", "Leads, not savings: a group says only that agencies funded grants described alike. Grant dollars are not additive with payments, across groups or "
                    "across thresholds. Most apparent overlap is one agency under several names (renames, fund names in the grantor field) until a grantor-agency map resolves them."),
                   ("Code and model card", f"{link('src/models/grant_groups.py')} · {link('docs/models/grant_groups.md', 'model card')}")])
            + _find(d["finding"]))


def _sec_mcp(d):
    g = d["golden"]
    tools_t = _table(["Tool", "What it answers", "Read-only"], [[f"<code>{esc(t['name'])}</code>", esc(t["description"]), "yes" if t["read_only"] else "no"] for t in d["tools"]])
    guard = '<ul class="ai-list">' + "".join(f"<li><b>{esc(x['title'])}</b> {_inline(x['text'])}</li>" for x in d["guardrails"]) + "</ul>"
    tr = "".join(f"<p class='k'><b>Call</b> <code>{esc(x['call'])}</code> <code>{esc(x['args'])}</code></p>"
                 + (f'<pre class="ai-pre" tabindex="0">{esc(x["json"])}</pre>' if x["json"] else f'<pre class="ai-pre" tabindex="0">Error: {esc(x["error"])}</pre>')
                 for x in d["transcript"])
    gold = (f'<span class="chip {"ok" if g["passed"] == g["total"] else "bad"}">{g["passed"]}/{g["total"]}</span> golden questions answered exactly, '
            f"{esc(g['source'])} on {esc(g['date'])} (run {esc(g.get('run_id') or '')}, {esc(g.get('via', ''))}; each expected value from independent SQL on its own connection)"
            + (f"; failed: {esc(', '.join(g['failed']))}" if g.get("failed") else "") + ".")
    cfg = (f'<pre class="ai-pre" id="mcpCfg" tabindex="0">{esc(d["desktop_config"])}</pre>'
           '<div class="copy-row"><button type="button" class="copy" id="mcpCopy" aria-describedby="mcpCopyMsg">Copy config</button>'
           '<span class="k" id="mcpCopyMsg" role="status" aria-live="polite"></span></div>')
    return ("<h2>4. MCP server</h2>"
            '<p class="ai-q"><b>Question.</b> Can an AI agent such as Claude query the tracker\'s data directly, safely, and get answers it can cite?</p>'
            + _dl([("What it is", esc(d["what"])),
                   ("Method", "The official Python MCP SDK over stdio; each tool is a plain function over a read-only DuckDB store, and every answer carries a "
                              "provenance block (tables, run, as-of date). Tested with a fixed golden set of questions whose expected answers come from independent SQL."),
                   (f"Tools ({len(d['tools'])}, from {d['tools_via']})", tools_t),
                   ("Guardrails", guard),
                   ("Result vs baseline", gold + f" Security: <b>{d['security_tests']}</b> tests ({esc(d['security_via'])}) run refused statements through the check, the tool and the bare connection."),
                   ("Claude Desktop config", "Settings &gt; Developer &gt; Edit Config, with the paths of your clone:" + cfg),
                   ("From the real transcript", tr + f"<p class='k'>Generated by <code>python -m src.mcp.transcript --write</code>; full transcript in {link('docs/mcp.md')}.</p>"),
                   ("Limits", "Read-only and local: it serves the exported marts (or the database file) on your machine over stdio; it does not explain or verify a figure beyond the provenance block it returns."),
                   ("Code", f"{link('src/mcp/server.py')} · {link('src/mcp/guard.py')} · {link('tests/test_mcp.py')} · {link('tests/test_mcp_security.py')} · {link('docs/mcp.md', 'docs')}")])
            + _find(d["finding"]))


def _sec_briefs(d):
    samples = "".join(f'<blockquote class="brief"><p>{esc(s["brief"])}</p><span class="chip">{esc(s["agency_code"])}</span> '
                      f'<span class="chip">backend: {esc(s["backend"])}</span> <span class="chip {"ok" if s["guardrail"] == "passed" else "warn"}">guardrail: {esc(s["guardrail"])}</span></blockquote>'
                      for s in d["samples"])
    steps = '<ul class="ai-list">' + "".join(f"<li><b>{esc(x['title'])}</b> {_inline(x['text'])}</li>" for x in d["steps"]) + "</ul>"
    demo = ""
    if d["demo"]:
        x = d["demo"]
        demo = (f"<p>Run during this build on the first sample ({esc(x['agency_code'])}): as written, "
                f"{'<span class=ok>passes</span>' if not x['original_problems'] else '<span class=bad>fails: ' + esc('; '.join(x['original_problems'])) + '</span>'}. "
                f"With {esc(x['true_value'])} changed to {esc(x['tampered_value'])}: "
                + ("<span class=bad>rejected</span>: " + esc("; ".join(x["tampered_problems"])) if x["tampered_problems"] else "<span class=warn>not caught</span>") + ".</p>")
    return ("<h2>5. Gemini briefs</h2>"
            '<p class="ai-q"><b>Question.</b> Can a language model write a one-line summary per agency without ever inventing a number?</p>'
            + _dl([("Method", "Facts are computed from the marts; a generator (Gemini through the google-genai SDK, or a deterministic template) writes one sentence; "
                              "a guardrail checks every figure and agency name against the facts, and any sentence that fails is replaced by the template sentence."),
                   ("Backend used", f"<b>{esc(', '.join(d['backends']))}</b> for all {d['rows']} sample briefs. Live Gemini needs <code>GEMINI_API_KEY</code> in the environment "
                    f"(the key is never stored in the repository); without it the template is used. Key present during this build: {'yes' if d['key_set_at_build'] else 'no'}."),
                   ("Result vs baseline", f"Baseline: the deterministic template sentence, which must itself pass. Result: {d['passed']} of {d['rows']} sample briefs pass "
                    f"the guardrail; {d['rows'] - d['passed']} were replaced. A generated sentence is kept only when it passes, so the output is never worse than the template."),
                   (f"{len(d['samples'])} sample briefs (of {d['rows']}; {d['passed']} pass)", samples),
                   ("How the guardrail works", steps + demo),
                   ("Limits", "The sentence can only restate the facts it is given; it explains nothing. The samples come from the template, so they show the guardrail's input "
                    "format, not Gemini's wording."),
                   ("Code", f"{link('src/briefs/generate.py')} · {link('src/briefs/guardrail.py')} · {link('docs/briefs.md', 'docs')} · {link('docs/briefs_sample.csv', 'samples')}")])
            + _find(d["finding"]))


SECTIONS = [("payment-screen", "Payment screen", "payment_screen", _sec_payment), ("payee-classifier", "Payee classifier", "payee_classifier", _sec_payee),
            ("grant-overlap", "Grant overlap", "grant_overlap", _sec_grants), ("mcp-server", "MCP server", "mcp", _sec_mcp),
            ("gemini-briefs", "Gemini briefs", "briefs", _sec_briefs)]

COPY_JS = """<script>(()=>{const b=document.getElementById('mcpCopy'),p=document.getElementById('mcpCfg'),m=document.getElementById('mcpCopyMsg');if(!b||!p)return;
function sel(){const r=document.createRange();r.selectNodeContents(p);const s=window.getSelection();s.removeAllRanges();s.addRange(r);return s;}
function fallback(){sel();let ok=false;try{ok=document.execCommand('copy');}catch(e){ok=false;}m.textContent=ok?'Copied.':'Selected: press Ctrl+C (Cmd+C) to copy.';}
b.addEventListener('click',()=>{const t=p.textContent;try{if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(()=>{m.textContent='Copied.';},fallback);return;}}catch(e){}fallback();});})();</script>"""


def body(facts):
    toc = '<ul class="ai-toc">' + "".join(f'<li><a href="#{a}">{esc(t)}</a><p>{esc(facts[k]["finding"])}</p></li>' for a, t, k, _ in SECTIONS) + "</ul>"
    parts = ["<h1>AI layer</h1>",
             "<p>Five pieces of machine learning and AI tooling sit on top of the pipeline. Each is shown with the question it answers, its method, "
             "its result against a baseline, its limits, and a one-line finding computed from the data at build time"
             f"{' (run ' + esc(facts['run_id']) + ')' if facts.get('run_id') else ''}. None of them is a source of savings: they produce leads to review and "
             "better data. The numbers are also in <a href=\"data/ai_layer.json\">data/ai_layer.json</a>.</p>", toc]
    for a, _, k, fn in SECTIONS:
        parts.append(f'<section class="ai" id="{a}" aria-labelledby="{a}-h">' + fn(facts[k]).replace("<h2>", f'<h2 id="{a}-h">', 1) + "</section>")
    parts.append(COPY_JS)
    return "\n".join(parts)


def write(out, src):
    """Write out/data/ai_layer.json and return (facts, body html)."""
    facts = collect(src)
    (Path(out) / "data").mkdir(parents=True, exist_ok=True)
    (Path(out) / "data" / "ai_layer.json").write_text(json.dumps(facts, indent=1, default=str) + "\n")
    return facts, body(facts)
