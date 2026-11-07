"""The ported forecast reproduces the legacy script's output on the real marts. Needs data/md_transparency.duckdb (skipped in CI)."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from src.models import forecast as F

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "md_transparency.duckdb"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="no database built (CI)")


def _legacy():
    spec = importlib.util.spec_from_file_location("legacy_forecast", ROOT / "legacy" / "gst" / "scripts" / "forecast.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_port_matches_the_legacy_forecast_and_model_table():
    import duckdb
    con = duckdb.connect(str(DB), read_only=True)
    f_code, f_scope, f_fund = (con.execute(f"SELECT * FROM mart.{t}").df() for t in ("f_code", "f_scope", "f_fund"))
    old_f, old_m = _legacy().build(f_code, f_scope, f_fund)
    new_f, new_m, _ = F.build(f_code, f_scope, f_fund)
    pd.testing.assert_frame_equal(new_f[old_f.columns], old_f, check_dtype=False)
    pd.testing.assert_frame_equal(new_m[old_m.columns], old_m, check_dtype=False)


def test_stored_tables_have_the_documented_dashboard_columns():
    import duckdb
    doc = pd.read_csv(ROOT / "docs" / "schemas" / "dashboard_columns.csv")
    con = duckdb.connect(str(DB), read_only=True)
    for t in ("f_forecast", "d_forecast_model"):
        assert list(con.execute(f"SELECT * FROM mart.{t}").df().columns) == list(doc[doc.table == t].column), t
