"""site/catalog.html: every warehouse table with its layer, description, rows, columns, the checks that read it, and lineage.

Built only from files checked into the repository, so it also builds in CI from the site_data/ snapshot:
docs/schemas/warehouse_columns.csv (columns, types, definitions, row counts; written by src/pipeline/governance.py),
docs/schemas/check_coverage.csv (the tables each check's queries read, ops.check_coverage), docs/schemas/lineage.csv
(what each table was built from, ops.lineage), sql/mart/*.sql headers (descriptions), config/datasets.yaml and
config/dashboard.yaml (sources and published tables), and the export's run_checks.csv (each check's latest result).
The overview diagram is inline SVG.
"""
import csv
import html
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCH = ROOT / "docs" / "schemas"
REPO = "https://github.com/EVO3-Ecosystem/gmi-savings-tracker"

LAYERS = {
    "raw": "Portal rows exactly as delivered, plus the extract run ID; never edited.",
    "ref": "Dimensions derived from the portal and the hand-kept reference CSVs (reference/), with their change control.",
    "core": "Typed and normalized facts (codes, names, partial years), and the mapped payments and budget scope.",
    "mart": "Tables the dashboard and models read: SQL marts (sql/mart/) and the outputs of the Python models (src/models/).",
    "ops": "Run bookkeeping: what the portal reported, check results, coverage and lineage, payee-name history.",
}
CONTEXT = {"cpi": "BLS CPI-U (CUUR0000SA0)", "population": "Census population estimates, Maryland",
           "federal_awards": "USAspending federal awards to Maryland governments", "mfr_index": "DBM Managing for Results plans"}
PY = {  # tables written by the Python models and fact builders (descriptions; the SQL marts describe themselves)
    "f_forecast": "Spending forecast by focus area and year with the bootstrap range (src/models/forecast.py).",
    "d_forecast_model": "Forecast model chosen for each area and its backtest error (src/models/forecast.py).",
    "d_forecast_backtest": "Rolling-origin backtest of the forecast models (src/models/forecast.py).",
    "d_forecast_calibration": "How often the forecast ranges held actual spending in the backtest (src/models/forecast.py).",
    "d_opps": "Opportunity findings of the four detectors (src/models/opportunities.py; docs/models/opportunities.md).",
    "d_bid_list": "Statewide bid list: vendors paid separately by many agencies (src/models/opportunities.py).",
    "d_detector_backtest": "The detectors rerun as of FY2022-FY2024, flags followed one year (src/models/backtest.py).",
    "d_savings": "GMI's reported savings items with page and quote (src/models/savings.py).",
    "f_savings_check": "Payments paired with each reported saving (src/models/savings.py).",
    "d_savings_status": "Status of each savings check: Seen, Partly seen, Not seen yet (src/models/savings.py).",
    "d_vendor_moves": "Largest payment decreases by vendors many agencies pay (src/models/savings.py).",
    "d_plan50": "The conditional path to $50M a year, step by step (src/models/recommendations.py).",
    "d_rec_status": "The six recommendations, their status and key number (src/models/recommendations.py).",
    "f_vendor_detail": "Vendor drill-downs by agency and year (src/models/recommendations.py).",
    "d_vendor_names": "Payee names merged into each vendor (src/models/recommendations.py).",
    "d_master_quality": "Quality of the agency and vendor master lists (src/pipeline/facts.py).",
    "sources": "Source datasets with portal dates and row counts (src/pipeline/facts.py).",
    "pipeline_runs": "Pipeline runs and their check counts (src/pipeline/facts.py).",
    "run_checks": "The latest run's checks and results (src/pipeline/facts.py).",
    "measures": "What each year-over-year column means, from the mart headers (src/pipeline/marts.py).",
    "stage_evidence": "How each budget year's stage was confirmed (reference/stage_evidence.csv).",
}

TONE = {"pass": "ok", "warn": "warn", "fail": "fail"}

