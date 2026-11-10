"""Payee type classifier: can a text model label the payees the name rules leave in "Business or other"?

Target: one of five classes per payee name as paid (about 61,800 names):
    business             for-profit companies, banks, utilities, practices (INC, LLC, CORP, PA, PC ...)
    government           public bodies: counties, cities, towns, boards of education, State and federal agencies, authorities
    nonprofit            foundations, associations, churches, charities and other non-profit organizations
    individual/withheld  a person's name, or a name withheld or redacted
    other                an organization whose type the name does not settle (hospitals, universities and colleges,
                         estates, trusts, joint ventures of mixed parties)

Baseline: the existing rules (reference/payee_type_rules.csv via mart.vendor_type), mapped to the five classes by
config/assumptions.yaml payee_classifier.rule_to_class. The rules have a default, "Business or other", that takes every
name no rule matched (type_basis = 'default').

Model: TF-IDF character n-grams (char_wb 2-5) + multinomial logistic regression (scikit-learn, fixed random_state,
class_weight='balanced'), trained on the rule labels of every payee except the evaluation sample (and every other name
of the same vendor, so a spelling variant of an evaluation name is never in training). It can only learn the classes
the rules produce: it never predicts individual/withheld.

Combined: the rule's label where a rule decided (a name rule or the grants data), the model's label where the rules
fell to the default.

Evaluation: reference/payee_labels_sample.csv, 400 names drawn by `draw_sample` (stratified by spend bucket and rule
label), labeled from the name text alone under the written criteria in docs/models/payee_classifier.md. A single
annotator's labels (my_label), to be re-reviewed by Sierra (her_label; when filled it replaces my_label). 'unsure'
labels are excluded and counted. The combined labels are promoted to final_label only if their macro F1 beats the
rules' on that sample; otherwise final_label is the rule label.

These labels are better data, never savings. Names that may be a person's are never published (masked, as the payment
screen does with payment_screen.org_name_pattern).
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "reference" / "payee_labels_sample.csv"
CLASSES = ["business", "government", "nonprofit", "individual/withheld", "other"]
MASK = "Payee not named (may be an individual)"
LABEL_COLUMNS = ["payee_key", "payee", "rule_type", "type_basis", "spend_bucket", "paid_all_years", "my_label", "her_label", "note"]


def assumptions(path=None):
    cfg = yaml.safe_load(Path(path or ROOT / "config" / "assumptions.yaml").read_text())
    return cfg["payee_classifier"], cfg["payment_screen"]["org_name_pattern"]


def inputs(con):
    return con.execute("SELECT * FROM mart.v_payee_class_input ORDER BY payee").df()


def spend_bucket(paid, edges):
    """Label of the all-years spend bucket: '<$100K', '$100K-$1M', ... from the lower edges."""
    def money(x):
        return f"${x / 1e6:g}M" if x >= 1e6 else f"${x / 1e3:g}K"
    names = [f"<{money(edges[1])}"] + [f"{money(lo)}-{money(hi)}" for lo, hi in zip(edges[1:-1], edges[2:])] + [f"{money(edges[-1])}+"]
    idx = np.searchsorted(np.asarray(edges[1:], dtype=float), np.asarray(paid, dtype=float), side="right")
    return pd.Series([names[i] for i in idx], index=getattr(paid, "index", None))


def rule_class(rule_type, cfg):
    m = cfg["rule_to_class"]
    out = pd.Series(rule_type).map(m)
    if out.isna().any():
        raise KeyError(f"payee types without a class in rule_to_class: {sorted(set(pd.Series(rule_type)[out.isna()]))}")
    return out


def draw_sample(df, cfg):
    """The evaluation sample: round-robin over the spend bucket x rule label cells (each cell shuffled with the fixed
    seed), one name per cell per pass, until eval_size names; small cells are exhausted first, so every cell is present."""
    rng = np.random.default_rng(cfg["random_state"])
    d = df.assign(spend_bucket=spend_bucket(df.paid_all_years.clip(lower=0), cfg["spend_buckets"]).values)
    cells = {k: list(g.sample(frac=1, random_state=int(rng.integers(1 << 31))).index) for k, g in d.groupby(["spend_bucket", "rule_type"], sort=True)}
    take = []
    while len(take) < cfg["eval_size"] and any(cells.values()):
        for k in sorted(cells):
            if cells[k] and len(take) < cfg["eval_size"]:
                take.append(cells[k].pop(0))
    return d.loc[take]


def read_labels(path=LABELS):
    lab = pd.read_csv(path, dtype=str, keep_default_na=False)
    lab["gold"] = lab.her_label.where(lab.her_label.str.strip() != "", lab.my_label).str.strip()
    bad = set(lab.gold) - set(CLASSES) - {"unsure"}
    if bad:
        raise ValueError(f"{path.name}: labels outside the five classes and 'unsure': {sorted(bad)}")
    return lab


def model(cfg):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    return make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=tuple(cfg["ngram_range"]), min_df=2, max_features=cfg["max_features"], sublinear_tf=True, lowercase=False),
        LogisticRegression(C=cfg["C"], max_iter=3000, class_weight="balanced", random_state=cfg["random_state"]))


def text(names):
    return pd.Series(names).astype(str).str.upper().str.replace(r"\s+", " ", regex=True).str.strip()


def metrics(gold, pred, labels):
    from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support
    p, r, f, s = precision_recall_fscore_support(gold, pred, labels=labels, zero_division=0)
    per = {c: {"precision": p[i], "recall": r[i], "f1": f[i], "support": int(s[i])} for i, c in enumerate(labels)}
    return {"accuracy": accuracy_score(gold, pred), "macro_f1": f1_score(gold, pred, labels=labels, average="macro", zero_division=0), "per_class": per}


def classify(df, labels, cfg, org_pattern):
    """Train, evaluate and label every payee. Returns (d_payee_class, d_payee_class_eval)."""
    df = df.reset_index(drop=True).copy()
    df["rule_class"] = rule_class(df.rule_type, cfg).values
    df["decided"] = df.type_basis != "default"
    ev_keys = set(labels.payee_key)
    held_vendors = set(df.loc[df.payee_key.isin(ev_keys), "vendor"])
    train = df[~df.vendor.isin(held_vendors)]
    clf = model(cfg).fit(text(train.payee), train.rule_class)
    prob = clf.predict_proba(text(df.payee))
    cls = clf.classes_
    df["model_label"] = cls[prob.argmax(1)]
    df["confidence"] = prob.max(1)
    df["combined_label"] = df.rule_class.where(df.decided, df.model_label)

    # ---- evaluation on the hand-labeled sample
    ev = labels.merge(df[["payee_key", "rule_class", "model_label", "combined_label", "confidence"]], on="payee_key", how="left")
    missing = int(ev.rule_class.isna().sum())
    unsure = int((ev.gold == "unsure").sum())
    ev = ev[(ev.gold != "unsure") & ev.rule_class.notna()]
    present = [c for c in CLASSES if c in set(ev.gold)]
    res = {m: metrics(ev.gold, ev[col], present) for m, col in (("rules", "rule_class"), ("model", "model_label"), ("combined", "combined_label"))}
    promoted = res["combined"]["macro_f1"] > res["rules"]["macro_f1"]

    # ---- labels for every payee
    df["final_label"] = df.combined_label if promoted else df.rule_class
    sure = df.confidence >= cfg["review_threshold"]
    suggest = (~df.decided) & (df.model_label != df.rule_class) & sure
    low = (~df.decided) & ~sure
    disagree = df.decided & (df.model_label != df.rule_class)
    df["review_flag"] = suggest | low | disagree
    df["review_reason"] = np.select([suggest, low, disagree], ["default label; model suggests another type", "default label; model confidence below threshold",
                                                              "model disagrees with the rule"], default=None)
    df["review_reason"] = df.review_reason.replace({"None": None})
    df["in_eval_sample"] = df.payee_key.isin(ev_keys)

    # ---- dollars: share of positive payments (all years) whose label rests on evidence, not the default
    pos = df.paid_all_years.clip(lower=0)
    conf = df.confidence >= cfg["review_threshold"]
    share = {"rules": pos[df.decided].sum() / pos.sum(), "model": pos[conf].sum() / pos.sum(),
             "combined": pos[df.decided | conf].sum() / pos.sum()}
    moved = {"rules": 0.0, "model": pos[df.model_label != df.rule_class].sum() / pos.sum(),
             "combined": pos[df.combined_label != df.rule_class].sum() / pos.sum()}
    dflt = ev.merge(df[["payee_key", "decided"]], on="payee_key")
    dflt = dflt[~dflt.decided]

    rows = []
    for m, r in res.items():
        rows += [{"method": m, "metric": "accuracy", "class": "all", "value": r["accuracy"], "n": len(ev)},
                 {"method": m, "metric": "macro_f1", "class": "all", "value": r["macro_f1"], "n": len(ev)},
                 {"method": m, "metric": "dollars_classified_share", "class": "all", "value": share[m], "n": len(df)},
                 {"method": m, "metric": "dollars_relabeled_share", "class": "all", "value": moved[m], "n": len(df)},
                 {"method": m, "metric": "accuracy_on_default_names", "class": "all", "n": len(dflt),
                  "value": float((dflt.gold == dflt[{"rules": "rule_class", "model": "model_label", "combined": "combined_label"}[m]]).mean()) if len(dflt) else None}]
        for c, v in r["per_class"].items():
            rows += [{"method": m, "metric": k, "class": c, "value": float(v[k]), "n": v["support"]} for k in ("precision", "recall", "f1")]
    rows += [{"method": "sample", "metric": "labeled", "class": "all", "value": float(len(labels)), "n": len(labels)},
             {"method": "sample", "metric": "excluded_unsure", "class": "all", "value": float(unsure), "n": len(labels)},
             {"method": "sample", "metric": "not_found", "class": "all", "value": float(missing), "n": len(labels)},
             {"method": "sample", "metric": "reviewed_by_sierra", "class": "all", "value": float((labels.her_label.str.strip() != "").sum()), "n": len(labels)},
             {"method": "decision", "metric": "combined_promoted", "class": "all", "value": float(promoted), "n": len(ev)},
             {"method": "model", "metric": "training_names", "class": "all", "value": float(len(train)), "n": len(df)},
             {"method": "model", "metric": "review_queue", "class": "all", "value": float(df.review_flag.sum()), "n": len(df)}]
    ev_df = pd.DataFrame(rows, columns=["method", "metric", "class", "value", "n"])

    rx = re.compile(org_pattern)
    org = df.payee.str.upper().map(lambda x: bool(rx.search(x)))
    named = org | df.final_label.isin(["government", "nonprofit", "other"])
    withheld = df.payee_key.isin(set(labels.loc[labels.gold == "individual/withheld", "payee_key"]))
    df["payee_shown"] = df.payee.where(named & ~withheld, MASK)
    out = df[["payee_key", "payee_shown", "rule_type", "type_basis", "rule_class", "model_label", "confidence", "final_label",
              "review_flag", "review_reason", "in_eval_sample", "paid_all_years"]].rename(columns={"payee_shown": "payee", "rule_type": "rule_label"})
    return out, ev_df


def write_sample(con, cfg=None, path=LABELS, labeler=None):
    """Draw the evaluation sample and write the labeling file (my_label from `labeler(payee) -> (label, note)` when given).
    Names labeled individual/withheld are written as a placeholder; look them up by payee_key in mart.v_payee_class_input."""
    cfg = cfg or assumptions()[0]
    s = draw_sample(inputs(con), cfg)
    lab = [labeler(p) if labeler else ("", "") for p in s.payee]
    s = s.assign(my_label=[a for a, _ in lab], note=[b for _, b in lab], her_label="")
    s["payee"] = s.payee.where(s.my_label != "individual/withheld", "[individual: name withheld, see payee_key]")
    s[LABEL_COLUMNS].to_csv(path, index=False)
    return s


def write(con, cfg=None):
    cfg, org = (cfg, assumptions()[1]) if cfg else assumptions()
    if not LABELS.exists():
        raise FileNotFoundError(f"{LABELS} is missing: draw it with payee_classifier.write_sample and label it")
    out, ev = classify(inputs(con), read_labels(), cfg, org)
    for name, df in (("d_payee_class", out), ("d_payee_class_eval", ev)):
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE mart.{name} AS SELECT * FROM _df")
        con.unregister("_df")
    return {"d_payee_class": len(out), "d_payee_class_eval": len(ev)}

