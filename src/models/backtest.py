"""Detector backtest, first stage: do opportunity flags recur, and what did flagged spending do next year? (roadmap gap 16)

Each detector in src/models/opportunities.py is rerun as of an earlier year T (FY2022, FY2023, FY2024) on data up to T only,
with the live thresholds and the same look-back (growth compares T with T-3; the payment detectors use year-T payments). It
is then rerun as of T+1, and the year-T units are followed into T+1. Everything below was fixed before measuring:

  Units      Peer gap and Growth: an agency and spending code (controllable, actual budget). Tail spend: a focus area.
             Leverage: a private vendor.
  Cohorts    Flagged: the detector's own flags at T (before the two budget detectors are de-duplicated against each other).
             Not flagged: units that passed the detector's size and comparability filters at T but were not flagged, so the
             comparison is between like-sized units:
               Peer gap  agency with 50+ positions, 8+ comparable agencies on the code, $250k+ on the code
               Growth    $1M+ prior-year base (T-3) and $500k+ at T, with a finite statewide growth rate on the code
               Tail spend  every focus area with private payments at T
               Leverage  private vendors paid $5M+ at T
  Window     T to T+1, one year. T+1 is always an actual year (FY2023-FY2025 budget, FY2023-FY2025 payments).
  Measures   units; flagged at T+1 (the same detector, rerun as of T+1); spending at T and T+1 summed over the cohort's units
             (controllable budget for the budget detectors, private payments for the payment detectors: the area's vendors
             outside the ten largest at T for Tail spend, the vendor's payments for Leverage); the pooled change; the median
             per-unit change (units with spending at T); units with no spending at T+1.

Descriptive only: flagged and unflagged units differ in more than the flag, budgets are re-coded between years, and a fall
next year is not evidence that a saving was made or could be. Cohorts of different detectors overlap (the same spending is
seen from the budget and the payments side), so no row may be added to another.
"""
import numpy as np
import pandas as pd

from . import opportunities

AS_OF = (2022, 2023, 2024)
DETECTORS = ("Peer gap", "Growth above trend", "Tail spend", "Leverage")
COLUMNS = ["detector", "as_of_fy", "next_fy", "cohort", "units", "flagged_next", "flagged_next_share", "spend_as_of", "spend_next",
           "pooled_change", "median_change", "units_zero_next"]


def _cfg(cfg, t):
    c = {k: (dict(v) if isinstance(v, dict) else v) for k, v in cfg.items()}
    c["current_fy"], c["base_fy"], c["payments_fy"] = t, t - (cfg["current_fy"] - cfg["base_fy"]), t
    return c


def screen(code_agency, agency_year, payments, cfg):
    """Every detector's eligible units at cfg['current_fy'] / cfg['payments_fy'] with a `flag` column, using exactly the rules of
    opportunities.detect (tests/test_backtest.py checks that the flags equal detect()'s findings). Returns {detector: frame}."""
    y, y0, py = cfg["current_fy"], cfg["base_fy"], cfg["payments_fy"]
    pg, gr, tl, lv = cfg["peer_gap"], cfg["growth"], cfg["tail_spend"], cfg["leverage"]
    c = code_agency[(code_agency.controllable.astype(str) == "True") & (code_agency.stage == "Actual")]
    fte = agency_year[agency_year.fiscal_year == y].set_index("agency_code").fte
    key = ["agency_code", "code", "comptroller_subobject_name", "area"]
    cur = c[c.fiscal_year == y].groupby(key, dropna=False).budget.sum().reset_index()
    cur["fte"] = cur.agency_code.map(fte)
    pe = cur[(cur.fte >= pg["min_positions"]) & (cur.budget > 0)].copy()
    pe["per"] = pe.budget / pe.fte
    st = pe.groupby("code").per.agg(p75=lambda s: s.quantile(pg["percentile"]), n="count")
    pe = pe.join(st, on="code")
    pe = pe[(pe.n >= pg["min_agencies"]) & (pe.budget >= pg["min_budget"])].copy()
    pe["flag"] = pe.per > pe.p75
    old = c[c.fiscal_year == y0].groupby(key, dropna=False).budget.sum().rename("old")
    g = cur.set_index(key).join(old).reset_index()
    state = g.groupby("code")[["budget", "old"]].sum()
    g = g.join((state.budget / state.old - 1).rename("sg"), on="code")
    g = g[(g.old > gr.get("min_base_budget", 0)) & (g.budget >= gr["min_budget"]) & np.isfinite(g.sg)].copy()
    g["flag"] = (g.budget / g.old - 1) > g.sg + gr["points_above_state"]
    unit = lambda d: d.groupby(["agency_code", "code"]).agg(flag=("flag", "any"), spend=("budget", "sum")).reset_index()  # noqa: E731
    p = payments[(payments.fiscal_year == py) & ~payments.is_government.astype(bool) & ~payments.passthrough.astype(bool)]
    a = p[p.area.notna()].groupby(["area", "vendor"]).amount.sum().reset_index().sort_values(["area", "amount"], ascending=[True, False], kind="stable")
    a["rank"] = a.groupby("area").cumcount()
    tail = a[a["rank"] >= tl["top_vendors"]].groupby("area").agg(spend=("amount", "sum"), vendors=("vendor", list))
    tail = tail.reindex(pd.Index(a.area.unique(), name="area"), fill_value=0).reset_index()
    tail["vendors"] = [v if isinstance(v, list) else [] for v in tail.vendors]
    tail["flag"] = tail.spend > tl["min_tail"]
    v = p.groupby("vendor").agg(spend=("amount", "sum"), agencies=("agency_code", "nunique")).reset_index()
    v = v[v.spend >= lv["min_spend"]].copy()
    v["flag"] = v.agencies >= lv["min_agencies"]
    return {"Peer gap": unit(pe), "Growth above trend": unit(g), "Tail spend": tail, "Leverage": v}


