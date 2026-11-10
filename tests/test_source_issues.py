"""Source issues, confidence and the evidence review (sql/mart/47-50) on constructed records."""
import duckdb
import pytest

from src.pipeline import marts

SQL = sorted(marts.SQL.glob("4[789]_*payment_screen*.sql")) + [marts.SQL / "50_d_source_issues.sql"]


@pytest.fixture()
def con():
    c = duckdb.connect()
    for s in ("core", "ref", "mart"):
        c.execute(f"CREATE SCHEMA {s}")
    rows = [  # fy, agency code, unit name, unit code, payee, zip, amount, date
        (2024, "D50", "UNIT A", "A1", "ACME INC", "1", 4897.0, "2024-01-01"), (2024, "D50", "UNIT A", "A1", "ACME INC", "2", 4897.0, "2024-01-01"),  # one unit, two ZIPs
        (2024, "J00", "UNIT X", "X1", "EVENTS LLC", "1", 5000.0, "2024-01-01"), (2024, "J00", "UNIT Y", "Y1", "EVENTS LLC", "1", 5000.0, "2024-01-01"),
        (2024, "E00", "UNIT Z", "Z1", "EVENTS LLC", "1", 5000.0, "2024-01-01"),                                                              # 3 units, same amount
        (2024, "K00", "UNIT K", "K1", "SAME CORP", "1", 2000.0, "2024-01-01"), (2024, "K00", "UNIT K", "K1", "SAME CORP", "1", 2000.0, "2024-01-01"),  # identical lines
        (2024, "U10", "MES", "U10", "BETA LLC", "1", 9000.0, "2024-01-01"), (2024, "U10", "MES", "U10", "BETA LLC", "1", 9000.0, "2025-01-01"),  # second block
        (2024, "U10", "MES", "U10", "GAMMA LLC", "1", 1500.0, "2025-01-01"),
        (2025, "D50", "UNIT A", "A1", "ACME INC", "1", 100.0, "2025-01-01"),
    ]
    c.execute("CREATE TABLE core.fact_payment_mapped (fiscal_year INT, agency_code VARCHAR, agency_name_as_paid VARCHAR, agency_code_as_paid VARCHAR, "
              "vendor_name_as_paid VARCHAR, vendor_zip VARCHAR, amount DOUBLE, record_date DATE, partial_year BOOLEAN)")
    for fy, a, u, uc, p, z, amt, d in rows:
        c.execute("INSERT INTO core.fact_payment_mapped VALUES (?,?,?,?,?,?,?,?,?)", [fy, a, u, uc, p, z, amt, d, fy == 2025])
    c.execute("CREATE TABLE core.fact_payment AS SELECT * FROM core.fact_payment_mapped")
    names = [("ACME INC", "Acme"), ("EVENTS LLC", "Events"), ("SAME CORP", "Same"), ("BETA LLC", "Beta"), ("GAMMA LLC", "Gamma")]
    c.execute("CREATE TABLE ref.map_payee_vendor (payee VARCHAR, vendor_key VARCHAR, vendor VARCHAR, is_government BOOLEAN, payee_area VARCHAR)")
    c.execute("CREATE TABLE mart.vendor_type (vendor VARCHAR, payee_type VARCHAR)")
    for p, v in names:
        c.execute("INSERT INTO ref.map_payee_vendor VALUES (?, ?, ?, false, NULL)", [p, p, v])
        c.execute("INSERT INTO mart.vendor_type VALUES (?, 'Business or other')", [v])
    c.execute("CREATE TABLE ref.payee_area_exclusions (area VARCHAR, agency_name_pattern VARCHAR, payee_pattern VARCHAR)")
    c.execute("CREATE TABLE mart.agency_master AS SELECT * FROM (VALUES ('D50', 'Agency Fifty'), ('U10', 'Maryland Environmental Service')) t(agency_code, agency)")
    cfg = marts.yaml.safe_load(marts.CFG.read_text())
    cfg["payment_screen"].update(first_fy=2024, last_fy=2025)
    cfg["source_issues"].update(verified_ids=["SRC-2024-U10"])
    for f in SQL:
        c.execute(marts.fill(f.read_text(), cfg))
    return c


def test_source_issue_leaves_the_leads(con):
    leads = con.execute("SELECT vendor FROM mart.d_payment_screen ORDER BY 1").fetchall()
    assert ("Beta",) not in leads and len(leads) == 3
    i = con.execute("SELECT issue_id, agency, agency_raw, records, amount, identical_records, screen_groups, screen_review_amount, verified_on IS NOT NULL "
                    "FROM mart.d_source_issues").fetchall()
    assert i == [("SRC-2024-U10", "Maryland Environmental Service", "MES", 2, 10500.0, 1, 1, 9000.0, True)]
    both = con.execute("SELECT count(*) FROM mart.v_payment_screen_rows r JOIN mart.d_payment_screen USING (group_id) WHERE r.source_issue_id IS NOT NULL").fetchone()[0]
    assert both == 0


def test_cleaned_agency_name(con):
    a = con.execute("SELECT agency, agency_raw FROM mart.d_payment_screen WHERE vendor = 'Acme'").fetchone()
    assert a == ("Agency Fifty", "UNIT A")


def test_confidence_and_review(con):
    got = dict((v, (c, s)) for v, c, s in con.execute("SELECT vendor, confidence, review_status FROM mart.d_payment_screen").fetchall())
    assert got["Acme"] == ("high", "needs_records")          # not round, one unit, two ZIPs (score +1 +1 -1 = 1)
    assert got["Events"] == ("low", "likely_legitimate")     # round, two units, 3 units paid the same amount
    assert got["Same"][1] == "confirmed_duplicate_in_source"  # identical in every published field
    notes = con.execute("SELECT count(*) FROM mart.d_payment_screen WHERE review_note IS NULL OR review_note = ''").fetchone()[0]
    assert notes == 0


def test_measured_rate_and_lever(con):
    r = con.execute("SELECT DISTINCT measured_confirmation_rate, reviewed_leads, confirmed_leads, lever_rate_low, lever_rate_likely, lever_rate_high "
                    "FROM mart.d_payment_screen_summary").fetchall()
    assert len(r) == 1
    p, n, k, lo, mid, hi = r[0]
    assert (n, k) == (3, 1) and p == pytest.approx(1 / 3) and mid == pytest.approx(1 / 3) and lo < mid < hi


def test_unmeasured_rate_is_null_and_lever_zero(con):
    con.execute("DELETE FROM mart.d_payment_screen WHERE review_status = 'confirmed_duplicate_in_source'")
    cfg = marts.yaml.safe_load(marts.CFG.read_text())
    cfg["payment_screen"].update(first_fy=2024, last_fy=2025)
    con.execute(marts.fill((marts.SQL / "49_d_payment_screen_summary.sql").read_text(), cfg))
    r = con.execute("SELECT DISTINCT measured_confirmation_rate, rate_basis, lever_rate_low, lever_rate_likely, lever_rate_high FROM mart.d_payment_screen_summary").fetchall()
    assert r == [(None, "not measurable without payment records", 0, 0, 0)]
