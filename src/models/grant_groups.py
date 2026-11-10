"""Grant groups: grants with the same purpose given by different grantor agencies (possible overlap leads).

Input: mart.v_grant_rows (the grants dataset, absk-avps, one row per published grant line; FY2009-FY2025).

1. Each distinct description (matched after lower case and spacing, about 5,000) is embedded with sentence-transformers
   all-MiniLM-L6-v2 on CPU (config grant_groups.model). If the package or the model cannot be loaded, TF-IDF word
   unigrams and bigrams are used instead; the backend used is recorded in every output row. Embeddings are cached in
   data/ml_cache/ by description, so a rebuild only embeds new descriptions.
2. Descriptions are clustered by agglomerative clustering (average linkage, cosine distance) with a threshold set before
   the results were looked at: descriptions whose average cosine similarity is at least grant_groups.cosine_threshold
   (0.85) join one group. The same clustering at the sensitivity thresholds (0.80, 0.90) is summarized alongside
   (mart.d_grant_groups_sensitivity); only the main threshold sets the leads.
3. Grantor agencies are resolved through reference/grantor_agency_aliases.csv (mart.v_grant_rows.grantor_agency): a
   renamed department counts as the current agency (Health and Mental Hygiene -> Maryland Department of Health) and a
   fund, program or unit name in the grantor field counts as the agency that runs it (MD Stem Cell Research Fund ->
   TEDCO). A group is a possible overlap lead when resolved agencies numbering at least grant_groups.min_agencies (2)
   funded it in grant_groups.lead_fy (FY2025, the last year in the grants data). multi_agency_any_year is the looser
   reading (2+ resolved agencies in any year, FY2009-FY2025), reported alongside. The grantor names as listed are kept
   (grantors_listed, multi_listed_any_year) so the groups the alias map collapses can be counted (collapsed_by_aliases).

A lead says only that two or more agencies fund grants described alike. It is not a duplicate, not waste and not a
saving: the grant dollars in a group are what was granted, are not additive with payments (grants are largely paid out
through the payments data, mart.f_overlap) and are not additive across groups or thresholds. The top groups were
checked by hand (docs/models/grant_groups.md), before and after the alias map.
"""
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "ml_cache"


def assumptions(path=None):
    return yaml.safe_load(Path(path or ROOT / "config" / "assumptions.yaml").read_text())["grant_groups"]


def inputs(con):
    return con.execute("SELECT * FROM mart.v_grant_rows").df()


def _key(s):
    return hashlib.md5(s.encode()).hexdigest()


def descriptions(rows):
    """One row per description key: the most common spelling as published, rows and dollars over all years."""
    spell = rows.groupby(["description_key", "description"]).size().rename("n").reset_index()
    spell = spell.sort_values(["description_key", "n", "description"], ascending=[True, False, True]).drop_duplicates("description_key")
    tot = rows.groupby("description_key").agg(rows=("amount", "size"), amount=("amount", "sum")).reset_index()
    return spell[["description_key", "description"]].merge(tot, on="description_key").sort_values("description_key").reset_index(drop=True)


def embed_minilm(texts, model_name, cache_dir=CACHE):
    from sentence_transformers import SentenceTransformer
    cache_dir = Path(cache_dir)
    cache = cache_dir / f"embeddings_{model_name.replace('/', '_')}.parquet"
    have = pd.read_parquet(cache) if cache.exists() else pd.DataFrame(columns=["k"])
    known = dict(zip(have.k, have.drop(columns="k").to_numpy(dtype=np.float32))) if len(have) else {}
    keys = [_key(t) for t in texts]
    todo = [t for t, k in zip(texts, keys) if k not in known]
    if todo:
        m = SentenceTransformer(model_name, device="cpu")
        vec = m.encode(todo, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
        known.update({_key(t): v.astype(np.float32) for t, v in zip(todo, vec)})
        cache_dir.mkdir(parents=True, exist_ok=True)
        out = pd.DataFrame(np.vstack(list(known.values())), columns=[f"e{i}" for i in range(len(vec[0]))])
        out.insert(0, "k", list(known.keys()))
        out.to_parquet(cache, index=False)
    return np.vstack([known[k] for k in keys])


def embed_tfidf(texts):
    from sklearn.feature_extraction.text import TfidfVectorizer
    x = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, sublinear_tf=True).fit_transform(texts)
    return x  # rows are L2-normalized by default


def embed(texts, cfg, cache_dir=CACHE):
    """(vectors, backend). Falls back to TF-IDF when sentence-transformers or the model cannot be loaded."""
    try:
        return embed_minilm(texts, cfg["model"], cache_dir), cfg["model"]
    except Exception as e:  # noqa: BLE001 - any failure (package missing, download blocked) falls back
        print(f"grant_groups: {cfg['model']} unavailable ({type(e).__name__}: {str(e)[:120]}); using TF-IDF word 1-2 grams")
        return embed_tfidf(texts), "tfidf-word-1-2gram"


