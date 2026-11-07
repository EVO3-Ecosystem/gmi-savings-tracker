"""The ported savings checks reproduce the legacy scripts' output on the real payments. Needs data/md_transparency.duckdb (skipped in CI)."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from src.models import savings as V

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "md_transparency.duckdb"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="no database built (CI)")


def _legacy(name):
    spec = importlib.util.spec_from_file_location(f"legacy_{name}", ROOT / "legacy" / "gst" / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _payments():
    import duckdb
    con = duckdb.connect(str(DB), read_only=True)
    return con.execute("SELECT fiscal_year, agency_code, vendor, vendor_name, area, amount, is_government, passthrough FROM mart.payment_area").df()


def test_the_four_tables_match_the_legacy_scripts(tmp_path):
    pay = _payments()
    pm = pay.rename(columns={"vendor": "family", "area": "lens"})
    old_d, old_f, old_mv = _legacy("savings").build(pm)
    old_st = _legacy("recs").recurrence(old_d, old_f, "RUN1", tmp_path / "h.csv")
    d, f = V.check_payments(pay)
    for new, old in ((d, old_d), (f, old_f), (V.vendor_moves(pay), old_mv), (V.status(d, f, "RUN1"), old_st)):
        pd.testing.assert_frame_equal(new[old.columns].reset_index(drop=True), old.reset_index(drop=True), check_dtype=False)


def test_stored_tables_have_the_documented_dashboard_columns():
    import duckdb
    doc = pd.read_csv(ROOT / "docs" / "schemas" / "dashboard_columns.csv")
    con = duckdb.connect(str(DB), read_only=True)
    for t in ("d_savings", "f_savings_check", "d_vendor_moves", "d_savings_status"):
        assert list(con.execute(f"SELECT * FROM mart.{t}").df().columns) == list(doc[doc.table == t].column), t
