"""The ported detectors and bid list reproduce the legacy scripts' output on the real marts. Needs data/md_transparency.duckdb (skipped in CI)."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from src.models import opportunities as O

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "md_transparency.duckdb"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="no database built (CI)")


def _legacy(name):
    spec = importlib.util.spec_from_file_location(f"legacy_{name}", ROOT / "legacy" / "gst" / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _inputs():
    import duckdb
    return O.inputs(duckdb.connect(str(DB), read_only=True))


def _legacy_payments(payments):
    return payments.rename(columns={"vendor": "family", "area": "lens"}).assign(vendor_name=lambda d: d.family)


def test_detectors_match_the_legacy_script():
    code_agency, agency_year, payments = _inputs()
    old = _legacy("opportunities").build(code_agency, agency_year.sort_values("fiscal_year", ascending=False), _legacy_payments(payments))
    new = O.detect(code_agency, agency_year, payments)
    pd.testing.assert_frame_equal(new[old.columns].reset_index(drop=True), old.reset_index(drop=True), check_dtype=False)


def test_bid_list_matches_the_legacy_script():
    _, agency_year, payments = _inputs()
    recs = _legacy("recs")
    names = agency_year.sort_values("fiscal_year").groupby("agency_code").agency.last()
    old = recs.bid_list(recs._ops(_legacy_payments(payments)), names)
    new = O.bid_list(payments, agency_year)
    pd.testing.assert_frame_equal(new[old.columns].reset_index(drop=True), old.reset_index(drop=True), check_dtype=False)


def test_stored_tables_have_the_documented_dashboard_columns():
    import duckdb
    doc = pd.read_csv(ROOT / "docs" / "schemas" / "dashboard_columns.csv")
    con = duckdb.connect(str(DB), read_only=True)
    for t in ("d_opps", "d_bid_list"):
        assert list(con.execute(f"SELECT * FROM mart.{t}").df().columns) == list(doc[doc.table == t].column), t
