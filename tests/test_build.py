"""Phase 2 gate on the latest database: every stop check passed. Run after `make build`."""
from pathlib import Path

import pytest

DB = Path(__file__).resolve().parents[1] / "data" / "md_transparency.duckdb"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="no database built (CI)")


def test_no_failed_checks_and_totals_tie():
    import duckdb
    con = duckdb.connect(str(DB), read_only=True)
    assert con.execute("SELECT count(*) FROM ops.check_result WHERE result = 'fail'").fetchone()[0] == 0
    assert con.execute("""SELECT count(*) FROM ops.check_result WHERE "check" LIKE 'Yearly totals = portal:%' AND result = 'pass'""").fetchone()[0] == 5