def cluster(vectors, threshold):
    """Agglomerative clustering, average linkage on cosine distance; descriptions closer than 1 - threshold merge."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics.pairwise import cosine_similarity
    n = vectors.shape[0]
    if n < 2:
        return np.zeros(n, dtype=int)
    dist = np.clip(1 - cosine_similarity(vectors), 0, 2)
    np.fill_diagonal(dist, 0)
    return AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage="average", distance_threshold=1 - threshold).fit_predict(dist)


def groups(rows, desc, labels, cfg, backend, threshold):
    """One row per group with its FY dollars and agencies; group_id is stable (hash of the member description keys)."""
    d = desc.assign(cluster=labels)
    gid = d.groupby("cluster").description_key.agg(lambda s: "G" + _key("|".join(sorted(s)))[:10])
    d["group_id"] = d.cluster.map(gid)
    r = rows.merge(d[["description_key", "group_id"]], on="description_key")
    if "grantor_listed" not in r:  # rows without the alias step: the listed name is the agency
        r["grantor_listed"] = r.grantor_agency
    fy = cfg["lead_fy"]
    cur = r[r.fiscal_year == fy]
    rep = d.sort_values(["group_id", "amount", "description"], ascending=[True, False, True]).groupby("group_id")
    g = pd.DataFrame({
        "description": rep.description.first(),
        "n_descriptions": rep.size(),
        "example_descriptions": rep.description.agg(lambda s: " | ".join(list(s)[1:4]) or None),
    })
    g["grantor_agencies"] = r.groupby("group_id").grantor_agency.agg(lambda s: "; ".join(sorted(set(s))))
    g["n_agencies"] = r.groupby("group_id").grantor_agency.nunique()
    g["grantees"] = r.groupby("group_id").grantee.nunique()
    g["grantors_listed"] = r.groupby("group_id").grantor_listed.agg(lambda s: "; ".join(sorted(set(s))))
    g["n_grantors_listed"] = r.groupby("group_id").grantor_listed.nunique()
    g[f"grantor_agencies_fy{fy}"] = cur.groupby("group_id").grantor_agency.agg(lambda s: "; ".join(sorted(set(s))))
    g[f"n_agencies_fy{fy}"] = cur.groupby("group_id").grantor_agency.nunique()
    g[f"grantees_fy{fy}"] = cur.groupby("group_id").grantee.nunique()
    g[f"rows_fy{fy}"] = cur.groupby("group_id").size()
    g[f"amount_fy{fy}"] = cur.groupby("group_id").amount.sum()
    g["amount_all_years"] = r.groupby("group_id").amount.sum()
    g["first_fy"] = r.groupby("group_id").fiscal_year.min()
    g["last_fy"] = r.groupby("group_id").fiscal_year.max()
    for c in (f"n_agencies_fy{fy}", f"grantees_fy{fy}", f"rows_fy{fy}"):
        g[c] = g[c].fillna(0).astype(int)
    g[f"amount_fy{fy}"] = g[f"amount_fy{fy}"].fillna(0.0)
    g["overlap_lead"] = g[f"n_agencies_fy{fy}"] >= cfg["min_agencies"]
    g["multi_agency_any_year"] = g.n_agencies >= cfg["min_agencies"]  # secondary: resolved agencies in any year
    g["multi_listed_any_year"] = g.n_grantors_listed >= cfg["min_agencies"]  # the round-1 reading: grantor names as listed
    g["collapsed_by_aliases"] = g.multi_listed_any_year & ~g.multi_agency_any_year  # 2+ names, but one agency after the map
    g["backend"], g["cosine_threshold"] = backend, threshold
    g = g.reset_index().sort_values([f"amount_fy{fy}", "amount_all_years", "group_id"], ascending=[False, False, True])
    g.insert(1, "rank_fy", np.arange(1, len(g) + 1))
    return g.reset_index(drop=True), d[["description_key", "description", "group_id", "rows", "amount"]]


def alias_counts(rows):
    """Grant rows whose grantor is not in reference/grantor_agency_aliases.csv, and those mapped with reason 'unknown'."""
    reason = rows["alias_reason"] if "alias_reason" in rows else pd.Series("not in map", index=rows.index)
    return {"rows_alias_not_in_map": int((reason == "not in map").sum()), "rows_alias_unknown": int((reason == "unknown").sum())}


def build(rows, cfg, cache_dir=CACHE):
    desc = descriptions(rows)
    vec, backend = embed(desc.description.tolist(), cfg, cache_dir)
    out, members, sens = None, None, []
    fy = cfg["lead_fy"]
    total = rows.loc[rows.fiscal_year == fy, "amount"].sum()
    for t in sorted({cfg["cosine_threshold"], *cfg["sensitivity"]}):
        g, m = groups(rows, desc, cluster(vec, t), cfg, backend, t)
        lead = g[g.overlap_lead]
        sens.append({"cosine_threshold": t, "backend": backend, "main": t == cfg["cosine_threshold"], "descriptions": len(desc), "groups": len(g),
                     "multi_description_groups": int((g.n_descriptions > 1).sum()), "groups_with_fy_amount": int((g[f"amount_fy{fy}"] != 0).sum()),
                     "overlap_leads": len(lead), "lead_amount_fy": float(lead[f"amount_fy{fy}"].sum()),
                     "multi_agency_any_year": int(g.multi_agency_any_year.sum()),
                     "multi_agency_any_year_amount_fy": float(g.loc[g.multi_agency_any_year, f"amount_fy{fy}"].sum()),
                     "multi_listed_any_year": int(g.multi_listed_any_year.sum()), "collapsed_by_aliases": int(g.collapsed_by_aliases.sum()),
                     **alias_counts(rows),
                     "lead_share_of_fy_grants": float(lead[f"amount_fy{fy}"].sum() / total) if total else None, "fiscal_year": fy})
        if t == cfg["cosine_threshold"]:
            out, members = g, m
    return out, members, pd.DataFrame(sens)


def write(con, cfg=None):
    cfg = cfg or assumptions()
    g, m, s = build(inputs(con), cfg)
    for name, df in (("d_grant_groups", g), ("d_grant_group_members", m), ("d_grant_groups_sensitivity", s)):
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE mart.{name} AS SELECT * FROM _df")
        con.unregister("_df")
    return {"d_grant_groups": len(g), "d_grant_group_members": len(m), "d_grant_groups_sensitivity": len(s)}