TOKENS = """<style>
main.wide{max-width:1180px}
:root{--c-raw:#eb6834;--c-ref:#eda100;--c-core:#1baf7a;--c-mart:#2a78d6;--c-ops:#6250d6;--s-panel:#fff}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--s-panel:#1e1e1d}}
:root[data-theme="dark"]{--s-panel:#1e1e1d}
.lin{overflow-x:auto;border:1px solid var(--s-line);border-radius:8px;padding:8px;background:var(--s-panel)}
.lin svg{display:block;min-width:720px;width:100%;height:auto}
.lin text{fill:var(--s-fg);font:12px ui-sans-serif,system-ui,sans-serif}.lin .mut{fill:var(--s-muted)}
.lin rect.n{fill:var(--s-bg);stroke:var(--s-line)}.lin path{fill:none;stroke:var(--s-muted);stroke-opacity:.55}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0}
input[type=search],select{font:inherit;font-size:14px;padding:4px 10px;border:1px solid var(--s-line);border-radius:6px;background:var(--s-panel);color:var(--s-fg);max-width:100%}
details.t{border:1px solid var(--s-line);border-radius:8px;margin:6px 0;background:var(--s-panel)}
details.t>summary{cursor:pointer;padding:8px 12px;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}
details.t>summary b{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:14px;word-break:break-all}
details.t .in{padding:0 12px 12px}
.pill{display:inline-block;border-radius:999px;padding:0 8px;font-size:12px;color:#fff}.pill.ref,.pill.core,.pill.raw{color:#0b0b0b}
.k{color:var(--s-muted);font-size:13px}
.ck{font-size:13px;margin:4px 0 8px;padding-left:18px}.ck li{margin:2px 0}
.ok{color:#1a7f37}.warn{color:#9a6700}.fail{color:#b42318}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]) .ok{color:#7ee2a8}:root:not([data-theme="light"]) .warn{color:#f2cc60}:root:not([data-theme="light"]) .fail{color:#ff8a80}}
.tbl table{font-size:13px}.tbl td:first-child{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
</style>"""


def _csv(path):
    return list(csv.DictReader(open(path))) if Path(path).exists() else []


def describe_sql():
    out = {}
    for f in sorted((ROOT / "sql" / "mart").glob("*.sql")):
        name = f.stem.split("_", 1)[1]
        lines = [ln[2:].strip() for ln in f.read_text().splitlines() if ln.startswith("--")]
        lines = [ln for ln in lines if not ln.startswith("yoy:")]
        what = " ".join(ln for ln in lines[1:] if ln and not ln.startswith(("Check", "Checks")))
        out[f"mart.{name}"] = (lines[0] if lines else "") + (" " + what if what else "") + f" (sql/mart/{f.name})"
    return out


def sources_of(t, deps, memo):
    if t in memo:
        return memo[t]
    memo[t] = set()
    if t.startswith("raw."):
        memo[t] = {t}
        return memo[t]
    acc = set()
    for d in deps.get(t, []):
        acc |= sources_of(d, deps, memo)
    memo[t] = acc
    return acc


def svg(src_nodes, layer_n, layer_edges, published, feeds):
    """Sources (left) -> layers (middle) -> published dashboard tables (right); edge labels = tables fed."""
    W, rowh = 940, 30
    H = max(len(src_nodes) * rowh + 40, 5 * 56 + 40)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Lineage: source datasets to warehouse layers to published tables">']
    sy = {}
    for i, (k, label) in enumerate(src_nodes):
        y = 20 + i * rowh
        sy[k] = y + 11
        out.append(f'<rect class="n" x="4" y="{y}" width="300" height="22" rx="5"/><text x="12" y="{y + 15}">{html.escape(label if len(label) <= 46 else label[:45] + "…")}<title>{html.escape(label)}</title></text>')
    order = ["raw", "ref", "core", "mart", "ops"]
    lx, ly = 430, {}
    for i, layer in enumerate(order):
        y = 20 + i * 56
        ly[layer] = y + 18
        out.append(f'<rect x="{lx}" y="{y}" width="150" height="36" rx="6" fill="var(--c-{layer})" fill-opacity=".16" stroke="var(--c-{layer})"/>'
                   f'<text x="{lx + 10}" y="{y + 15}"><tspan font-weight="600">{layer}</tspan></text><text class="mut" x="{lx + 10}" y="{y + 30}">{layer_n.get(layer, 0)} tables</text>')
    px, py = 720, 20 + 3 * 56
    out.append(f'<rect x="{px}" y="{py}" width="210" height="36" rx="6" fill="var(--c-mart)" fill-opacity=".3" stroke="var(--c-mart)"/>'
               f'<text x="{px + 10}" y="{py + 15}" font-weight="600">Published</text><text class="mut" x="{px + 10}" y="{py + 30}">{published} dashboard tables</text>')
    for k, y in sy.items():
        n = feeds.get(k, 0)
        out.append(f'<path d="M304 {y} C 370 {y}, 370 {ly["raw"]}, {lx} {ly["raw"]}" stroke-width="{1 + min(n, 48) / 8:.1f}"><title>{html.escape(k)} feeds {n} published tables</title></path>')
        out.append(f'<text class="mut" x="310" y="{y - 3}" font-size="10">{n}</text>')
    for (a, b), n in sorted(layer_edges.items()):
        if a == b or a not in ly or b not in ly:
            continue
        ya, yb = ly[a], ly[b]
        x0 = lx + 150 if order.index(b) > order.index(a) else lx
        bend = 40 + 14 * abs(order.index(b) - order.index(a))
        sx = x0 + (bend if x0 > lx else -bend)
        out.append(f'<path d="M{x0} {ya} C {sx} {ya}, {sx} {yb}, {x0} {yb}"><title>{a} to {b}: {n} dependencies</title></path>')
    out.append(f'<path d="M{lx + 150} {ly["mart"]} L {px} {py + 18}" stroke-width="3"/>')
    out.append("</svg>")
    return "".join(out)


