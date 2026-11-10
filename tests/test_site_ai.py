"""site/ai.html (src/pipeline/site_ai.py): the page builds, has every section, is linked from every page, and every number it
shows equals the source files (the export, the docs, the code), including after the data change."""
import ast
import csv
import html
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from src.pipeline import site, site_ai

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ["payment-screen", "payee-classifier", "grant-overlap", "mcp-server", "gemini-briefs"]


@pytest.fixture(scope="module")
def src():
    try:
        return site.source_dir()
    except SystemExit:
        pytest.skip("no export and no site_data/ snapshot")


@pytest.fixture(scope="module")
def built(tmp_path_factory, src):
    return site.build(tmp_path_factory.mktemp("site") / "site", src)


@pytest.fixture(scope="module")
def page(built):
    return (built / "ai.html").read_text()


@pytest.fixture(scope="module")
def facts(built):
    return json.loads((built / "data" / "ai_layer.json").read_text())


def rows(path):
    return list(csv.DictReader(open(path, newline="", encoding="utf-8")))


def text(page):
    """The page's visible text, unescaped, with whitespace collapsed."""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", t)).split())


def test_page_builds_with_every_section_and_the_shell(page):
    assert page.startswith("<!doctype html>") and "<title>GMI AI layer</title>" in page and "<h1>AI layer</h1>" in page
    for s in SECTIONS:
        assert f'<section class="ai" id="{s}"' in page and f'href="#{s}"' in page, s
    for label in ("Question.", "Method", "Result vs baseline", "Limits", "Finding"):
        assert page.count(label) >= len(SECTIONS), label
    assert page.count('<div class="ai-find">') == len(SECTIONS)
    assert "not an official State of Maryland product" in page
    assert '@media (prefers-color-scheme: dark){:root:not([data-theme="light"])' in page and ':root[data-theme="dark"]{' in page
    assert ":focus-visible{outline:2px solid var(--" in page


def test_every_page_links_the_ai_layer(built):
    for name in ("index.html", "about.html", "catalog.html", "explorer.html", "ai.html", "404.html"):
        f = built / name
        if f.exists():
            assert 'href="ai.html"' in f.read_text(), name


def test_payment_screen_numbers_equal_the_export(src, facts, page):
    leads, issues = rows(src / "d_payment_screen.csv"), rows(src / "d_source_issues.csv")
    summ = rows(src / "d_payment_screen_summary.csv")
    d, t = facts["payment_screen"], text(page)
    assert d["leads"] == len(leads)
    assert d["lead_review_amount"] == pytest.approx(sum(float(r["review_amount"]) for r in leads))
    assert d["source_issue_groups"] == sum(int(r["screen_groups"]) for r in issues)
    assert d["baseline_groups"] == len(leads) + sum(int(r["screen_groups"]) for r in issues)
    assert sum(g["groups"] for g in d["by_confidence_status"]) == len(leads)
    assert {(g["confidence"], g["review_status"]) for g in d["by_confidence_status"]} == {(r["confidence"], r["review_status"]) for r in leads}
    assert d["rate_basis"] == summ[0]["rate_basis"] and d["rate_basis"] in t
    for r in issues:
        assert r["issue_id"] in t and r["verified_on"] in t
    assert site_ai.money(d["lead_review_amount"]) in t and f"{len(leads)} leads" in t
    assert site_ai.REVIEW_SHEET in page


def test_payee_classifier_numbers_equal_the_eval_file(src, facts, page):
    ev = {(r["method"], r["metric"], r["class"]): r for r in rows(src / "d_payee_class_eval.csv")}
    d, t = facts["payee_classifier"], text(page)
    for m in ("accuracy", "macro_f1"):
        for k in ("rules", "model", "combined"):
            assert d["table"][m][k] == float(ev[(k, m, "all")]["value"])
    for k in ("rules", "model", "combined"):
        assert site_ai.pct(float(ev[(k, "dollars_relabeled_share", "all")]["value"]), 0) in t
    assert d["promoted"] == bool(float(ev[("decision", "combined_promoted", "all")]["value"]))
    assert ("not promoted" in t) != d["promoted"]
    assert d["review_queue"] == int(float(ev[("model", "review_queue", "all")]["value"]))
    assert f"Review queue: {d['review_queue']:,} names" in t
    assert d["reviewed_by_sierra"] == int(float(ev[("sample", "reviewed_by_sierra", "all")]["value"]))
    assert "single-annotator" in t and "pending Sierra's review" in t
    pc = rows(src / "d_payee_class.csv")
    queue = sorted((r for r in pc if r["review_flag"] == "True"), key=lambda r: -float(r["paid_all_years"]))[:site_ai.TOP_QUEUE]
    assert [q["payee_key"] for q in d["top_queue"]] == [r["payee_key"] for r in queue]
    by_key = {r["payee_key"]: r for r in pc}
    for q in d["top_queue"]:
        assert q["payee"] in (by_key[q["payee_key"]]["payee"], site_ai.MASK)  # never a name the export does not publish
    assert d["review_queue_rows"] == sum(1 for r in pc if r["review_flag"] == "True")


