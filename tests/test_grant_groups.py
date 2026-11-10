"""Grant groups (src/models/grant_groups.py) with the TF-IDF backend on constructed grants, the input mart, and the grantor
alias map (reference/grantor_agency_aliases.csv). Every test here runs without sentence-transformers (CI installs no ml
extra): the backend is forced to TF-IDF; the coverage test against the real grants skips when data/ is absent."""
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from src.models import grant_groups as gg
from src.pipeline import marts

CFG = gg.assumptions()
ROOT = Path(__file__).resolve().parents[1]
ALIASES = ROOT / "reference" / "grantor_agency_aliases.csv"
DB = ROOT / "data" / "md_transparency.duckdb"
REASONS = r"^(current name|spelling|rename|fund of agency|program of agency|unit of agency|unknown)"


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


def _sql_con(aliases):
    c = duckdb.connect()
    for sc in ("core", "mart", "ref"):
        c.execute(f"CREATE SCHEMA {sc}")
    c.execute("""CREATE TABLE core.fact_grant AS SELECT * FROM (VALUES
        (2025, 'MARYLAND DEPARTMENT OF LABOR/EARN MD', 'X', 'Grant', 'Training  grants', 1.0),
        (2016, 'Department of Labor, Licensing and Regulation/EARN', 'Y', 'Grant', 'TRAINING grants', 2.0),
        (2018, 'MD Stem Cell Research Fund', 'W', 'Grant', 'Stem cell research', 4.0),
        (2018, 'Administration and Operations', 'V', 'Grant', 'Climate training', 5.0),
        (2025, 'DEPARTMENT OF HEALTH & MENTAL HYGIENE/Office', 'Z', 'Grant', '', 3.0)) t(fiscal_year, grantor, grantee, category, description, amount)""")
    c.register("_a", pd.DataFrame(aliases, columns=["grantor_raw", "grantor_agency", "agency_code", "reason", "evidence"]))
    c.execute("CREATE TABLE ref.grantor_agency_aliases AS SELECT * FROM _a")
    c.execute(marts.fill((marts.SQL / "61_v_grant_rows.sql").read_text()))
    return c


def test_grant_rows_sql_normalizes_and_resolves_agencies():
    c = _sql_con([
        ("MARYLAND DEPARTMENT OF LABOR/EARN MD", "Maryland Department of Labor", "P00", "current name", ""),
        ("Department of Labor, Licensing and Regulation/EARN", "Maryland Department of Labor", "P00", "rename: DLLR -> Labor (2019)", ""),
        ("MD Stem Cell Research Fund", "Maryland Technology Development Corporation", "T50", "fund of agency: TEDCO", ""),
        ("Administration and Operations", "ADMINISTRATION AND OPERATIONS", "", "unknown", ""),
    ])
    r = c.execute("SELECT grantor_listed, grantor_agency, alias_reason, grantor_program, description_key FROM mart.v_grant_rows ORDER BY amount").fetchall()
    assert r == [  # the blank description is dropped
        ("DEPARTMENT OF LABOR", "Maryland Department of Labor", "current name", "EARN MD", "training grants"),
        ("DEPARTMENT OF LABOR LICENSING AND REGULATION", "Maryland Department of Labor", "rename: DLLR -> Labor (2019)", "EARN", "training grants"),
        ("MD STEM CELL RESEARCH FUND", "Maryland Technology Development Corporation", "fund of agency: TEDCO", None, "stem cell research"),
        ("ADMINISTRATION AND OPERATIONS", "ADMINISTRATION AND OPERATIONS", "unknown", None, "climate training"),  # unknown keeps the listed name
    ]


def test_grant_rows_sql_without_alias_row_keeps_listed_name():
    c = _sql_con([])
    r = c.execute("SELECT DISTINCT grantor_agency, alias_reason FROM mart.v_grant_rows WHERE grantor_listed LIKE 'DEPARTMENT OF LABOR%' ORDER BY 1").fetchall()
    assert r == [("DEPARTMENT OF LABOR", "not in map"), ("DEPARTMENT OF LABOR LICENSING AND REGULATION", "not in map")]


def test_aliases_collapse_renamed_agency(monkeypatch, tmp_path):
    """A rename counted as two agencies before the map is one agency after it: the any-year group collapses."""
    _tfidf(monkeypatch)
    rows = _rows()
    rows["grantor_listed"] = rows.grantor_agency
    rows.loc[rows.grantor_agency == "DEPARTMENT OF LABOR", "grantor_agency"] = "DEPARTMENT OF COMMERCE"  # pretend: one agency renamed
    rows["alias_reason"] = "current name"
    g, _, s = gg.build(rows, dict(CFG, cosine_threshold=0.6, sensitivity=[]), tmp_path)
    cyber = g[g.description == "Cyber workforce training"].iloc[0]
    assert cyber.n_grantors_listed == 2 and cyber.multi_listed_any_year and not cyber.multi_agency_any_year and cyber.collapsed_by_aliases
    assert cyber.amount_all_years == 90.0
    main = s[s.main].iloc[0]
    assert main.collapsed_by_aliases == 1 and main.rows_alias_not_in_map == 0 and main.rows_alias_unknown == 0


def test_alias_map_is_well_formed():
    a = pd.read_csv(ALIASES, dtype=str, keep_default_na=False)
    assert list(a.columns) == ["grantor_raw", "grantor_agency", "agency_code", "reason", "evidence"]
    assert a.grantor_raw.str.strip().is_unique and (a.grantor_agency != "").all() and (a.evidence != "").all()
    assert a.reason.str.match(REASONS).all(), a.loc[~a.reason.str.match(REASONS), "reason"].unique()
    assert a[a.reason.str.startswith("rename")].reason.str.contains(r"\(\d{4}\)").all()  # every rename carries its year
    known = a[a.reason != "unknown"]
    assert (known.agency_code != "").all() and known.groupby("agency_code").grantor_agency.nunique().max() == 1
    unk = a[a.reason == "unknown"]
    assert (unk.agency_code == "").all() and len(unk) <= 0.01 * len(a)


@pytest.mark.skipif(not DB.exists(), reason="no database built (CI)")
def test_alias_map_covers_every_grantor_and_targets_pipeline_agencies():
    c = duckdb.connect(str(DB), read_only=True)
    raw = {g.strip() for (g,) in c.execute("SELECT DISTINCT grantor FROM raw.grants WHERE grantor IS NOT NULL").fetchall()}
    names = {n for (n,) in c.execute("SELECT agency FROM mart.agency_name UNION SELECT agency FROM mart.agency_master WHERE agency IS NOT NULL").fetchall()}
    a = pd.read_csv(ALIASES, dtype=str, keep_default_na=False)
    assert raw == set(a.grantor_raw.str.strip())
    assert set(a[a.reason != "unknown"].grantor_agency) <= names
    assert not re.search("not in map", " ".join(c.execute("SELECT DISTINCT alias_reason FROM mart.v_grant_rows").fetchnumpy()["alias_reason"]))