def _next_spend(det, units, code_agency, payments, t1):
    if det in ("Peer gap", "Growth above trend"):
        c = code_agency[(code_agency.controllable.astype(str) == "True") & (code_agency.stage == "Actual") & (code_agency.fiscal_year == t1)]
        s = c.groupby(["agency_code", "code"]).budget.sum()
        return units.set_index(["agency_code", "code"]).index.map(lambda k: s.get(k, 0.0)).to_numpy(dtype=float)
    p = payments[(payments.fiscal_year == t1) & ~payments.is_government.astype(bool) & ~payments.passthrough.astype(bool)]
    if det == "Leverage":
        s = p.groupby("vendor").amount.sum()
        return units.vendor.map(s).fillna(0.0).to_numpy(dtype=float)
    s = p[p.area.notna()].groupby(["area", "vendor"]).amount.sum()
    return np.array([sum(s.get((ar, vn), 0.0) for vn in vs) for ar, vs in zip(units.area, units.vendors)], dtype=float)


def _key(det):
    return {"Tail spend": ["area"], "Leverage": ["vendor"]}.get(det, ["agency_code", "code"])


def run(code_agency, agency_year, payments, cfg=None, as_of=AS_OF):
    """One row per detector, as-of year and cohort (Flagged / Not flagged), in COLUMNS order."""
    cfg = cfg or opportunities.assumptions()
    rows = []
    for t in as_of:
        upto = lambda d, yr: d[d.fiscal_year <= yr]  # noqa: E731  only data up to the as-of year
        now = screen(upto(code_agency, t), upto(agency_year, t), upto(payments, t), _cfg(cfg, t))
        nxt = screen(upto(code_agency, t + 1), upto(agency_year, t + 1), upto(payments, t + 1), _cfg(cfg, t + 1))
        for det in DETECTORS:
            u, k = now[det].copy(), _key(det)
            later = set(map(tuple, nxt[det].loc[nxt[det].flag, k].to_numpy()))
            u["flag_next"] = [tuple(r) in later for r in u[k].to_numpy()]
            u["spend_next"] = _next_spend(det, u, code_agency, payments, t + 1)
            for cohort, part in (("Flagged", u[u.flag]), ("Not flagged", u[~u.flag])):
                s0, s1 = float(part.spend.sum()), float(part.spend_next.sum())
                pos = part[part.spend > 0]
                rows.append({"detector": det, "as_of_fy": t, "next_fy": t + 1, "cohort": cohort, "units": len(part),
                             "flagged_next": int(part.flag_next.sum()), "flagged_next_share": part.flag_next.mean() if len(part) else None,
                             "spend_as_of": s0, "spend_next": s1, "pooled_change": s1 / s0 - 1 if s0 else None,
                             "median_change": float((pos.spend_next / pos.spend - 1).median()) if len(pos) else None,
                             "units_zero_next": int((part.spend_next <= 0).sum())})
    return pd.DataFrame(rows, columns=COLUMNS)


def write(con, cfg=None):
    code_agency, agency_year, payments = opportunities.inputs(con)
    df = run(code_agency, agency_year, payments, cfg)
    con.register("_df", df)
    con.execute("CREATE OR REPLACE TABLE mart.d_detector_backtest AS SELECT * FROM _df")
    con.unregister("_df")
    return len(df)
