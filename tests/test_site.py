"""The GitHub Pages site builds from the export (or the checked-in site_data/ snapshot) without a network or a browser."""
import re
from pathlib import Path

import pytest
import yaml

from src.pipeline import site

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    try:
        src = site.source_dir()
    except SystemExit:
        pytest.skip("no export and no site_data/ snapshot")
    return site.build(tmp_path_factory.mktemp("site") / "site", src)


def test_index_has_disclaimer_and_no_banner(built):
    page = (built / "index.html").read_text()
    assert "Independent prototype by Sierra Napier, built from Maryland&#x27;s open data; not an official State of Maryland product" in page
    assert "Preview for approval" not in page
    assert "https://github.com/EVO3-Ecosystem/gmi-savings-tracker" in page
    assert re.search(r"Data as of \d{4}-\d{2}-\d{2}", page)


def test_data_is_fetched_by_relative_path_not_embedded(built):
    page = (built / "index.html").read_text()
    assert "var RAW={};" in page and site.STUB_START not in page
    assert "fetch('data/'+f+'.csv')" in page
    assert len(page) < 2_000_000  # the 11 MB of CSVs are not inlined
    # nothing loads from another host or an absolute path (outbound <a> links to sources are fine)
    assert not re.search(r"""\bsrc=["']?(?:https?:|/)""", page)
    assert not re.search(r"""<link[^>]+href=["']?(?:https?:|/)""", page)
    assert not re.search(r"""fetch\(\s*['"](?:/|https?:)""", page)


def test_every_dashboard_dataset_is_published(built):
    cfg = yaml.safe_load((ROOT / "config" / "dashboard.yaml").read_text())
    missing = [f for f in cfg.values() if not (built / "data" / f"{f}.csv").is_file()]
    assert not missing, missing
    assert len(cfg) >= 44


def test_support_pages(built):
    assert "Allow: /" in (built / "robots.txt").read_text()
    assert "Page not found" in (built / "404.html").read_text()
    about = (built / "about.html").read_text()
    assert "Sierra Napier" in about and "<table>" in about and 'src="figures/pipeline.png"' in about
    for img in re.findall(r'src="(figures/[^"]+)"', about):
        assert (built / img).is_file(), img
    assert not re.search(r"<script[^>]+src=", about)


def test_snapshot_covers_the_dashboard():
    snap = ROOT / "site_data"
    if not snap.exists():
        pytest.skip("no site_data/ snapshot")
    cfg = yaml.safe_load((ROOT / "config" / "dashboard.yaml").read_text())
    assert all((snap / f"{f}.csv").is_file() for f in cfg.values())


def test_parquet_copied_for_the_explorer(built):
    pq = sorted((built / "parquet").glob("*.parquet"))
    if not pq:
        pytest.skip("export has no Parquet files")
    cfg = yaml.safe_load((ROOT / "config" / "dashboard.yaml").read_text())
    assert {f.stem for f in pq} >= set(cfg.values())


def test_publish_stage_has_card_and_manifest(tmp_path):
    from src.pipeline import publish
    try:
        src = site.source_dir()
    except SystemExit:
        pytest.skip("no export and no site_data/ snapshot")
    if not site.parquet_files(src):
        pytest.skip("export has no Parquet files")
    out = publish.stage(tmp_path / "stage", src)
    card = (out / "README.md").read_text()
    assert card.startswith("---\nlicense: other") and "Source datasets" in card and "d_payment_screen" in card
    assert (out / "manifest.csv").exists() and len(list((out / "parquet").glob("*.parquet"))) >= 40


def test_explorer_pins_duckdb_wasm_and_has_a_fallback(built):
    from src.pipeline import site_explorer
    if not (built / "explorer.html").exists():
        pytest.skip("no Parquet files, so no explorer")
    page = (built / "explorer.html").read_text()
    assert re.fullmatch(r"\d+\.\d+\.\d+", site_explorer.DUCKDB_WASM)
    assert "@duckdb/duckdb-wasm@' + __EX.ver" in page and f'ver: "{site_explorer.DUCKDB_WASM}"' in page
    assert "getJsDelivrBundles" in page and "createObjectURL(new Blob" in page and "(pq ? 'parquet/' : 'data/')" in page
    assert '__EX.source === \'parquet\'' in page and 'source: "parquet"' in page and 'download: true' in page
    assert "function fallback(" in page and "data/' + t + '.csv'" in page and len(site_explorer.EXAMPLES) == 6
    assert 'href="explorer.html"' in (built / "index.html").read_text()


