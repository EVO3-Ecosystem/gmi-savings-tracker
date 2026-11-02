import duckdb

from src.pipeline import marts


def test_yoy_matches_the_legacy_measure():
    c = duckdb.connect()
    c.execute("CREATE SCHEMA mart")
    base = "SELECT * FROM (VALUES (2024, 'Actual', 'A', 100.0), (2025, 'Actual', 'A', 110.0), (2026, 'Working budget', 'A', 0.0), (2027, 'Legislative appropriation', 'A', 50.0), (2025, 'Actual', 'B', 5.0)) t(fiscal_year, stage, k, v)"
    c.execute(marts.yoy_sql("t", base, "k", "v", True))
    r = {(y, k): (p, g, s) for y, k, p, g, s in c.execute("SELECT fiscal_year, k, v_prior, v_yoy, stage_pair FROM mart.t").fetchall()}
    assert r[(2025, "A")] == (100.0, 0.1, "Actual vs Actual")
    assert r[(2026, "A")][1] == -1.0 and r[(2026, "A")][2] == "Working budget vs Actual"
    assert r[(2027, "A")][1] is None  # prior year is zero
    assert r[(2025, "B")] == (None, None, None)  # no prior year for this key
    assert [d[0] for d in c.execute("DESCRIBE mart.t").fetchall()] == ["fiscal_year", "stage", "k", "v", "v_prior", "v_yoy", "stage_pair"]
