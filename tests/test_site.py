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
