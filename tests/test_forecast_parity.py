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


def _marts():
    import duckdb
    con = duckdb.connect(str(DB), read_only=True)
    return tuple(con.execute(f"SELECT * FROM mart.{t}").df() for t in ("f_code", "f_scope", "f_fund"))


def test_port_with_the_legacy_rule_matches_the_legacy_forecast_and_model_table():
    f_code, f_scope, f_fund = _marts()
    old_f, old_m = _legacy().build(f_code, f_scope, f_fund)
    cfg = F.assumptions()
    cfg["forecast"]["selection"] = "legacy_single_split"
    new_f, new_m, _ = F.build(f_code, f_scope, f_fund, cfg)
    pd.testing.assert_frame_equal(new_f[old_f.columns], old_f, check_dtype=False)
    pd.testing.assert_frame_equal(new_m[old_m.columns], old_m, check_dtype=False)


def test_the_rolling_origin_rule_changes_only_utilities_and_leaves_other_areas_identical():
    f_code, f_scope, f_fund = _marts()
    old_f, old_m = _legacy().build(f_code, f_scope, f_fund)
    new_f, new_m, _ = F.build(f_code, f_scope, f_fund)
    changed = set(new_m.area[new_m.method.values != old_m.method.values])
    assert changed == {"Utilities & facility energy"}
    assert new_m.set_index("area").loc["Utilities & facility energy", "method"] == F.NAIVE
    same = ~new_f.area.isin(changed)
    pd.testing.assert_frame_equal(new_f[same][old_f.columns].reset_index(drop=True), old_f[same.values].reset_index(drop=True), check_dtype=False)


def test_stored_tables_have_the_documented_dashboard_columns():
    import duckdb
    doc = pd.read_csv(ROOT / "docs" / "schemas" / "dashboard_columns.csv")
    con = duckdb.connect(str(DB), read_only=True)
    for t in ("f_forecast", "d_forecast_model"):
        assert list(con.execute(f"SELECT * FROM mart.{t}").df().columns) == list(doc[doc.table == t].column), t
