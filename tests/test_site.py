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
    assert "getJsDelivrBundles" in page and "createObjectURL(new Blob" in page and "new URL('parquet/'" in page
    assert "function fallback(" in page and "data/' + t + '.csv'" in page and len(site_explorer.EXAMPLES) == 6
    assert 'href="explorer.html"' in (built / "index.html").read_text()


def test_catalog_lists_tables_columns_checks_and_lineage(built):
    page = (built / "catalog.html").read_text()
    assert "<svg" in page and "Lineage" in page and 'href="catalog.html"' in (built / "index.html").read_text()
    n = page.count('<details class="t"')
    wh = (ROOT / "docs" / "schemas" / "warehouse_columns.csv").read_text().splitlines()[1:]
    assert n == len({r.split(",", 1)[0] for r in wh}) and n > 50
    assert "mart.d_payment_screen" in page and "review_amount" in page
