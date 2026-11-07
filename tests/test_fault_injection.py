"""Fault injection: a damaged extract must fail its stop checks, and the last good database must survive.

Copies the latest raw run to a temporary folder, drops half of one year's budget rows (what a truncated download
looks like), and builds there. Needs a real extract in data/raw/ (skipped in CI); no network. Run: make test-fault
"""
import json
import shutil
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.pipeline import build, checks

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
RUNS = sorted(p for p in RAW.iterdir() if (p / "manifest.json").exists()) if RAW.exists() else []
pytestmark = pytest.mark.skipif(not RUNS, reason="no extract run in data/raw (CI)")


@pytest.fixture
def faulted(tmp_path, monkeypatch):
    run = RUNS[-1]
    dest = tmp_path / "raw" / run.name
    shutil.copytree(run, dest)
    b = pd.read_parquet(dest / "budget.parquet")
    year = int(pd.to_numeric(b["fiscal_year"]).max()) - 1
    rows = b.index[pd.to_numeric(b["fiscal_year"]) == year]
    b.drop(rows[: len(rows) // 2]).to_parquet(dest / "budget.parquet")  # the injected fault
    # the manifest still records the portal's own count, so the damage is visible to the checks
    assert json.loads((dest / "manifest.json").read_text())["datasets"]
    monkeypatch.setattr(build, "DATA", tmp_path)
    monkeypatch.setattr(build, "DB", tmp_path / "md_transparency.duckdb")
    monkeypatch.setattr(checks, "HIST", tmp_path / "check_history.csv")
    return run.name, year


def test_damaged_extract_fails_and_keeps_the_last_good_database(faulted, tmp_path):
    run_id, _ = faulted
    good = tmp_path / "md_transparency.duckdb"
    con = duckdb.connect(str(good))
    con.execute("CREATE TABLE sentinel AS SELECT 42 AS answer")
    con.close()

    assert build.build(run_id) is False

    keep = duckdb.connect(str(good), read_only=True)  # the last good database is untouched
    assert keep.execute("SELECT answer FROM sentinel").fetchone()[0] == 42
    keep.close()
    failed = tmp_path / "md_transparency.failed.duckdb"
    assert failed.exists() and not (tmp_path / "md_transparency.building").exists()
    f = duckdb.connect(str(failed), read_only=True)
    bad = f.execute("""SELECT "check" FROM ops.check_result WHERE result = 'fail'""").fetchall()
    f.close()
    names = " | ".join(r[0] for r in bad)
    assert "Rows loaded = portal count" in names or "Yearly totals = portal" in names, names
