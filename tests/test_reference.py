"""Phase 3 gate on the latest database: match rates at or above the dashboard pipeline's. Run after `make build`."""
from pathlib import Path

import pytest

DB = Path(__file__).resolve().parents[1] / "data" / "md_transparency.duckdb"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="no database built (CI)")


def test_reference_checks_pass():
    import duckdb
    con = duckdb.connect(str(DB), read_only=True)
    ref = con.execute("""SELECT "check", result FROM ops.check_result WHERE layer = 'ref' AND severity = 'stop'""").fetchall()
    assert len(ref) >= 6
    assert all(r == "pass" for _, r in ref), ref


def test_reference_tables_built():
    import duckdb
    con = duckdb.connect(str(DB), read_only=True)
    for t in ("ref.map_payment_agency", "ref.map_payee_vendor", "ref.map_focus_area", "core.fact_budget_scope", "core.fact_payment_mapped", "core.mfr_measure"):
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] > 0, t
