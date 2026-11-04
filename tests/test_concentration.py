import duckdb


def test_hhi_and_top5_follow_the_definition():
    """HHI = sum of squared percentage shares; top-5 share; the same SQL as sql/mart/36_f_concentration.sql."""
    c = duckdb.connect()
    c.execute("CREATE SCHEMA mart")
    c.execute("CREATE TABLE mart.v_purchase AS SELECT * FROM (VALUES (2026, 'A', 'x', 60.0::DOUBLE), (2026, 'A', 'y', 30.0), (2026, 'A', 'z', 10.0), "
              "(2026, 'B', 'u', 50.0), (2026, 'B', 'v', 50.0)) t(fiscal_year, area, vendor, amount)")
    sql = open("sql/mart/36_f_concentration.sql").read()
    c.execute(sql)
    r = {a: (int(n), round(float(s), 6), round(float(t), 6), float(h)) for a, n, s, t, h in c.execute("SELECT area, vendors, spend, top5_share, hhi FROM mart.f_concentration").fetchall()}
    assert r["A"] == (3, 100.0, 1.0, 4600.0)  # 60² + 30² + 10²
    assert r["B"] == (2, 100.0, 1.0, 5000.0)
