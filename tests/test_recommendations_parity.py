"""The ported recommendations reproduce the legacy script's output on the real data (except recommendation 6, which is deliberately
read from this pipeline's own Managing for Results data). Needs data/md_transparency.duckdb (skipped in CI)."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from src.models import opportunities as O
from src.models import recommendations as R

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "md_transparency.duckdb"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="no database built (CI)")


def _legacy():
    spec = importlib.util.spec_from_file_location("legacy_recs", ROOT / "legacy" / "gst" / "scripts" / "recs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _con():
    import duckdb
    return duckdb.connect(str(DB), read_only=True)


def _same(new, old):
    pd.testing.assert_frame_equal(new[old.columns].reset_index(drop=True), old.reset_index(drop=True), check_dtype=False)


def test_vendor_detail_matches_the_legacy_function_on_both_bases():
    con = _con()
    rc, pay = _legacy(), R.inputs(con)
    pm = pay.rename(columns={"vendor": "family"})
    bids = con.execute("SELECT * FROM mart.d_bid_list").df()
    lev = con.execute("SELECT spending_code FROM mart.d_opps WHERE detector = 'Leverage'").df().spending_code.tolist()
    ops = rc._ops(pm)
    f1, n1 = R.vendor_detail(ops, list(bids.vendor) + lev)
    of1, on1 = rc.vendor_detail(ops, list(bids.vendor) + lev)
    _same(f1, of1)
    _same(n1, on1)
    rest = sorted(set(con.execute("SELECT DISTINCT vendor FROM mart.f_vendor").df().vendor) - {v.upper() for v in f1.vendor.str.upper()})
    f2, n2 = R.vendor_detail(pay, rest)
    of2, on2 = rc.vendor_detail(pm.assign(vendor=pm.family.fillna(pm.vendor_name).astype(str)), rest)
    _same(f2, of2)
    _same(n2, on2)


def test_plan_and_status_rows_one_to_five_match_the_legacy_script_and_row_six_is_the_deliberate_difference():
    con = _con()
    rc = _legacy()
    bids, fm, fc, chk = (con.execute(f"SELECT * FROM mart.{t}").df() for t in ("d_bid_list", "d_forecast_model", "f_forecast", "d_savings_status"))
    plan, old_plan = R.plan50(fm, fc, bids), rc.plan50(fm, fc, bids)
    _same(plan, old_plan)
    share = con.execute("SELECT sum(amount) FILTER (WHERE agency_code IS NOT NULL) / sum(amount) FROM core.fact_payment_mapped WHERE fiscal_year = 2026").fetchone()[0]
    new, old = R.status(bids, chk, plan, share, (2957, 108, 111, 106)), rc.status(bids, chk, old_plan, share)
    _same(new.iloc[:5].drop(columns="progress").assign(p=new.progress.str.split(" at the assumed rates").str[0].where(new.rec == 4, new.progress)),
          old.iloc[:5].drop(columns="progress").assign(p=old.progress))  # rec 4's progress now adds the plan's range after the legacy text
    assert old.iloc[5].status == "Needs a data feed" and new.iloc[5].status == "Data in place"


def test_stored_tables_have_the_documented_dashboard_columns():
    doc = pd.read_csv(ROOT / "docs" / "schemas" / "dashboard_columns.csv")
    con = _con()
    for t in ("d_plan50", "d_rec_status", "f_vendor_detail", "d_vendor_names"):
        assert list(con.execute(f"SELECT * FROM mart.{t}").df().columns) == list(doc[doc.table == t].column), t


def test_the_opportunity_module_and_the_recommendations_agree_on_the_bid_list_basis():
    assert O.assumptions()["bid_list"]["excluded_agency_codes"] == ["CAPITAL", "D06", "D25"]
