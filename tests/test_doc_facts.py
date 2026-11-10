"""src/models/doc_facts.py: generated sections replace only text between markers; the review sheet keeps decisions."""
import duckdb
import pandas as pd
import pytest

from src.models import doc_facts


def test_put_replaces_between_markers_only():
    t = "head\n<!-- facts:x -->\nold 246\n<!-- /facts:x -->\ntail"
    assert doc_facts.put(t, "x", "new 316") == "head\n<!-- facts:x -->\nnew 316\n<!-- /facts:x -->\ntail"
    with pytest.raises(SystemExit):
        doc_facts.put("no markers", "x", "y")


def test_review_sheet_keeps_decisions(tmp_path):
    con = duckdb.connect()
    con.execute("CREATE SCHEMA mart")
    con.execute("""CREATE TABLE mart.d_payment_screen AS SELECT * FROM (VALUES
        ('g1', 'Possible duplicate', 2025, 'A', 'A RAW', 'Acme', 2, 10.0, 10.0, 'high', 'needs_records', 'note'),
        ('g2', 'Possible duplicate', 2025, 'B', 'B RAW', 'Beta', 2, 5.0, 5.0, 'low', 'likely_legitimate', 'note'))
        t(group_id, rule, fiscal_year, agency, agency_raw, vendor, n, amount, review_amount, confidence, review_status, review_note)""")
    path = tmp_path / "sheet.csv"
    assert doc_facts.review_sheet(con, path) == 2
    d = pd.read_csv(path, dtype=str).fillna("")
    d.loc[d.group_id == "g1", ["her_decision", "notes"]] = ["records_requested", "asked agency"]
    d.to_csv(path, index=False)
    doc_facts.review_sheet(con, path)
    d = pd.read_csv(path, dtype=str).fillna("")
    assert list(d.columns) == doc_facts.SHEET_COLS
    assert d.set_index("group_id").loc["g1", "her_decision"] == "records_requested" and d.set_index("group_id").loc["g2", "her_decision"] == ""
