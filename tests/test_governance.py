import json

import pandas as pd

from src.pipeline import governance as G


def _res(cols, name="Payments"):
    return [{"resource": {"id": "7syw-q4cy", "name": name, "columns_field_name": list(cols), "columns_datatype": list(cols.values())}}]


def test_drift_finds_added_removed_retyped_and_renamed():
    old = _res({"amount": "Number", "date": "Calendar date", "agency_name": "Text"})
    new = _res({"amount": "Text", "agency_name": "Text", "agency_code": "Text"}, name="Payments v2")
    got = {(c, ch.split(" ")[0]) for _, c, ch in G.drift(old, new)}
    assert got == {("agency_code", "column"), ("date", "column"), ("amount", "type"), ("title", "'Payments'")}


def test_no_drift_when_unchanged():
    r = _res({"amount": "Number"})
    assert G.drift(r, r) == []


def test_define_prefers_table_specific_then_general():
    d = pd.DataFrame([("count", "raw.fte", "portal", "positions"), ("count", "", "derived", "general"), ("x", "core.fact_payment*", "derived", "wild")],
                     columns=["column", "applies_to", "origin", "definition"])
    assert G.define(d, "raw.fte", "count") == ("positions", "portal")
    assert G.define(d, "d_savings", "count") == ("general", "derived")
    assert G.define(d, "core.fact_payment_mapped", "x") == ("wild", "derived")
    assert G.define(d, "core.other", "x") == ("", "")


def test_catalog_falls_back_to_snapshot(tmp_path, monkeypatch):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"results": _res({"amount": "Number"})}))
    monkeypatch.setattr(G, "SNAP", snap)
    res, how = G.catalog({"domain": "invalid.invalid", "datasets": {"payments": {"id": "7syw-q4cy"}}})
    assert how.startswith("saved snapshot") and res[0]["resource"]["id"] == "7syw-q4cy"


def test_dictionary_has_no_duplicate_keys():
    d = pd.read_csv(G.DICT, dtype=str).fillna("")
    assert not d.duplicated(["column", "applies_to"]).any()
    assert d.origin.isin(["portal", "source", "reference", "derived", "ops"]).all()
