"""New-payee-name history (ops.payee_name_seen, data/payee_name_seen.csv): first run, identical rerun, a later run with
new names, and a failed build. Data-free: a tiny in-memory database stands in for ref.map_payee_vendor. The real failed
build is covered by tests/test_fault_injection.py, which also asserts that no history file is written."""
import duckdb
import pandas as pd

from src.pipeline import checks


def _con(names):
    con = duckdb.connect(":memory:")
    for s in ("ref", "ops"):
        con.execute(f"CREATE SCHEMA {s}")
    con.register("_n", pd.DataFrame({"payee": names}))
    con.execute("CREATE TABLE ref.map_payee_vendor AS SELECT payee FROM _n")
    return con


def _build(data, run_id, names, passes=True):
    """What build.py does: the check compares with the history, and only a passing build records."""
    con = _con(names)
    seen = checks.read_payee_history(data)
    new, baseline = checks.new_payee_names(set(names), seen, run_id)
    if passes:
        checks.record_payees(con, run_id, data)
    return new, baseline, con


def _hist(data):
    return checks.read_payee_history(data)


def test_first_build_records_every_name_and_reports_none_as_new(tmp_path):
    new, baseline, con = _build(tmp_path, "20261101T000000Z", ["ACME INC", "SOLO CO"])
    assert baseline and new == []
    h = _hist(tmp_path)
    assert list(h.columns) == checks.PAYEE_COLUMNS and list(h.payee_name) == ["ACME INC", "SOLO CO"]
    assert set(h.first_seen_run_id) == {"20261101T000000Z"} and set(h.first_seen_date) == {"2026-11-01"}
    assert con.execute("SELECT count(*) FROM ops.payee_name_seen").fetchone()[0] == 2


def test_identical_rerun_adds_no_rows_and_no_false_new_names(tmp_path):
    _build(tmp_path, "R1", ["ACME INC", "SOLO CO"])
    before = _hist(tmp_path)
    for _ in range(2):  # the same extract run built again, twice
        new, baseline, _c = _build(tmp_path, "R1", ["ACME INC", "SOLO CO"])
        assert baseline and new == []
    pd.testing.assert_frame_equal(before, _hist(tmp_path))
    _build(tmp_path, "R2", ["ACME INC", "SOLO CO", "NEW LLC"])
    for _ in range(2):  # a rerun of R2 reports the same one new name, not more, and does not duplicate it
        new, baseline, _c = _build(tmp_path, "R2", ["ACME INC", "SOLO CO", "NEW LLC"])
        assert not baseline and new == ["NEW LLC"]
    h = _hist(tmp_path)
    assert len(h) == h.payee_name.nunique() == 3


def test_later_build_reports_new_names_and_moves_last_seen(tmp_path):
    _build(tmp_path, "20261101T000000Z", ["ACME INC", "SOLO CO"])
    new, baseline, _c = _build(tmp_path, "20261201T000000Z", ["ACME INC", "NEW LLC"])
    assert not baseline and new == ["NEW LLC"]
    h = _hist(tmp_path).set_index("payee_name")
    assert h.loc["NEW LLC", "first_seen_run_id"] == "20261201T000000Z"
    assert h.loc["ACME INC", "first_seen_run_id"] == "20261101T000000Z" and h.loc["ACME INC", "last_seen_date"] == "2026-12-01"
    assert h.loc["SOLO CO", "last_seen_run_id"] == "20261101T000000Z"  # not paid this run: kept, last_seen unchanged


def test_failed_build_writes_nothing(tmp_path):
    _build(tmp_path, "R1", ["ACME INC"], passes=False)
    assert not (tmp_path / checks.PAYEE_HISTORY).exists()
    _build(tmp_path, "R1", ["ACME INC"])
    before = _hist(tmp_path)
    new, baseline, _c = _build(tmp_path, "R2", ["ACME INC", "BAD NAME"], passes=False)
    assert new == ["BAD NAME"] and not baseline  # reported by the failed build's check ...
    pd.testing.assert_frame_equal(before, _hist(tmp_path))  # ... but not recorded
    new, _b, _c = _build(tmp_path, "R3", ["ACME INC", "BAD NAME"])
    assert new == ["BAD NAME"]  # so the next passing build still reports it as new
