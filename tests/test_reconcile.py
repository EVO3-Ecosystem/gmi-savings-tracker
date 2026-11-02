import duckdb

from src.pipeline import reconcile as R


def _con():
    c = duckdb.connect()
    c.execute("create schema raw; create table raw.payments as select * from (values ('2025', 10.0), ('2025', 5.0), ('2026', 7.0)) t(fiscal_year, amount)")
    return c


def test_compare_matches_and_cleans_formatted_numbers(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text('fiscal_year,amount\n2025,"$10.00"\n2025,"5"\n2026,"7"\n')
    j = R.compare(_con(), "payments", {"year_col": "fiscal_year", "sum_col": "amount"}, f)
    assert j.match.all() and j.rows_web.sum() == 3


def test_compare_flags_missing_rows_and_totals(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("fiscal_year,amount\n2025,10\n2026,9\n")
    j = R.compare(_con(), "payments", {"year_col": "fiscal_year", "sum_col": "amount"}, f).set_index("fiscal_year")
    assert not j.loc[2025, "match"] and j.loc[2025, "total_difference"] == -5
    assert not j.loc[2026, "match"] and j.loc[2026, "total_difference"] == 2