def test_catalog_lists_tables_columns_checks_and_lineage(built):
    page = (built / "catalog.html").read_text()
    assert "<svg" in page and "Lineage" in page and 'href="catalog.html"' in (built / "index.html").read_text()
    n = page.count('<details class="t"')
    wh = (ROOT / "docs" / "schemas" / "warehouse_columns.csv").read_text().splitlines()[1:]
    assert n == len({r.split(",", 1)[0] for r in wh}) and n > 50
    assert "mart.d_payment_screen" in page and "review_amount" in page


# --- the analysis stage's payment-screen interface (confidence, review status, source issues, measured rate) ----------
def interface_fixture(src, dst):
    """Copy an export's CSVs to dst and reshape the payment screen the way the analysis stage will publish it:
    d_payment_screen gains confidence/review_status/review_note/agency_raw and loses the FY2022 MDTA/MES double listing,
    which moves to a new d_source_issues.csv; d_payment_screen_summary gains measured_confirmation_rate, rate_basis and the
    review counts, with every lever rate 0 (as the analysis stage publishes it while no rate can be measured)."""
    import shutil
    import pandas as pd
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.csv"):
        shutil.copy(f, dst / f.name)
    g = pd.read_csv(src / "d_payment_screen.csv")
    dbl = (g.fiscal_year == 2022) & (g.rule == "Repeated annual line") & g.agency_code.isin(["J11", "U10"])
    issues = (g[dbl].groupby(["agency_code", "agency"], as_index=False)
              .agg(records=("n", "sum"), amount=("review_amount", "sum")))
    issues = pd.DataFrame({
        "issue_id": [f"SI-2022-{c}" for c in issues.agency_code],
        "issue": "FY2022 payments listed twice (record dates 2022-01-01 and 2023-01-01)",
        "fiscal_year": 2022, "agency": issues.agency, "records": issues.records, "amount": issues.amount,
        "agency_code": issues.agency_code, "agency_raw": issues.agency, "identical_records": issues.records // 2, "identical_amount": issues.amount,
        "screen_groups": issues.records // 2, "screen_records": issues.records, "screen_review_amount": issues.amount,
        "evidence": "Every FY2022 payee line for the agency appears twice with identical amounts, one copy dated in the next calendar year",
        "verified_against": "vendorpayments.maryland.gov FY2022 totals", "verified_on": "2026-11-09", "status": "Confirmed in source"})
    g = g[~dbl].copy()
    g["confidence"] = ["high" if (r.rule == "Possible duplicate" and r.amount >= 100_000) else "medium" if r.rule == "Possible duplicate" else "low"
                       for r in g.itertuples()]
    g["confidence_score"] = g.confidence.map({"high": 1, "medium": 0, "low": -2})
    g["review_status"] = "needs_records"
    g["review_note"] = "Awaiting agency payment records"
    g["agency_raw"] = g.agency
    g.to_csv(dst / "d_payment_screen.csv", index=False)
    issues.to_csv(dst / "d_source_issues.csv", index=False)
    s = pd.read_csv(src / "d_payment_screen_summary.csv")
    agg = g.groupby(["rule", "fiscal_year"]).agg(groups=("group_id", "size"), records=("n", "sum"), total_amount=("total_amount", "sum"),
                                                 review_amount=("review_amount", "sum"))
    for col in ["groups", "records", "total_amount", "review_amount"]:
        s[col] = [agg[col].get((r.rule, r.fiscal_year), 0) for r in s.itertuples()]
    s["measured_confirmation_rate"] = None
    s["rate_basis"] = "not measurable without payment records"
    s["lever_rate_low"] = s["lever_rate_likely"] = s["lever_rate_high"] = 0.0
    s["reviewed_leads"], s["confirmed_leads"] = len(g), 0
    s.to_csv(dst / "d_payment_screen_summary.csv", index=False)
    return dst


@pytest.fixture(scope="module")
def iface_src(tmp_path_factory):
    try:
        src = site.source_dir()
    except SystemExit:
        pytest.skip("no export and no site_data/ snapshot")
    return interface_fixture(src, tmp_path_factory.mktemp("iface") / "export")


