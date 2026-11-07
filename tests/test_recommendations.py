"""The six recommendations on small constructed cases (no data/ needed)."""
import duckdb
import pandas as pd
import pytest

from src.models import recommendations as R


def _pay(rows):
    """rows: (agency, vendor, payee, amount, fiscal_year)."""
    return pd.DataFrame([{"fiscal_year": fy, "agency_code": a, "vendor": v, "vendor_name": payee, "amount": amt} for a, v, payee, amt, fy in rows])


def test_vendor_detail_lists_payments_by_agency_and_year_and_payee_names_for_fy2026():
    pay = _pay([("A01", "ACME", "ACME INC", 100.123, 2025), ("A01", "ACME", "ACME INC", 50.0, 2026), ("A02", "ACME", "ACME LLC", 25.0, 2026),
                ("A01", "ACME", "ACME INC", 999.0, 2021), ("A01", "OTHER", "OTHER CO", 7.0, 2026)])
    f, n = R.vendor_detail(pay, ["acme"])  # matched whatever the case
    assert set(f.vendor) == {"Acme"} and f[(f.agency_code == "A01") & (f.fiscal_year == 2025)].paid.iloc[0] == 100.12
    assert 2021 not in set(f.fiscal_year) and len(f) == 3  # nothing before FY2022; A01 twice, A02 once
    assert dict(zip(n.payee_name, n.fy2026)) == {"ACME INC": 50.0, "ACME LLC": 25.0}  # FY2026 only


def _plan_inputs(bids):
    model = pd.DataFrame({"area": ["Telecom", "Fleet & fuel", "Real estate & leases", "Utilities & facility energy"],
                          "gmi_rate": [0.10, None, None, None]})
    fc = pd.DataFrame({"area": ["Telecom", "Fleet & fuel", "Real estate & leases", "Utilities & facility energy", "Telecom"],
                       "fiscal_year": [2027, 2027, 2027, 2027, 2026], "p50": [100e6, 500e6, 200e6, 300e6, 1.0]})
    return model, fc, pd.DataFrame(bids, columns=["vendor", "fy2026", "agencies"])


def test_step_one_is_gmis_rate_times_the_fy2027_median_and_areas_without_a_rate_add_nothing():
    plan = R.plan50(*_plan_inputs([("V1", 100e6, 12)]))
    assert plan.step.iloc[0] == 1 and plan.saving.iloc[0] == 10e6  # 10% of Telecom's FY2027 $100M, not its FY2026 value
    assert plan.action.iloc[0] == "Keep GMI's current savings going"


def test_contracts_are_added_until_the_target_is_reached_and_then_nothing_more():
    plan = R.plan50(*_plan_inputs([("V1", 600e6, 12), ("V2", 600e6, 10), ("V3", 600e6, 10)]))  # 3.5% of $600M = $21M each
    assert list(plan.action) == ["Keep GMI's current savings going", "Statewide contract: V1", "Statewide contract: V2"]  # $10M + $21M + $21M >= $50M
    assert plan.cumulative.iloc[-1] == pytest.approx(52e6) and plan.saving.iloc[1] == pytest.approx(21e6) and plan.tab.iloc[1] == "opp"
    assert plan.basis.iloc[1] == "assumed 3.5% of $600.0M paid by 12 agencies (assumed range 2-5%)"


def test_fallback_areas_are_added_when_the_contracts_fall_short():
    plan = R.plan50(*_plan_inputs([("V1", 10e6, 12)]))
    assert list(plan.action)[-2:] == ["Start savings in real estate & leases at 1%", "Start savings in utilities & facility energy at 1%"]
    assert plan.saving.iloc[-2] == 2e6 and plan.saving.iloc[-1] == 3e6 and plan.cumulative.is_monotonic_increasing and list(plan.step) == list(range(1, len(plan) + 1))


def _chk(rows):
    return pd.DataFrame(rows, columns=["check_id", "status", "changed"])


def test_status_rows_state_the_key_numbers():
    bids = pd.DataFrame({"vendor": ["V1", "V2"], "low": [1e6, 2.5e6], "high": [4e6, 3.5e6]})
    chk = _chk([("S01", "Seen", False), ("S06", "Partly seen", True), ("S10", "Not seen yet", False), ("S02", "Payments fell", False),
                ("S03", "Payments fell", False), ("S04", "Payments did not fall", False), ("S05", "Payments fell", False)])
    plan = pd.DataFrame({"cumulative": [20e6, 51e6]})
    st = R.status(bids, chk, plan, 0.987, (2957, 108, 111, 106)).set_index("rec")
    assert st.loc[1, "progress"] == "2 vendors ranked; $3.5M–$7.5M a year"
    assert st.loc[2, "progress"] == "1 of 3 checks seen in payments; 1 changed since last run"
    assert "payments fell for 3 of 4" in st.loc[3, "progress"]
    assert st.loc[4, "status"] == "Plan reaches $50M" and st.loc[4, "progress"] == "2 steps to $51.0M a year"
    assert st.loc[5, "progress"] == "98.7% of FY2026 payments matched to an agency"
    assert list(R.status(bids, chk, pd.DataFrame({"cumulative": [20e6]}), 1.0).set_index("rec").loc[4, ["status"]]) == ["Gap remains"]


def test_recommendation_six_is_read_from_the_managing_for_results_data_not_a_stale_text():
    assert R.results_row((2957, 108, 111, 106)) == ("Data in place", "2,957 performance measures read from 108 of 111 agency plans; 106 plans matched to a budget agency")
    assert R.results_row(None)[0] == "Needs a data feed" and R.results_row((0, 0, 0, 0))[0] == "Needs a data feed"  # the plans were not available


def test_previous_comes_from_the_last_earlier_run_and_a_rerun_never_compares_with_itself():
    cur = pd.DataFrame({"rec": [1, 2], "title": ["a", "b"], "status": ["s", "s"], "progress": ["now1", "now2"], "tab": ["x", "x"]})
    assert R.with_previous(cur, R.read_history("/nonexistent"), "R3").previous.isna().all()
    hist = pd.DataFrame({"run_id": ["R1", "R2", "R3"], "rec": [1, 1, 1], "title": "a", "status": "s", "progress": ["old", "last", "this run"], "tab": "x"})
    out = R.with_previous(cur, hist, "R3").set_index("rec")
    assert out.loc[1, "previous"] == "last" and pd.isna(out.loc[2, "previous"])


def test_history_is_recorded_once_per_run_and_replaced_on_a_rerun(tmp_path):
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA mart")
    con.execute("CREATE TABLE mart.d_rec_status AS SELECT 1 AS rec, 'a' AS title, 'Ready' AS status, 'first' AS progress, 'opp' AS tab")
    assert R.record(con, "R1", tmp_path) == 1
    con.execute("CREATE OR REPLACE TABLE mart.d_rec_status AS SELECT 1 AS rec, 'a' AS title, 'Ready' AS status, 'second' AS progress, 'opp' AS tab")
    R.record(con, "R1", tmp_path)
    R.record(con, "R2", tmp_path)
    h = R.read_history(tmp_path)
    assert list(h.run_id) == ["R1", "R2"] and list(h.progress) == ["second", "second"]


def test_every_assumption_comes_from_the_assumptions_file():
    cfg = R.assumptions()
    assert cfg["target_saving"] == 50_000_000 and cfg["plan"]["contract_rate"] == 0.035 and cfg["matched_fy"] == 2026
    assert cfg["plan"]["fallback_areas"] == ["Real estate & leases", "Utilities & facility energy"]
