"""Pipeline facts (Data & pipeline tab): column contract and values, on a small synthetic database (no data/ needed)."""
import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.pipeline import facts

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTED = pd.read_csv(ROOT / "docs" / "schemas" / "dashboard_columns.csv")


def documented(table):
    return list(DOCUMENTED[DOCUMENTED.table == table].column)


@pytest.fixture
def world(tmp_path):
    con = duckdb.connect(":memory:")
    for s in ("raw", "core", "ref", "ops", "mart"):
        con.execute(f"CREATE SCHEMA {s}")
    yr = {"budget": "fiscal_year", "fund": "fiscal_year", "fte": "fiscal_year", "payments": "fiscal_year", "grants": "fiscalyear"}
    for k, col in yr.items():
        con.execute(f"CREATE TABLE raw.{k} AS SELECT * FROM (VALUES ('2017'), ('2026'), ('2027')) t({col})")
    ids = {"budget": "yu65-jmmv", "fund": "gy87-e27x", "fte": "x8qy-486w", "payments": "7syw-q4cy", "grants": "absk-avps"}
    man = {"datasets": [{"dataset": k, "id": i, "rows": 3, "portal_count": 3, "match": True, "rowsUpdatedAt_utc": "2026-08-10T18:07:57+00:00"}
                        for k, i in ids.items()]}
    con.execute("CREATE TABLE core.fact_payment AS SELECT * FROM (VALUES (2026, 100.0, false), (2027, 50.0, true)) t(fiscal_year, amount, partial_year)")
    con.execute("CREATE TABLE core.fact_payment_mapped AS SELECT * FROM (VALUES (2026, 99.5, 'D50'), (2026, 0.5, NULL), (2027, 50.0, 'D50')) t(fiscal_year, amount, agency_code)")
    con.execute("CREATE TABLE ref.map_payment_agency AS SELECT * FROM (VALUES ('A', 'D50'), ('B', 'D51'), ('C', NULL)) t(payment_agency_name, agency_code)")
    con.execute("CREATE TABLE ref.map_payee_vendor AS SELECT * FROM (VALUES ('ACME INC', 'ACME'), ('ACME LLC', 'ACME'), ('SOLO CO', 'SOLO')) t(payee, vendor)")
    con.execute("CREATE TABLE ops.check_result AS SELECT * FROM (VALUES ('R2', 'raw', 'Rows loaded', 'stop', 'pass', '3 of 3'),"
                " ('R2', 'ref', 'New payee names since the last build', 'warn', 'warn', '2 new: A; B')) t(run_id, layer, \"check\", severity, result, detail)")
    data = tmp_path
    pd.DataFrame({"run_id": ["R1", "R2"], "status": ["passed", "passed"], "forced": [True, False], "seconds": [400.0, 5.0], "rows": [15, 15],
                  "downloaded": [5, 0], "reused": [0, 5], "heals": [1, 0], "mismatches": [0, 0], "enrichment_warnings": [0, 0]}).to_csv(data / "runs.csv", index=False)
    pd.DataFrame({"run_id": ["R2", "R2"], "layer": ["raw", "ref"], "check": ["a", "b"], "severity": ["stop", "warn"], "result": ["pass", "warn"],
                  "detail": ["", ""]}).to_csv(data / "check_history.csv", index=False)
    (data / "raw" / "R1").mkdir(parents=True)
    (data / "raw" / "R1" / "manifest.json").write_text(json.dumps({"datasets": [{"dataset": "payments", "rows": 7}, {"dataset": "budget", "rows": 9}]}))
    return con, man, data


def test_every_table_matches_the_documented_dashboard_columns(world):
    con, man, data = world
    facts.build(con, "R2", man, data, data / "check_history.csv")
    for t in ("sources", "run_checks", "pipeline_runs", "d_master_quality"):
        assert list(con.execute(f"SELECT * FROM mart.{t}").df().columns) == documented(t), t


def test_sources_rows_and_years(world):
    con, man, data = world
    facts.build(con, "R2", man, data, data / "check_history.csv")
    s = con.execute("SELECT * FROM mart.sources").df().set_index("source")
    assert list(s.index) == ["payments", "budget", "fund", "fte", "grants"]
    assert s.loc["budget", "years"] == "FY2017-FY2027" and s.loc["budget", "portal_updated"] == "2026-08-10"
    assert s.loc["fte", "dataset_id"] == "x8qy-486w" and (s.reconciled == 1).all()


def test_pipeline_runs_history_modes_and_publish_flag(world):
    con, man, data = world
    facts.build(con, "R2", man, data, data / "check_history.csv")
    r = con.execute("SELECT * FROM mart.pipeline_runs ORDER BY run_id").df().set_index("run_id")
    assert r.loc["R1", "mode"] == "fresh download" and r.loc["R2", "mode"] == "freshness reuse"
    assert r.loc["R1", "published"] == 0 and pd.isna(r.loc["R1", "checks"])  # extracted but never built
    assert r.loc["R2", "published"] == 1 and r.loc["R2", "checks"] == 2 and r.loc["R2", "warnings"] == 1
    assert r.loc["R1", "payment_rows"] == 7 and r.loc["R1", "repairs"] == 1


def test_master_quality_values(world):
    con, man, data = world
    facts.build(con, "R2", man, data, data / "check_history.csv")
    q = con.execute("SELECT * FROM mart.d_master_quality").df().set_index("measure")
    assert q.loc["FY2026 payments matched to a budget agency", "value"] == "99.50%"
    assert q.loc["Payment agency names mapped", "value"] == "2 of 3"
    assert q.loc["Payee names grouped into companies", "value"] == "2 names in 1 companies"
    assert q.loc["New payee names since the last run", "value"] == "2"
    assert q.loc["Agency names not yet mapped", "value"] == "C"


def test_run_checks_carry_the_run_id_and_stage(world):
    con, man, data = world
    facts.build(con, "R2", man, data, data / "check_history.csv")
    c = con.execute("SELECT * FROM mart.run_checks").df()
    assert set(c.run_id) == {"R2"} and list(c.stage) == ["raw", "ref"] and list(c.status) == ["pass", "warn"]


def test_runs_without_history_files_still_build(world, tmp_path):
    con, man, _ = world
    empty = tmp_path / "empty"
    empty.mkdir()
    out = facts.build(con, "R2", man, empty, empty / "check_history.csv")
    assert out["pipeline_runs"] == 0 and out["sources"] == 5
