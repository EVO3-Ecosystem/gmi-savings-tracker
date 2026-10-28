"""Opportunity detectors: where the next $50M is likely to be.

Four detectors scan every controllable spending code at every agency (FY2025 actual budget) and the FY2026
payments to vendors. Each finding carries a baseline, a likely saving and a low-high range, and the
evidence behind it. Findings at the same agency and spending code are not added twice: the larger one is kept.

  peer gap     an agency spends more per budgeted position on a spending code than three in four agencies;
               saving = 5-15% of the spending above that 75th percentile, at most 3-10% of the agency's spending on the code
  growth       an agency's spending on a code grew 25+ points faster than the state's over FY2022-FY2025;
               saving = 10-30% of the growth above the state's pace
  tail spend   in each focus area, payments to vendors outside the ten largest; consolidation typically saves 3-10%
  leverage     one vendor paid by ten or more agencies; a single enterprise agreement typically saves 2-5%
"""
import numpy as np
import pandas as pd

Y, Y0, PY = 2025, 2022, 2026


def build(code_agency, f_agency, pm):
    c = code_agency[(code_agency.controllable.astype(str) == "True") & (code_agency.stage == "Actual")]
    names = f_agency.drop_duplicates("agency_code").set_index("agency_code").agency
    fte = f_agency[f_agency.fiscal_year == Y].set_index("agency_code").fte
    key = ["agency_code", "code", "comptroller_subobject_name", "area"]
    cur = c[c.fiscal_year == Y].groupby(key, dropna=False).budget.sum().reset_index()
    out = []
    # peer gap per position
    cur["fte"] = cur.agency_code.map(fte)
    pe = cur[(cur.fte >= 50) & (cur.budget > 0)].copy()
    pe["per"] = pe.budget / pe.fte
    st = pe.groupby("code").per.agg(med="median", p75=lambda s: s.quantile(.75), n="count")
    pe = pe.join(st, on="code")
    hit = pe[(pe.n >= 8) & (pe.per > pe.p75) & (pe.budget >= 250e3)].copy()
    gap = (hit.per - hit.p75) * hit.fte  # only the spending above three in four agencies
    hit["low"], hit["high"] = np.minimum(.05 * gap, .03 * hit.budget), np.minimum(.15 * gap, .10 * hit.budget)
    hit["detector"] = "Peer gap"
    hit["evidence"] = [f"${p:,.0f} per position vs ${q:,.0f} at the 75th percentile of {int(n)} agencies (median ${m:,.0f}); agencies differ in mission, so only 5-15% of the excess is counted" for p, q, m, n in zip(hit.per, hit.p75, hit.med, hit.n)]
    out.append(hit)
    # growth above the state's pace
    old = c[c.fiscal_year == Y0].groupby(key, dropna=False).budget.sum().rename("old")
    g = cur.set_index(key).join(old).reset_index()
    state = g.groupby("code")[["budget", "old"]].sum()
    g = g.join((state.budget / state.old - 1).rename("sg"), on="code")
    g = g[(g.old > 0) & (g.budget >= 500e3)].copy()
    g["ag"] = g.budget / g.old - 1
    hit = g[(g.ag > g.sg + .25) & np.isfinite(g.sg)].copy()
    excess = hit.budget - hit.old * (1 + hit.sg)
    hit["low"], hit["high"] = .10 * excess, .30 * excess
    hit["detector"] = "Growth above trend"
    hit["evidence"] = [f"grew {a:+.0%} over FY{Y0}-FY{Y} vs {s:+.0%} statewide" for a, s in zip(hit.ag, hit.sg)]
    out.append(hit)
    o = pd.concat(out, ignore_index=True)
    o["mid"] = (o.low + o.high) / 2
    o = o.sort_values("mid", ascending=False).drop_duplicates(["agency_code", "code"])  # keep the larger finding
    o = o.rename(columns={"budget": "baseline", "comptroller_subobject_name": "spending_code"})
    o["agency"] = o.agency_code.map(names)
    o["spending_code"] = o.spending_code + " (" + o.code.astype(str) + ")"
    rows = [o[["detector", "agency_code", "agency", "area", "spending_code", "baseline", "low", "high", "evidence"]]]
    # payments: tail spend and multi-agency leverage, FY2026
    p = pm[(pm.fiscal_year == PY) & ~pm.is_government.astype(bool) & ~pm.passthrough.astype(bool)].copy()
    p["vendor"] = p.family.fillna(p.vendor_name).astype(str)
    a = p[p.lens.notna()].groupby(["lens", "vendor"]).amount.sum().reset_index()
    for area, grp in a.groupby("lens"):
        grp = grp.sort_values("amount", ascending=False)
        tail = grp.amount.iloc[10:].sum()
        if tail > 1e6:
            rows.append(pd.DataFrame([{"detector": "Tail spend", "agency_code": None, "agency": "Statewide", "area": area,
                                       "spending_code": f"{len(grp) - 10:,} smaller vendors", "baseline": tail, "low": .03 * tail, "high": .10 * tail,
                                       "evidence": f"${tail / 1e6:,.1f}M paid to vendors outside the ten largest in FY{PY}"}]))
    v = p.groupby("vendor").agg(spend=("amount", "sum"), agencies=("agency_code", "nunique"))
    v = v[(v.agencies >= 10) & (v.spend >= 5e6)]
    rows.append(pd.DataFrame({"detector": "Leverage", "agency_code": None, "agency": "Statewide", "area": None,
                              "spending_code": v.index.str.title(), "baseline": v.spend.values, "low": .02 * v.spend.values, "high": .05 * v.spend.values,
                              "evidence": [f"paid by {n} agencies separately in FY{PY}" for n in v.agencies]}))
    d = pd.concat(rows, ignore_index=True)
    d["likely"] = (d.low + d.high) / 2
    d = d.sort_values("likely", ascending=False).reset_index(drop=True)
    d.insert(0, "opp_id", [f"O{i:03d}" for i in range(1, len(d) + 1)])
    for k in ("baseline", "low", "high", "likely"):
        d[k] = d[k].round(0)
    return d