def test_optional_source_issues_are_loaded_when_published(iface_src, tmp_path):
    out = site.build(tmp_path / "site", iface_src)
    page = (out / "index.html").read_text()
    assert '"d_source_issues": "d_source_issues"' in page and (out / "data" / "d_source_issues.csv").is_file()
    assert 'id="psIssues"' in page and "Data-quality issues in the source" in page


def test_missing_source_issues_are_not_requested(built):
    if (built / "data" / "d_source_issues.csv").exists():
        pytest.skip("this export already publishes d_source_issues")
    page = (built / "index.html").read_text()
    assert '"d_source_issues": "d_source_issues"' not in page  # nothing fetches a file that is not there (no 404 on load)


# --- the two variants: GitHub Pages and the claude.ai artifact -----------------------------------------------------------
@pytest.fixture(scope="module")
def artifact(tmp_path_factory):
    try:
        src = site.source_dir()
    except SystemExit:
        pytest.skip("no export and no site_data/ snapshot")
    return site.build(tmp_path_factory.mktemp("art") / "art", src, artifact=True)


def test_pages_variant_keeps_download_copy_and_hosting_files(built):
    assert (built / "404.html").is_file() and (built / "robots.txt").is_file() and (built / ".nojekyll").is_file()
    if not (built / "explorer.html").exists():
        pytest.skip("no Parquet files, so no explorer")
    ex = (built / "explorer.html").read_text()
    assert re.search(r'<button id="exCsv" disabled>Download results \(CSV\)</button>', ex)
    assert 'id="exCopy"' in ex and "navigator.clipboard.writeText" in ex and "t.select()" in ex


def test_artifact_variant(artifact):
    assert not (artifact / "parquet").exists() and not list(artifact.rglob("*.parquet"))
    for f in ("404.html", "robots.txt", ".nojekyll"):
        assert not (artifact / f).exists(), f
    ex = (artifact / "explorer.html").read_text()
    assert 'source: "csv"' in ex and "read_csv_auto" in ex and "download: false" in ex
    assert re.search(r'<button id="exCsv" disabled hidden>', ex) and re.search(r'<button id="fbCsv" disabled hidden>', ex)
    assert 'id="exCopy"' in ex and "navigator.clipboard.writeText" in ex
    tables = re.search(r"tables: (\[[^\]]*\])", ex).group(1)
    import json
    assert all((artifact / "data" / f"{t}.csv").is_file() for t in json.loads(tables))
    for f in artifact.rglob("*"):
        if f.is_file() and f.suffix in site.TEXT_EXT:
            assert "\ufffd" not in f.read_text(encoding="utf-8", errors="replace"), f
    assert (artifact / "index.html").is_file() and (artifact / "catalog.html").is_file() and (artifact / "about.html").is_file()
    total = sum(f.stat().st_size for f in artifact.rglob("*") if f.is_file())
    assert total < 64e6 and len([f for f in artifact.rglob("*") if f.is_file()]) <= 255  # one artifact publish


def test_replacement_chars_are_scrubbed_and_reported(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.csv").write_text("a,b\nCaf\ufffd,\ufffd\ufffd\n", encoding="utf-8")
    (tmp_path / "y.png").write_bytes(b"\x89PNG\xef\xbf\xbd")
    assert site.scrub_replacement_chars(tmp_path) == {"data/x.csv": 3}
    assert (tmp_path / "data" / "x.csv").read_text() == "a,b\nCaf?,??\n" and (tmp_path / "y.png").read_bytes().endswith(b"\xef\xbf\xbd")


def test_every_page_is_theme_aware(built):
    """Colours are tokens with dark values under prefers-color-scheme (guarded by data-theme="light") and data-theme="dark"."""
    for name in ("index.html", "about.html", "catalog.html", "explorer.html"):
        f = built / name
        if not f.exists():
            continue
        page = f.read_text()
        assert '@media (prefers-color-scheme: dark){:root:not([data-theme="light"])' in page, name
        assert ':root[data-theme="dark"]{' in page, name
        assert re.search(r"body\{[^}]*background:var\(--", page), name
        assert ":focus-visible{outline:2px solid var(--" in page, name
    index = (built / "index.html").read_text()
    assert "colors:['var(--series-1)'" in index and "--series-1:#3987e5" in index  # d3 series read CSS variables; dark steps defined
    assert "#fff7e0" not in index and "border-bottom:1px solid #e4e3de" not in index