def body(src):
    wh = _csv(SCH / "warehouse_columns.csv")
    cover = _csv(SCH / "check_coverage.csv")
    lin = _csv(SCH / "lineage.csv")
    res = {r["check"]: r.get("status", r.get("result", "")) for r in _csv(Path(src) / "run_checks.csv")}
    pub = set(yaml.safe_load((ROOT / "config" / "dashboard.yaml").read_text()).values())
    man = {r["file"]: r.get("rows", "") for r in _csv(Path(src) / "manifest.csv")}
    ds = yaml.safe_load((ROOT / "config" / "datasets.yaml").read_text())["datasets"]
    raw_label = {f"raw.{k}": f"{d['id']} {d.get('portal_name', k)}" for k, d in ds.items()} | {f"raw.{k}": v for k, v in CONTEXT.items()}
    desc = describe_sql()
    tables = defaultdict(list)
    rows = {}
    for r in wh:
        tables[r["table"]].append(r)
        rows[r["table"]] = r["table_rows"]
    deps = defaultdict(list)
    for r in lin:
        deps[r["table_name"]].append(r["depends_on"])
    checks = defaultdict(list)
    for r in cover:
        for t in (r.get("tables") or "").split():
            checks[t].append(r["check"])
    memo, feeds = {}, defaultdict(int)
    for t in tables:
        if t.startswith("mart.") and t[5:] in pub:
            for s in sources_of(t, deps, memo):
                feeds[s] += 1
    layer_n = defaultdict(int)
    for t in tables:
        layer_n[t.split(".")[0]] += 1
    edges = defaultdict(int)
    for t, ds_ in deps.items():
        for d in ds_:
            edges[(d.split(".")[0], t.split(".")[0])] += 1
    src_nodes = [(k, raw_label.get(k, k)) for k in sorted((t for t in tables if t.startswith("raw.")), key=lambda k: (k[4:] in CONTEXT, k))]
    parts = ['<h1>Database catalog</h1>',
             f'<p>Every table in the warehouse ({len(tables)} tables in five layers), with its description, row count, columns and their definitions, '
             'the checks whose queries read it, and what it was built from. The published dashboard tables are the marts marked <i>published</i>; '
             'they are also on the <a href="explorer.html">data explorer</a> and as CSV in <code>data/</code>.</p>',
             '<h2>Lineage</h2><p class="k">Source datasets feed the raw layer; the line width and number show how many published tables each one feeds '
             '(followed through the recorded lineage). Arrows between layers are table-to-table dependencies.</p>',
             '<div class="lin">' + svg(src_nodes, layer_n, edges, len(pub), feeds) + '</div>',
             '<h2>Tables</h2><div class="row"><input type="search" id="cQ" placeholder="Find a table or column" aria-label="Find a table or column">'
             '<select id="cL" aria-label="Layer"><option value="">All layers</option>' + "".join(f'<option value="{k}">{k}</option>' for k in LAYERS) + '</select>'
             '<label class="k"><input type="checkbox" id="cP"> Published only</label><span class="k" id="cN"></span></div>']
    parts.append('<dl class="k">' + "".join(f"<dt><b>{k}</b></dt><dd>{html.escape(v)}</dd>" for k, v in LAYERS.items()) + "</dl>")
    order = {k: i for i, k in enumerate(LAYERS)}
    for t in sorted(tables, key=lambda x: (order.get(x.split(".")[0], 9), x)):
        layer, name = t.split(".", 1)
        is_pub = layer == "mart" and name in pub
        d = desc.get(t) or (PY.get(name) if layer == "mart" else "") or (f"Rows of {raw_label[t]} as delivered by the portal." if t in raw_label else LAYERS.get(layer, ""))
        srcs = sorted(sources_of(t, deps, memo)) if t in deps else []
        lin_txt = (" → ".join(filter(None, [", ".join(html.escape(raw_label.get(s, s).split(" ")[0]) for s in srcs) if srcs else "",
                                            ", ".join(f"<code>{html.escape(x)}</code>" for x in sorted(deps[t]))])) + f" → <code>{html.escape(t)}</code>") if deps.get(t) else \
            (f"{html.escape(raw_label[t])} → <code>{html.escape(t)}</code>" if t in raw_label else "No recorded inputs (loaded from a reference CSV or written by run bookkeeping).")
        ck = sorted(set(checks.get(t, [])))
        ck_html = ('<ul class="ck">' + "".join(f'<li><span class="{TONE.get(res.get(c, ""), "")}">{html.escape(res.get(c, "") or "")}</span> {html.escape(c)}</li>' for c in ck)
                   + "</ul>") if ck else '<p class="k">No check reads this table directly.</p>'
        cols = "".join(f"<tr><td>{html.escape(c['column'])}</td><td>{html.escape(c['type'])}</td><td>{html.escape(c.get('definition') or '')}</td></tr>" for c in tables[t])
        n_rows = int(float(rows[t])) if rows[t] not in ("", None) else 0
        search = " ".join([t] + [c["column"] for c in tables[t]]).lower()
        parts.append(f'<details class="t" data-l="{layer}" data-p="{1 if is_pub else 0}" data-s="{html.escape(search)}"><summary>'
                     f'<span class="pill {layer}" style="background:var(--c-{layer})">{layer}</span><b>{html.escape(t)}</b>'
                     f'<span class="k">{n_rows:,} rows · {len(tables[t])} columns{" · published" + (f" ({int(man[name]):,} rows exported)" if man.get(name) else "") if is_pub else ""} · {len(ck)} checks</span></summary>'
                     f'<div class="in"><p>{html.escape(d)}</p><p class="k"><b>Lineage:</b> {lin_txt}</p><p class="k"><b>Checks that read it</b> (latest run):</p>{ck_html}'
                     f'<div class="tbl"><table><thead><tr><th>Column</th><th>Type</th><th>Definition</th></tr></thead><tbody>{cols}</tbody></table></div></div></details>')
    parts.append(f'<p class="k">Column definitions: <a href="{REPO}/blob/main/reference/column_dictionary.csv">reference/column_dictionary.csv</a>; '
                 f'schemas: <a href="{REPO}/tree/main/docs/schemas">docs/schemas/</a>; governance: <a href="{REPO}/blob/main/docs/data-governance.md">docs/data-governance.md</a>. '
                 'Lineage is recorded from the build\'s own queries; for a table written by a Python model it lists the tables that model read.</p>')
    parts.append("""<script>(()=>{const q=document.getElementById('cQ'),l=document.getElementById('cL'),p=document.getElementById('cP'),n=document.getElementById('cN');
const all=[...document.querySelectorAll('details.t')];function f(){const s=q.value.trim().toLowerCase();let k=0;all.forEach(d=>{const ok=(!s||d.dataset.s.includes(s))&&(!l.value||d.dataset.l===l.value)&&(!p.checked||d.dataset.p==='1');d.hidden=!ok;if(ok)k++;});n.textContent=k+' of '+all.length+' tables';}
[q,l,p].forEach(e=>e.addEventListener(e===q?'input':'change',f));f();})();</script>""")
    return "\n".join(parts)
