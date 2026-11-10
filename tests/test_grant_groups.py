"""Grant groups (src/models/grant_groups.py) with the TF-IDF backend on constructed grants, and the input mart."""
import duckdb
import numpy as np
import pandas as pd

from src.models import grant_groups as gg
from src.pipeline import marts

CFG = gg.assumptions()


def _rows():
    r = [  # fiscal_year, grantor_agency, grantee, description, amount
        (2025, "DEPARTMENT OF HEALTH", "A", "School based health centers", 100.0),
        (2025, "DEPARTMENT OF EDUCATION", "B", "School based health centers program", 50.0),
        (2024, "DEPARTMENT OF EDUCATION", "B", "School based health centers", 30.0),
        (2025, "DEPARTMENT OF COMMERCE", "C", "Cyber workforce training", 70.0),
        (2023, "DEPARTMENT OF LABOR", "D", "Cyber workforce training", 20.0),
        (2025, "DEPARTMENT OF AGING", "E", "Senior nutrition meals", 10.0),
    ]
    df = pd.DataFrame(r, columns=["fiscal_year", "grantor_agency", "grantee", "description", "amount"])
    df["description_key"] = df.description.str.lower()
    return df


def _tfidf(monkeypatch):
    def fail(*a, **k):
        raise ImportError("blocked in test")
    monkeypatch.setattr(gg, "embed_minilm", fail)


def test_groups_leads_and_sensitivity(monkeypatch, tmp_path):
    _tfidf(monkeypatch)
    cfg = dict(CFG, cosine_threshold=0.6, sensitivity=[0.5, 0.95])
    g, m, s = gg.build(_rows(), cfg, tmp_path)
    assert (g.backend == "tfidf-word-1-2gram").all()
    assert len(m) == 4 and m.group_id.notna().all()  # 4 distinct descriptions, each in one group
    shc = g[g.description.str.startswith("School based")].iloc[0]
    assert shc.n_descriptions == 2 and shc.n_agencies_fy2025 == 2 and shc.overlap_lead and shc.amount_fy2025 == 150.0
    cyber = g[g.description == "Cyber workforce training"].iloc[0]
    assert not cyber.overlap_lead and cyber.multi_agency_any_year  # two agencies, but not in the same year
    assert abs(g.amount_fy2025.sum() - 230.0) < 1e-9  # every FY2025 dollar in exactly one group
    assert list(s.cosine_threshold) == [0.5, 0.6, 0.95] and s.main.sum() == 1
    assert g.group_id.is_unique and g.rank_fy.tolist() == list(range(1, len(g) + 1))


def test_group_ids_are_stable(monkeypatch, tmp_path):
    _tfidf(monkeypatch)
    a, _, _ = gg.build(_rows(), CFG, tmp_path)
    b, _, _ = gg.build(_rows().sample(frac=1, random_state=1), CFG, tmp_path)
    assert sorted(a.group_id) == sorted(b.group_id)


def test_cluster_threshold():
    v = np.array([[1.0, 0.0], [0.99, 0.141], [0.0, 1.0]])
    v = v / np.linalg.norm(v, axis=1, keepdims=True)
    lab = gg.cluster(v, 0.85)
    assert lab[0] == lab[1] != lab[2]


def test_grant_rows_sql_normalizes_agencies():
    c = duckdb.connect()
    for s in ("core", "mart"):
        c.execute(f"CREATE SCHEMA {s}")
    c.execute("""CREATE TABLE core.fact_grant AS SELECT * FROM (VALUES
        (2025, 'MARYLAND DEPARTMENT OF LABOR/EARN MD', 'X', 'Grant', 'Training  grants', 1.0),
        (2025, 'DEPARTMENT OF LABOR', 'Y', 'Grant', 'TRAINING grants', 2.0),
        (2025, 'DEPARTMENT OF HEALTH & MENTAL HYGIENE/Office', 'Z', 'Grant', '', 3.0)) t(fiscal_year, grantor, grantee, category, description, amount)""")
    c.execute(marts.fill((marts.SQL / "61_v_grant_rows.sql").read_text()))
    r = c.execute("SELECT grantor_agency, grantor_program, description_key FROM mart.v_grant_rows ORDER BY amount").fetchall()
    assert r == [("DEPARTMENT OF LABOR", "EARN MD", "training grants"), ("DEPARTMENT OF LABOR", None, "training grants")]  # blank description dropped
