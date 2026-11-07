"""Opportunity detectors: where the next $50M is likely to be (port of legacy/gst/scripts/opportunities.py and the bid
list in legacy/gst/scripts/recs.py).

Four detectors scan every controllable spending code at every agency (FY2025 actual budget) and the FY2026 payments to
private vendors. Each finding carries a baseline, a likely saving and a low-high range, and the evidence behind it.
Findings at the same agency and spending code are not added twice: the larger one is kept.

  peer gap     an agency spends more per budgeted position on a spending code than three in four agencies;
               saving = 5-15% of the spending above that 75th percentile, at most 3-10% of the agency's spending on the code
  growth       an agency's spending on a code grew 25+ points faster than the state's over FY2022-FY2025;
               saving = 10-30% of the growth above the state's pace
  tail spend   in each focus area, payments to vendors outside the ten largest; consolidation typically saves 3-10%
  leverage     one vendor paid by ten or more agencies; a single enterprise agreement typically saves 2-5%

The bid list is the same idea at vendor level: private vendors paid separately by ten or more agencies, minus service
providers and regulated utilities, which are not biddable contracts.

The saving rates are screening percentages, not forecasts, and the findings are not additive: the budget and payment
views count the same spending, and only the two budget detectors are de-duplicated against each other. Every threshold
and rate lives in config/assumptions.yaml.
Differences from the legacy script: an agency's name is its latest one (the legacy script took whichever row came
first), and the inputs are this pipeline's marts.
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
COLUMNS = ["detector", "agency_code", "agency", "area", "spending_code", "baseline", "low", "high", "evidence"]


def assumptions():
    return yaml.safe_load((ROOT / "config" / "assumptions.yaml").read_text())["opportunities"]


def _latest_names(agency_year):
    return agency_year.sort_values("fiscal_year", ascending=False).drop_duplicates("agency_code").set_index("agency_code").agency


def detect(code_agency, agency_year, payments, cfg=None):
    """code_agency: budget by fiscal_year, stage, agency_code, code, comptroller_subobject_name, controllable, area.
    agency_year: agency_code, agency, fiscal_year, fte. payments: fiscal_year, agency_code, vendor, area, amount,
    is_government, passthrough. Returns the findings, largest likely saving first, with ids O001, O002, ..."""
    cfg = cfg or assumptions()
    y, y0, py = cfg["current_fy"], cfg["base_fy"], cfg["payments_fy"]
    pg, gr, tl, lv = cfg["peer_gap"], cfg["growth"], cfg["tail_spend"], cfg["leverage"]
    c = code_agency[(code_agency.controllable.astype(str) == "True") & (code_agency.stage == "Actual")]
    names = _latest_names(agency_year)
    fte = agency_year[agency_year.fiscal_year == y].set_index("agency_code").fte
    key = ["agency_code", "code", "comptroller_subobject_name", "area"]
    cur = c[c.fiscal_year == y].groupby(key, dropna=False).budget.sum().reset_index()
    out = []
    # peer gap per position
    cur["fte"] = cur.agency_code.map(fte)
    pe = cur[(cur.fte >= pg["min_positions"]) & (cur.budget > 0)].copy()
    pe["per"] = pe.budget / pe.fte
    st = pe.groupby("code").per.agg(med="median", p75=lambda s: s.quantile(pg["percentile"]), n="count")
    pe = pe.join(st, on="code")
    hit = pe[(pe.n >= pg["min_agencies"]) & (pe.per > pe.p75) & (pe.budget >= pg["min_budget"])].copy()
    gap = (hit.per - hit.p75) * hit.fte  # only the spending above three in four agencies
    hit["low"] = np.minimum(pg["share_low"] * gap, pg["cap_low"] * hit.budget)
    hit["high"] = np.minimum(pg["share_high"] * gap, pg["cap_high"] * hit.budget)
    hit["detector"] = "Peer gap"
    hit["evidence"] = [f"${p:,.0f} per position vs ${q:,.0f} at the 75th percentile of {int(n)} agencies (median ${m:,.0f}); agencies differ in mission, "
                       f"so only {pg['share_low'] * 100:.0f}-{pg['share_high']:.0%} of the excess is counted" for p, q, m, n in zip(hit.per, hit.p75, hit.med, hit.n)]
    out.append(hit)
    # growth above the state's pace
    old = c[c.fiscal_year == y0].groupby(key, dropna=False).budget.sum().rename("old")
    g = cur.set_index(key).join(old).reset_index()
    state = g.groupby("code")[["budget", "old"]].sum()
    g = g.join((state.budget / state.old - 1).rename("sg"), on="code")
    g = g[(g.old > gr.get("min_base_budget", 0)) & (g.budget >= gr["min_budget"])].copy()
    g["ag"] = g.budget / g.old - 1
    hit = g[(g.ag > g.sg + gr["points_above_state"]) & np.isfinite(g.sg)].copy()
    excess = hit.budget - hit.old * (1 + hit.sg)
    hit["low"], hit["high"] = gr["share_low"] * excess, gr["share_high"] * excess
    hit["detector"] = "Growth above trend"
    hit["evidence"] = [f"grew {a:+.0%} over FY{y0}-FY{y} vs {s:+.0%} statewide" for a, s in zip(hit.ag, hit.sg)]
    out.append(hit)
    o = pd.concat(out, ignore_index=True)
    o["mid"] = (o.low + o.high) / 2
    o = o.sort_values("mid", ascending=False).drop_duplicates(["agency_code", "code"])  # keep the larger finding
    o = o.rename(columns={"budget": "baseline", "comptroller_subobject_name": "spending_code"})
    o["agency"] = o.agency_code.map(names)
    o["spending_code"] = o.spending_code + " (" + o.code.astype(str) + ")"
    rows = [o[COLUMNS]]
    # payments: tail spend and multi-agency leverage
    p = payments[(payments.fiscal_year == py) & ~payments.is_government.astype(bool) & ~payments.passthrough.astype(bool)].copy()
    a = p[p.area.notna()].groupby(["area", "vendor"]).amount.sum().reset_index()
    top = tl["top_vendors"]
    for area, grp in a.groupby("area"):
        grp = grp.sort_values("amount", ascending=False)
        tail = grp.amount.iloc[top:].sum()
        if tail > tl["min_tail"]:
            rows.append(pd.DataFrame([{"detector": "Tail spend", "agency_code": None, "agency": "Statewide", "area": area,
                                       "spending_code": f"{len(grp) - top:,} smaller vendors", "baseline": tail, "low": tl["rate_low"] * tail,
                                       "high": tl["rate_high"] * tail, "evidence": f"${tail / 1e6:,.1f}M paid to vendors outside the ten largest in FY{py}"}]))
    v = p.groupby("vendor").agg(spend=("amount", "sum"), agencies=("agency_code", "nunique"))
    v = v[(v.agencies >= lv["min_agencies"]) & (v.spend >= lv["min_spend"])]
    rows.append(pd.DataFrame({"detector": "Leverage", "agency_code": None, "agency": "Statewide", "area": None,
                              "spending_code": v.index.str.title(), "baseline": v.spend.values, "low": lv["rate_low"] * v.spend.values,
                              "high": lv["rate_high"] * v.spend.values, "evidence": [f"paid by {n} agencies separately in FY{py}" for n in v.agencies]}))
    d = pd.concat(rows, ignore_index=True)
    d["likely"] = (d.low + d.high) / 2
    d = d.sort_values("likely", ascending=False).reset_index(drop=True)
    d.insert(0, "opp_id", [f"O{i:03d}" for i in range(1, len(d) + 1)])
    for k in ("baseline", "low", "high", "likely"):
        d[k] = d[k].round(0)
    return d


def bid_list(payments, agency_year, cfg=None):
    """Private vendors paid separately by ten or more agencies in the payments year (recommendation 1)."""
    cfg = cfg or assumptions()
    bl, py = cfg["bid_list"], cfg["payments_fy"]
    names = agency_year.sort_values("fiscal_year").groupby("agency_code").agency.last()
    p = payments[~payments.is_government.astype(bool) & ~payments.passthrough.astype(bool) & ~payments.agency_code.isin(bl["excluded_agency_codes"])]
    q = p[p.fiscal_year.isin([py - 1, py])]
    g = q.groupby(["vendor", "fiscal_year"]).amount.sum().unstack(fill_value=0)
    a = q[q.fiscal_year == py].groupby("vendor").agency_code.nunique()
    top = (q[q.fiscal_year == py].groupby(["vendor", "agency_code"]).amount.sum().reset_index()
           .sort_values("amount", ascending=False).groupby("vendor").head(3))
    top["n"] = top.agency_code.map(names).fillna(top.agency_code)
    top = top.groupby("vendor").n.agg(", ".join)
    d = pd.DataFrame({"fy2025": g.get(py - 1), "fy2026": g.get(py), "agencies": a}).dropna(subset=["agencies"])
    biddable = ~d.index.str.upper().str.contains(bl["not_biddable"], flags=re.NOFLAG, regex=True)
    d = d[(d.agencies >= bl["min_agencies"]) & (d.fy2026 >= bl["min_spend"]) & biddable].sort_values("fy2026", ascending=False)
    d["low"], d["high"] = bl["rate_low"] * d.fy2026, bl["rate_high"] * d.fy2026
    d["top_agencies"] = top.reindex(d.index)
    d = d.reset_index().rename(columns={"index": "vendor"})
    d.insert(0, "rank", range(1, len(d) + 1))
    d["vendor"] = d.vendor.str.title()
    return d


def inputs(con):
    """The three inputs, read from the marts."""
    code_agency = con.execute("""SELECT b.fiscal_year, s.stage, b.agency_code, b.object_name, b.subobject_code AS code,
          b.subobject_name AS comptroller_subobject_name, b.controllable, b.focus_area AS area, sum(b.budget) AS budget
        FROM core.fact_budget_scope b JOIN ref.dim_stage s USING (fiscal_year) GROUP BY ALL""").df()
    agency_year = con.execute("SELECT agency_code, agency, fiscal_year, fte FROM mart.agency_year").df()
    payments = con.execute("SELECT fiscal_year, agency_code, vendor, area, amount, is_government, passthrough FROM mart.payment_area").df()
    return code_agency, agency_year, payments


def write(con, cfg=None):
    code_agency, agency_year, payments = inputs(con)
    opps, bids = detect(code_agency, agency_year, payments, cfg), bid_list(payments, agency_year, cfg)
    for name, df in (("d_opps", opps), ("d_bid_list", bids)):
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE mart.{name} AS SELECT * FROM _df")
        con.unregister("_df")
    return {"d_opps": len(opps), "d_bid_list": len(bids)}
