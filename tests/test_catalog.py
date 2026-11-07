"""The measures catalog is generated from the `-- yoy:` headers of the mart SQL (no data/ needed)."""
import importlib.util
from pathlib import Path

import pandas as pd

from src.pipeline import marts

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = "Change in {v} from the previous fiscal year, as a share of the previous year"

# The 14 rows the legacy pipeline wrote (one per value of its ten Me.yoy calls in legacy/gst/scripts/run.py, in call order):
# (table, measure value, grouped by, higher_is)
LEGACY = [("totals_by_fy", "total_payments", "fiscal year", "neutral"), ("budget_by_function", "budget", "category_title", "neutral"),
          ("budget_by_fund", "budget", "fund_type_name", "neutral"), ("budget_by_object", "budget", "object_name", "lower"),
          ("budget_by_object", "controllable", "object_name", "lower"), ("spending_scope", "budget", "scope", "neutral"),
          ("agency_year", "controllable", "agency_code", "lower"), ("agency_year", "fte", "agency_code", "lower"),
          ("agency_year", "controllable_per_fte", "agency_code", "lower"), ("area_year", "spend", "area", "lower"),
          ("area_year", "payee_spend", "area", "lower"), ("area_agency_year", "spend", "area, agency_code", "lower"),
          ("area_code_year", "spend", "area, code", "lower"), ("area_vendor_year", "spend", "area, vendor", "lower")]


def test_the_catalog_has_the_legacy_rows_in_the_legacy_order():
    cat = marts.catalog()
    want = pd.DataFrame([{"table": t, "measure": f"{v}_yoy", "definition": DEFINITION.format(v=v), "grouped_by": g, "higher_is": h} for t, v, g, h in LEGACY])
    pd.testing.assert_frame_equal(cat.reset_index(drop=True), want)


def test_each_row_equals_what_the_legacy_measure_function_would_have_recorded():
    spec = importlib.util.spec_from_file_location("legacy_measures", ROOT / "legacy" / "gst" / "scripts" / "measures.py")
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    frame = pd.DataFrame({"fiscal_year": [2024, 2025], "area": "A", "code": "c", "spend": [1.0, 2.0], "stage": "Actual"})
    legacy.yoy(frame, ["area", "code"], ["spend"], table="area_code_year", good="lower")
    legacy.yoy(frame.assign(total_payments=1.0), [], ["total_payments"], table="totals_by_fy")
    old = legacy.catalog().reset_index(drop=True)
    new = marts.catalog()
    new = new[new.table.isin(["area_code_year", "totals_by_fy"])].set_index("table").loc[["area_code_year", "totals_by_fy"]].reset_index()
    pd.testing.assert_frame_equal(new[old.columns], old)


def test_headers_with_and_without_the_optional_parts(tmp_path):
    (tmp_path / "01_a.sql").write_text("-- yoy: keys=none values=v\nSELECT 1")
    (tmp_path / "02_b.sql").write_text("-- yoy: keys=k values=v,w stage\nSELECT 1")
    (tmp_path / "03_c.sql").write_text("-- yoy: keys=k,j values=v good=lower\nSELECT 1")
    (tmp_path / "04_d.sql").write_text("-- yoy: keys=k values=v stage good=lower\nSELECT 1")
    (tmp_path / "05_plain.sql").write_text("-- no change measure here\nSELECT 1")
    cat = marts.catalog(tmp_path)
    assert list(zip(cat.table, cat.measure, cat.grouped_by, cat.higher_is)) == [
        ("a", "v_yoy", "fiscal year", "neutral"), ("b", "v_yoy", "k", "neutral"), ("b", "w_yoy", "k", "neutral"),
        ("c", "v_yoy", "k, j", "lower"), ("d", "v_yoy", "k", "lower")]  # the file without a header adds nothing


def test_the_optional_good_flag_does_not_change_how_a_header_is_read():
    m = marts.HEAD.match("-- yoy: keys=a values=b stage good=lower")
    assert m.group(1) == "a" and m.group(2) == "b" and m.group(3) and m.group(4) == "lower"
    m = marts.HEAD.match("-- yoy: keys=a values=b good=lower")
    assert not m.group(3) and m.group(4) == "lower"
    m = marts.HEAD.match("-- yoy: keys=a values=b stage")
    assert m.group(3) and m.group(4) is None


def test_the_real_sql_marks_the_six_cost_tables_as_lower_is_better():
    cat = marts.catalog()
    assert sorted(set(cat[cat.higher_is == "lower"].table)) == ["agency_year", "area_agency_year", "area_code_year", "area_vendor_year", "area_year", "budget_by_object"]
    assert set(cat.higher_is) == {"lower", "neutral"}
