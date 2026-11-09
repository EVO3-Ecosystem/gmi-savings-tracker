"""Payment screen (sql/mart/47-49) on constructed records: each rule, the exclusions, precedence and the summary."""
import duckdb
import pytest

from src.pipeline import marts

SQL = sorted(marts.SQL.glob("4[789]_*payment_screen*.sql"))


def test_fill_literals():
    cfg = {"a": {"n": 7, "s": "it's", "l": ["X", "Y"]}}
    assert marts.fill("{{a.n}} {{ a.s }} ({{a.l}})", cfg) == "7 'it''s' ('X', 'Y')"
    with pytest.raises(KeyError):
        marts.fill("{{a.missing}}", cfg)


@pytest.fixture()
def con():
    c = duckdb.connect()
    for s in ("core", "ref", "mart"):
        c.execute(f"CREATE SCHEMA {s}")
    rows = [  # fy, agency, payee, zip, amount, date
        (2025, "D50", "ACME INC", "1", 5000.0, "2025-01-01"), (2025, "D50", "ACME INC", "2", 5000.0, "2025-01-01"),   # duplicate
        (2025, "D50", "BETA LLC", "1", 9000.0, "2025-01-01"), (2025, "D50", "BETA LLC", "1", 9000.0, "2026-01-01"),   # repeated line
        (2025, "D50", "COUNTY OF X", "1", 7000.0, "2025-01-01"), (2025, "D50", "COUNTY OF X", "1", 7000.0, "2025-01-01"),  # government: out
        (2025, "D50", "ACME INC", "1", 500.0, "2025-01-01"), (2025, "D50", "ACME INC", "3", 500.0, "2025-01-01"),     # under $1,000: out
        (2026, "D50", "ACME INC", "1", 5000.0, "2026-01-01"), (2026, "D50", "ACME INC", "1", 5000.0, "2026-01-01"),   # partial year: out
    ]
    c.execute("CREATE TABLE core.fact_payment_mapped (fiscal_year INT, agency_code VARCHAR, agency_name_as_paid VARCHAR, agency_code_as_paid VARCHAR, "
              "vendor_name_as_paid VARCHAR, vendor_zip VARCHAR, amount DOUBLE, record_date DATE, partial_year BOOLEAN)")
    for fy, a, p, z, amt, d in rows:
        c.execute("INSERT INTO core.fact_payment_mapped VALUES (?,?,?,?,?,?,?,?,?)", [fy, a, "AGENCY " + a, a, p, z, amt, d, fy == 2026])
    c.execute("CREATE TABLE core.fact_payment AS SELECT * FROM core.fact_payment_mapped")
    c.execute("""CREATE TABLE ref.map_payee_vendor AS SELECT * FROM (VALUES ('ACME INC', 'ACME', 'Acme', false, NULL),
                 ('BETA LLC', 'BETA', 'Beta', false, NULL), ('COUNTY OF X', 'COUNTY OF X', 'County of X', true, NULL))
                 t(payee, vendor_key, vendor, is_government, payee_area)""")
    c.execute("""CREATE TABLE mart.vendor_type AS SELECT * FROM (VALUES ('Acme', 'Business or other'), ('Beta', 'Business or other'),
                 ('County of X', 'Government')) t(vendor, payee_type)""")
    c.execute("CREATE TABLE ref.payee_area_exclusions (area VARCHAR, agency_name_pattern VARCHAR, payee_pattern VARCHAR)")
    cfg = marts.yaml.safe_load(marts.CFG.read_text())
    cfg["payment_screen"].update(first_fy=2025, last_fy=2026)
    for f in SQL:
        c.execute(marts.fill(f.read_text(), cfg))
    return c


def test_rules(con):
    got = con.execute("SELECT rule, fiscal_year, vendor, n, amount, review_amount, zips FROM mart.d_payment_screen ORDER BY rule").fetchall()
    assert got == [("Possible duplicate", 2025, "Acme", 2, 5000.0, 5000.0, 2), ("Repeated annual line", 2025, "Beta", 2, 9000.0, 9000.0, 1)]


def test_summary_and_split_status(con):
    s = con.execute("SELECT rule, fiscal_year, groups, review_amount, status FROM mart.d_payment_screen_summary ORDER BY fiscal_year, rule_order").fetchall()
    assert len(s) == 6
    assert s[0] == ("Possible duplicate", 2025, 1, 5000.0, "Measured")
    assert s[2][0] == "Possible split purchase" and s[2][4].startswith("Not measurable")
    assert all(r[2] == 0 for r in s if r[1] == 2026)
