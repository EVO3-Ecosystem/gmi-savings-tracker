"""The publish gate refuses to export unaudited data. Runs without data/ (uses tiny temporary databases)."""
import os

import duckdb
import pandas as pd

from src.pipeline import gate


def _db(tmp_path, results=("pass", "pass")):
    path = tmp_path / "md_transparency.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA ops")
    con.execute("CREATE TABLE ops.check_result (\"check\" TEXT, result TEXT)")
    for i, r in enumerate(results):
        con.execute("INSERT INTO ops.check_result VALUES (?, ?)", [f"c{i}", r])
    return con, path


def _parity(tmp_path, statuses=("reproduced", "difference explained")):
    p = tmp_path / "summary.csv"
    pd.DataFrame({"file": [f"f{i}" for i in range(len(statuses))], "status": list(statuses)}).to_csv(p, index=False)
    return p


def test_clean_database_and_parity_pass(tmp_path):
    con, db = _db(tmp_path)
    assert gate.problems(con, db, _parity(tmp_path)) == []


def test_warnings_do_not_block(tmp_path):
    con, db = _db(tmp_path, ("pass", "warn"))
    assert gate.problems(con, db, _parity(tmp_path)) == []


def test_failed_stop_check_blocks(tmp_path):
    con, db = _db(tmp_path, ("pass", "fail"))
    out = gate.problems(con, db, _parity(tmp_path))
    assert len(out) == 1 and "1 stop check" in out[0]


def test_missing_check_table_blocks(tmp_path):
    db = tmp_path / "md_transparency.duckdb"
    con = duckdb.connect(str(db))
    out = gate.problems(con, db, _parity(tmp_path))
    assert len(out) == 1 and "ops.check_result" in out[0]


def test_unexplained_parity_difference_blocks(tmp_path):
    con, db = _db(tmp_path)
    out = gate.problems(con, db, _parity(tmp_path, ("reproduced", "difference to explain")))
    assert len(out) == 1 and "f1" in out[0]


def test_missing_parity_summary_blocks(tmp_path):
    con, db = _db(tmp_path)
    out = gate.problems(con, db, tmp_path / "nope.csv")
    assert len(out) == 1 and "make parity" in out[0]


def test_newer_failed_build_makes_the_database_stale(tmp_path):
    con, db = _db(tmp_path)
    failed = tmp_path / "md_transparency.failed.duckdb"
    failed.write_text("x")
    os.utime(failed, (db.stat().st_mtime + 60, db.stat().st_mtime + 60))
    out = gate.problems(con, db, _parity(tmp_path))
    assert len(out) == 1 and "newer build failed" in out[0]


def test_older_failed_build_is_ignored(tmp_path):
    con, db = _db(tmp_path)
    failed = tmp_path / "md_transparency.failed.duckdb"
    failed.write_text("x")
    os.utime(failed, (db.stat().st_mtime - 60, db.stat().st_mtime - 60))
    assert gate.problems(con, db, _parity(tmp_path)) == []
