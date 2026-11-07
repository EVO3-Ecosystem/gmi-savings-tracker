"""Publish gate (write-audit-publish): export only what has been audited.

A dashboard export is allowed only when all of these hold:
  1. the database recorded its check results and none of them failed (ops.check_result);
  2. no later build failed its stop checks, which would leave this database stale
     (data/md_transparency.failed.duckdb newer than data/md_transparency.duckdb);
  3. the legacy parity summary exists and has no unexplained difference (docs/parity/summary.csv).

`problems()` returns one sentence per violated rule; an empty list means publishing is allowed.
"""
from pathlib import Path

import pandas as pd

PARITY_OK = {"reproduced", "difference explained"}


def _failed_checks(con):
    try:
        n = con.execute("SELECT count(*) FROM ops.check_result WHERE result = 'fail'").fetchone()[0]
    except Exception as e:  # noqa: BLE001 - a missing table is itself a gate failure
        return [f"the database has no ops.check_result table ({type(e).__name__}); rebuild it with `make build`"]
    return [f"{n} stop check(s) failed in the database's last build"] if n else []


def _stale(db, failed):
    db, failed = Path(db), Path(failed)
    if failed.exists() and db.exists() and failed.stat().st_mtime > db.stat().st_mtime:
        return [f"a newer build failed its stop checks ({failed.name}); this database is the last good one but out of date. "
                "Fix the failure and rebuild before exporting"]
    return []


def _parity(summary):
    summary = Path(summary)
    if not summary.exists():
        return [f"no parity summary at {summary}; run `make parity` first"]
    s = pd.read_csv(summary)
    if "status" not in s.columns or s.empty:
        return [f"parity summary {summary.name} has no status column or no rows"]
    bad = s[~s.status.isin(PARITY_OK)]
    if len(bad):
        return [f"{len(bad)} dashboard file(s) have an unexplained parity difference: {', '.join(map(str, bad.file.head(5)))}"]
    return []


def problems(con, db, parity_summary):
    failed = Path(db).with_name("md_transparency.failed.duckdb")
    return _failed_checks(con) + _stale(db, failed) + _parity(parity_summary)
