"""Payee classifier (src/models/payee_classifier.py) on constructed names, and the checked-in evaluation sample."""
import duckdb
import pandas as pd
import pytest

from src.models import payee_classifier as pc
from src.pipeline import marts

CFG, ORG = pc.assumptions()


def _names():
    biz = [f"{w} {s}" for w in ("ACME", "BETA", "GAMMA", "DELTA", "OMEGA", "SIGMA", "APEX", "ZENITH", "NOVA", "ORBIT")
           for s in ("INC", "LLC", "CORP", "CONSTRUCTION LLC", "TRUCKING INC")]
    gov = [f"{w} COUNTY {s}" for w in ("ALPHA", "BRAVO", "CHARLIE", "ECHO", "FOXTROT", "GOLF", "HOTEL", "INDIA", "KILO", "LIMA")
           for s in ("BOARD OF EDUCATION", "GOVERNMENT", "COMMISSIONERS", "PUBLIC SCHOOLS", "DEPT OF HEALTH")]
    npo = [f"{w} {s}" for w in ("HOPE", "UNITY", "GRACE", "MERCY", "HARBOR", "BRIDGE", "LIGHT", "RIVER", "OAK", "PINE")
           for s in ("FOUNDATION INC", "ASSOCIATION", "COMMUNITY CENTER INC", "BAPTIST CHURCH", "SOCIETY")]
    rows = [(n, "Business or other", "default") for n in biz] + [(n, "Government", "name rule") for n in gov] + \
           [(n, "Non-profit", "grants data nonprofit = Y") for n in npo]
    df = pd.DataFrame(rows, columns=["payee", "rule_type", "type_basis"])
    df["payee_key"] = [f"k{i:04d}" for i in range(len(df))]
    df["vendor"] = df.payee
    df["vendor_key"] = df.payee
    df["paid_all_years"] = [10.0 ** (3 + i % 6) for i in range(len(df))]
    df["paid_fy2025"] = 0.0
    return df


def test_spend_buckets():
    b = pc.spend_bucket(pd.Series([0, 99999, 100000, 5e6, 2e8]), CFG["spend_buckets"])
    assert list(b) == ["<$100K", "<$100K", "$100K-$1M", "$1M-$10M", "$100M+"]


def test_every_rule_type_has_a_class():
    assert set(pc.rule_class(pd.Series(list(CFG["rule_to_class"])), CFG)) <= set(pc.CLASSES)
    with pytest.raises(KeyError):
        pc.rule_class(pd.Series(["Unknown type"]), CFG)


def test_sample_is_stratified_and_reproducible():
    df = _names()
    cfg = dict(CFG, eval_size=30)
    a, b = pc.draw_sample(df, cfg), pc.draw_sample(df, cfg)
    assert list(a.payee_key) == list(b.payee_key) and len(a) == 30 and a.payee_key.is_unique
    assert set(a.rule_type) == set(df.rule_type)  # every rule label is in the sample


def test_classify_holds_out_the_sample_and_reports_all_metrics():
    df = _names()
    ev = df.iloc[::10].copy()
    gold = ev.rule_type.map({"Business or other": "business", "Government": "government", "Non-profit": "nonprofit"})
    lab = pd.DataFrame({"payee_key": ev.payee_key, "payee": ev.payee, "my_label": gold.values, "her_label": ""})
    lab.loc[lab.index[0], "my_label"] = "unsure"
    lab["gold"] = lab.her_label.where(lab.her_label != "", lab.my_label)
    out, m = pc.classify(df, lab, dict(CFG, max_features=5000), ORG)
    assert len(out) == len(df) and out.final_label.notna().all() and out.confidence.between(0, 1).all()
    v = {(r.method, r.metric): r.value for r in m[m["class"] == "all"].itertuples()}
    for meth in ("rules", "model", "combined"):
        assert {(meth, "accuracy"), (meth, "macro_f1"), (meth, "dollars_classified_share")} <= set(v)
    assert v[("sample", "excluded_unsure")] == 1
    assert v[("model", "training_names")] == len(df) - len(ev)  # evaluation names never trained on
    assert v[("rules", "accuracy")] == 1.0  # gold equals the rules here, so combined cannot beat them ...
    assert v[("decision", "combined_promoted")] == 0 and (out.final_label == out.rule_class).all()  # ... and the rules are kept


def test_names_that_may_be_a_person_are_withheld():
    df = pd.concat([_names(), pd.DataFrame([{"payee": "SMITH JOHN A", "rule_type": "Business or other", "type_basis": "default", "payee_key": "kp",
                                              "vendor": "SMITH JOHN A", "vendor_key": "SMITH JOHN A", "paid_all_years": 5e4, "paid_fy2025": 0.0}])], ignore_index=True)
    lab = pd.DataFrame({"payee_key": ["k0000"], "payee": ["ACME INC"], "my_label": ["business"], "her_label": [""], "gold": ["business"]})
    out, _ = pc.classify(df, lab, dict(CFG, max_features=5000), ORG)
    shown = dict(zip(out.payee_key, out.payee))
    assert shown["kp"] == pc.MASK and shown["k0000"] == "ACME INC"


def test_input_mart_sql():
    c = duckdb.connect()
    for s in ("core", "ref", "mart"):
        c.execute(f"CREATE SCHEMA {s}")
    c.execute("CREATE TABLE core.fact_payment AS SELECT * FROM (VALUES (2025, 'ACME INC', 10.0), (2024, 'ACME INC', 5.0)) t(fiscal_year, vendor_name_as_paid, amount)")
    c.execute("CREATE TABLE ref.map_payee_vendor AS SELECT * FROM (VALUES ('ACME INC', 'ACME', 'Acme'), ('NEW CO', 'NEW CO', 'New Co')) t(payee, vendor_key, vendor)")
    c.execute("CREATE TABLE mart.vendor_type AS SELECT * FROM (VALUES ('Acme', 'Business or other', 'default'), ('New Co', 'Business or other', 'default')) t(vendor, payee_type, type_basis)")
    c.execute(marts.fill((marts.SQL / "60_v_payee_class_input.sql").read_text()))
    r = {p: (a, f) for p, a, f in c.execute("SELECT payee, paid_all_years, paid_fy2025 FROM mart.v_payee_class_input").fetchall()}
    assert r == {"ACME INC": (15.0, 10.0), "NEW CO": (0.0, 0.0)}


def test_checked_in_sample():
    lab = pc.read_labels()
    assert len(lab) == CFG["eval_size"] and lab.payee_key.is_unique
    assert set(lab.gold) <= set(pc.CLASSES) | {"unsure"}
    assert "her_label" in lab.columns
    assert lab.loc[lab.gold == "individual/withheld", "payee"].str.startswith("[individual").all()  # a person's name is never written out