def test_grant_overlap_numbers_equal_the_groups_file(src, facts, page):
    g, sens = rows(src / "d_grant_groups.csv"), rows(src / "d_grant_groups_sensitivity.csv")
    d, t = facts["grant_overlap"], text(page)
    col = next(c for c in g[0] if re.fullmatch(r"amount_fy\d{4}", c))
    assert d["groups"] == len(g) and d["fiscal_year"] == int(col[-4:])
    assert d["leads"] == sum(1 for r in g if r["overlap_lead"] == "True")
    assert d["lead_amount_fy"] == pytest.approx(sum(float(r[col]) for r in g if r["overlap_lead"] == "True"))
    assert d["multi_agency_any_year"] == sum(1 for r in g if r["multi_agency_any_year"] == "True")
    assert [s["groups"] for s in d["sensitivity"]] == [r["groups"] for r in sens]
    for r in sens:
        assert f"{int(r['groups']):,}" in t
    p = d["precision"]
    if p["real"] is None:
        assert p["source"] == "see model card" and "See the model card" in t
    else:
        assert f"{p['real']} of {p['of']}" in t
    assert "not savings" in t and "not additive" in t


def test_precision_falls_back_when_the_grouping_changed(src, tmp_path):
    """The model card's hand check is only shown while its group count matches the data (another change may regroup)."""
    for f in Path(src).iterdir():
        (tmp_path / f.name).symlink_to(f)
    g = rows(src / "d_grant_groups.csv")
    (tmp_path / "d_grant_groups.csv").unlink()
    with open(tmp_path / "d_grant_groups.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(g[0]))
        w.writeheader()
        w.writerows(g[:-1])
    d = site_ai.grant_overlap(tmp_path)
    assert d["groups"] == len(g) - 1
    assert d["precision"]["real"] is None and d["precision"]["source"] == "see model card"


def test_numbers_follow_the_data_not_the_code(src, tmp_path):
    """Drop a lead and change a metric in a copy of the export: the page's facts change with it."""
    for f in Path(src).iterdir():
        (tmp_path / f.name).symlink_to(f)
    leads = rows(src / "d_payment_screen.csv")
    (tmp_path / "d_payment_screen.csv").unlink()
    with open(tmp_path / "d_payment_screen.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(leads[0]))
        w.writeheader()
        w.writerows(leads[1:])
    ev = rows(src / "d_payee_class_eval.csv")
    for r in ev:
        if (r["method"], r["metric"], r["class"]) == ("rules", "macro_f1", "all"):
            r["value"] = "0.123"
    (tmp_path / "d_payee_class_eval.csv").unlink()
    with open(tmp_path / "d_payee_class_eval.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ev[0]))
        w.writeheader()
        w.writerows(ev)
    ps, pc = site_ai.payment_screen(tmp_path), site_ai.payee_classifier(tmp_path)
    assert ps["leads"] == len(leads) - 1 and ps["finding"].startswith(f"{len(leads) - 1} payment leads")
    assert pc["table"]["macro_f1"]["rules"] == 0.123 and "0.12" in pc["finding"]


def test_mcp_section_reads_the_server_and_the_golden_set(facts, page):
    d, t = facts["mcp"], text(page)
    tree = ast.parse((ROOT / "src" / "mcp" / "server.py").read_text())
    registered = sorted(n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                        and any(isinstance(x, ast.Call) and getattr(x.func, "attr", "") == "tool" for x in n.decorator_list))
    assert sorted(x["name"] for x in d["tools"]) == registered
    for name in registered:
        assert f"<code>{name}</code>" in page
    golden = yaml.safe_load((ROOT / "tests" / "fixtures" / "mcp_golden.yaml").read_text())
    g = d["golden"]
    assert g["total"] == len(golden) and 0 <= g["passed"] <= g["total"] and g["passed"] == g["total"] - len(g["failed"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", g["date"]) and f"{g['passed']}/{g['total']}" in t
    n_tests = sum(1 for n in ast.walk(ast.parse((ROOT / "tests" / "test_mcp_security.py").read_text())) if isinstance(n, ast.FunctionDef) and n.name.startswith("test"))
    assert d["security_tests"] >= n_tests and f"{d['security_tests']} tests" in t
    assert len(d["guardrails"]) >= 4 and all(x["title"] in t for x in d["guardrails"])
    assert '"mcpServers"' in d["desktop_config"] and html.escape(d["desktop_config"], quote=True) in page
    md = (ROOT / "docs" / "mcp.md").read_text()
    assert d["transcript"] and all(x["call"] == "query" and x["args"] in md for x in d["transcript"])
    # the Copy button writes inside the click handler and falls back to selecting the text
    assert 'id="mcpCopy"' in page and "addEventListener('click'" in page and "navigator.clipboard.writeText" in page
    assert "selectNodeContents" in page and "execCommand('copy')" in page


def test_briefs_section_shows_the_sample_file(facts, page):
    sample = rows(ROOT / "docs" / "briefs_sample.csv")
    d, t = facts["briefs"], text(page)
    assert [s["brief"] for s in d["samples"]] == [r["brief"] for r in sample[:6]]
    for r in sample[:6]:
        assert r["brief"] in t and f"guardrail: {r['guardrail']}" in t and f"backend: {r['backend']}" in t
    assert d["rows"] == len(sample) and d["passed"] == sum(1 for r in sample if r["guardrail"] == "passed")
    assert "GEMINI_API_KEY" in t and len(d["steps"]) >= 3
    if d["demo"]:
        assert d["demo"]["original_problems"] == [] and d["demo"]["tampered_problems"], "the guardrail rejects a changed figure"


def test_artifact_variant_has_the_ai_page(tmp_path, src):
    out = site.build(tmp_path / "artifact", src, artifact=True)
    assert (out / "ai.html").is_file() and (out / "data" / "ai_layer.json").is_file()
    shutil.rmtree(out)
