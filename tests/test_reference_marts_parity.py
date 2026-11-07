"""The stored measures and stage-evidence tables, and the evidence against the database's own totals. Needs data/ (skipped in CI)."""
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline import marts

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "md_transparency.duckdb"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="no database built (CI)")


def _con():
    import duckdb
    return duckdb.connect(str(DB), read_only=True)


def test_stored_tables_equal_their_sources_and_the_documented_columns():
    con = _con()
    doc = pd.read_csv(ROOT / "docs" / "schemas" / "dashboard_columns.csv")
    for name, want in (("measures", marts.catalog()), ("stage_evidence", marts.stage_evidence())):
        got = con.execute(f"SELECT * FROM mart.{name}").df()
        assert list(got.columns) == list(doc[doc.table == name].column)
        pd.testing.assert_frame_equal(got, want, check_dtype=False)


def test_the_whole_file_totals_in_the_evidence_tie_to_the_database_to_the_dollar():
    con = _con()
    rows = con.execute("""SELECT e.fiscal_year, e.file_total, b.t FROM mart.stage_evidence e
        JOIN (SELECT fiscal_year, sum(budget) t FROM core.fact_budget GROUP BY 1) b USING (fiscal_year) WHERE e.programs_compared IS NULL""").fetchall()
    assert {r[0] for r in rows} == {2022, 2027}
    for fy, file_total, db_total in rows:
        assert abs(file_total - db_total) <= 1, fy
