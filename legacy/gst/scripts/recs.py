"""Recommendations as tracked outputs, re-checked on every run.

Each of the six recommendations on the Overview gets a table the dashboard shows, a status with one key number,
and a history row per run (model/rec_history.csv), so the tracker shows what changed since the last refresh.
"""
from pathlib import Path

import numpy as np
import pandas as pd

SKIP = (r"CONSTRUCT|PAVING|CONTRACTING|MCO|HEALTH|TRUST|BANK|SCHOOL|ACADEMY|UNIVERSITY|COLLEGE|HOSPITAL|COUNTY|CITY OF|\bJV\b|BUS|INSURANCE|ROOF|MECHANICAL|ENGINEERS|TITLE|RESCUE|BUILDERS|EXCAVAT|BRIDGE|STEEL|CONCRETE|YESHIVA|TALMUD|HOME OF|ARC OF|COUNCIL|CHARIT|SHELTER|FAMILY|YOUTH|COMMUNITY|SERVICES FOR|CENTER FOR|SOCIETY|FOUNDATION|ASSOCIATION"
        r"|BALTIMORE GAS|PEPCO|POTOMAC ELECTRIC|DELMARVA|POTOMAC EDISON|WASHINGTON GAS LIGHT|SCHLOSSER|MYERS|ZIMMER|CHRISTMAN")  # service providers and regulated utilities are not biddable contracts


def _ops(pm):
    p = pm[~pm.is_government.astype(bool) & ~pm.passthrough.astype(bool) & ~pm.agency_code.isin(["CAPITAL", "D06", "D25"])].copy()
    p["vendor"] = p.family.fillna(p.vendor_name).astype(str)
    return p


def bid_list(p, names):
    """R1: vendors paid separately by ten or more agencies in FY2026."""
    q = p[p.fiscal_year.isin([2025, 2026])]
    g = q.groupby(["vendor", "fiscal_year"]).amount.sum().unstack(fill_value=0)
    a = q[q.fiscal_year == 2026].groupby("vendor").agency_code.nunique()
    top = (q[q.fiscal_year == 2026].groupby(["vendor", "agency_code"]).amount.sum().reset_index()
           .sort_values("amount", ascending=False).groupby("vendor").head(3))
    top["n"] = top.agency_code.map(names).fillna(top.agency_code)
    top = top.groupby("vendor").n.agg(", ".join)
    d = pd.DataFrame({"fy2025": g.get(2025), "fy2026": g.get(2026), "agencies": a}).dropna(subset=["agencies"])
    d = d[(d.agencies >= 10) & (d.fy2026 >= 5e6) & ~d.index.str.upper().str.contains(SKIP, regex=True)].sort_values("fy2026", ascending=False)
    d["low"], d["high"] = .02 * d.fy2026, .05 * d.fy2026
    d["top_agencies"] = top.reindex(d.index)
    d = d.reset_index().rename(columns={"index": "vendor"})
    d.insert(0, "rank", range(1, len(d) + 1))
    d["vendor"] = d.vendor.str.title()
    return d


def vendor_detail(p, vendors):
    """Drill-down tables for each listed vendor: payments by agency and year (FY2022-FY2026) and the payee names merged into it."""
    up = {v.upper() for v in vendors}
    q = p[(p.fiscal_year >= 2022) & p.vendor.str.upper().isin(up)].copy()
    q["vendor"] = q.vendor.str.title()
    f = q.groupby(["vendor", "agency_code", "fiscal_year"]).amount.sum().round(2).reset_index().rename(columns={"amount": "paid"})
    n = q[q.fiscal_year == 2026].groupby(["vendor", "vendor_name"]).amount.sum().round(2).reset_index().rename(columns={"vendor_name": "payee_name", "amount": "fy2026"})
    return f, n


def contract_sets(p, target=81e6, drop=18e6, k=7, seed=5):
    """R3: sets of up to seven vendors whose FY2025 spending and FY2025-FY2026 decrease fit GMI's description."""
    q = p[p.fiscal_year.isin([2025, 2026])]
    g = q.groupby(["vendor", "fiscal_year"]).amount.sum().unstack(fill_value=0)
    a = q[q.fiscal_year == 2025].groupby("vendor").agency_code.nunique()
    c = g[(a.reindex(g.index).fillna(0) >= 3) & g[2025].between(1e6, 40e6) & (g[2026] <= .95 * g[2025]) & (g[2026] >= .5 * g[2025]) & ~g.index.str.upper().str.contains(SKIP, regex=True)]
    if len(c) < k:
        return pd.DataFrame(), pd.DataFrame()
    v25, dv = c[2025].values, (c[2025] - c[2026]).values
    rng = np.random.default_rng(seed)
    best = {}
    for _ in range(60000):
        n = rng.integers(3, k + 1)
        idx = tuple(sorted(rng.choice(len(c), n, replace=False)))
        s, d = v25[list(idx)].sum(), dv[list(idx)].sum()
        fit = abs(s - target) / target + abs(d - drop) / drop
        if fit < 0.15 and idx not in best:
            best[idx] = fit
    ranked = sorted(best.items(), key=lambda x: x[1])[:200]
    rows = []
    for sid, (idx, fit) in enumerate(ranked[:5], 1):
        for i in idx:
            rows.append({"set": sid, "fit": round(1 - fit, 4), "vendor": c.index[i].title(), "fy2025": v25[i], "fy2026": c[2026].values[i], "decrease": dv[i]})
    sets = pd.DataFrame(rows)
    freq = pd.Series([c.index[i] for idx, _ in ranked for i in idx]).value_counts()
    freq = pd.DataFrame({"vendor": freq.index.str.title(), "sets_found_in": freq.values, "share_of_sets": (freq.values / max(len(ranked), 1)).round(4),
                         "fy2025": c.loc[freq.index, 2025].values, "decrease": (c.loc[freq.index, 2025] - c.loc[freq.index, 2026]).values}).head(25)
    return sets, freq


def recurrence(d_sav, f_chk, run_id, hist_path):
    """R2: status of every payment check this run, with the previous run's status."""
    paid = f_chk.groupby(["check_id", "fiscal_year"]).paid.sum().unstack(fill_value=0)
    rep = d_sav.dropna(subset=["reported_low"]).assign(mid=lambda x: (x.reported_low + x.reported_high) / 2).groupby("check_id").mid.sum()
    rows = []
    for cid, r in paid.iterrows():
        b, a = r.get(2025, 0), r.get(2026, 0)
        rp = rep.get(cid)
        dropv = b - a
        st = "No reported figure" if not rp else ("Seen" if dropv >= .5 * rp else "Partly seen" if dropv > 0 else "Not seen yet")
        item = d_sav[d_sav.saving_id == cid].item.iloc[0]
        rows.append({"check_id": cid, "item": item, "reported": rp, "before": b, "after": a, "status": st})
    cur = pd.DataFrame(rows)
    hist = pd.read_csv(hist_path) if Path(hist_path).exists() else pd.DataFrame(columns=["run_id", "check_id", "status", "after"])
    prev = hist[hist.run_id != run_id].sort_values("run_id").groupby("check_id").tail(1).set_index("check_id")
    cur["previous_status"] = cur.check_id.map(prev.status) if len(prev) else None
    cur["changed"] = cur.previous_status.notna() & (cur.previous_status != cur.status)
    hist = pd.concat([hist[hist.run_id != run_id], cur[["check_id", "status", "after"]].assign(run_id=run_id)], ignore_index=True)
    hist.to_csv(hist_path, index=False)
    return cur


def plan50(fm, fc, bids):
    """R4: GMI's current pace, then the next actions, added up until they reach $50M a year."""
    f27 = fc[fc.fiscal_year == 2027].set_index("area").p50
    pace = float((fm.set_index("area").gmi_rate.fillna(0) * f27.reindex(fm.area).values).sum())
    rows = [{"step": 1, "action": "Keep GMI's current savings going", "basis": "forecast FY2027 spending × the rate GMI reported for each area", "saving": pace, "tab": "calc"}]
    for _, b in bids.iterrows():
        if sum(r["saving"] for r in rows) >= 50e6:
            break
        rows.append({"step": len(rows) + 1, "action": f"Statewide contract: {b.vendor}", "basis": f"3.5% of ${b.fy2026 / 1e6:,.1f}M paid by {int(b.agencies)} agencies (range 2-5%)", "saving": .035 * b.fy2026, "tab": "opp"})
    if sum(r["saving"] for r in rows) < 50e6:
        for area in ("Real estate & leases", "Utilities & facility energy"):
            rows.append({"step": len(rows) + 1, "action": f"Start savings in {area.lower()} at 1%", "basis": f"1% of forecast FY2027 spending of ${f27.get(area, 0) / 1e6:,.1f}M", "saving": .01 * f27.get(area, 0), "tab": "calc"})
    d = pd.DataFrame(rows)
    d["cumulative"] = d.saving.cumsum()
    return d


def master_quality(pm, am, vm, prev_path):
    """R5: how well payments match the agency and vendor master lists; new payee names since the last run."""
    p26 = pm[pm.fiscal_year == 2026]
    matched = float(p26.loc[p26.agency_code.notna(), "amount"].sum() / p26.amount.sum())
    fam = vm[vm.family.notna()]; fam = fam[fam.groupby("family").vendor_name.transform("nunique") > 1]  # companies paid under two or more names
    names = set(p26.vendor_name.astype(str))
    prev = set(Path(prev_path).read_text().splitlines()) if Path(prev_path).exists() else set()
    new = len(names - prev) if prev else 0
    Path(prev_path).write_text("\n".join(sorted(names)))
    unmatched = sorted(set(pm.loc[pm.agency_code.isna(), "agency_name"].astype(str)))
    rows = [("FY2026 payments matched to a budget agency", f"{matched:.2%}", matched >= .99),
            ("Payment agency names mapped", f"{am.agency_code.notna().sum():,} of {len(am):,}", True),
            ("Payee names grouped into companies", f"{fam.vendor_name.nunique():,} names in {fam.family.nunique():,} companies" if len(fam) else "—", True),
            ("New payee names since the last run", f"{new:,}" if prev else "first run recorded", True),
            ("Agency names not yet mapped", ", ".join(unmatched[:6]) + (" …" if len(unmatched) > 6 else "") if unmatched else "none", len(unmatched) <= 10)]
    return pd.DataFrame(rows, columns=["measure", "value", "ok"]), matched


def status(bids, chk, sets, plan, matched):
    seen = int((chk.status == "Seen").sum()); tot = int((chk.status != "No reported figure").sum())
    reach = plan.cumulative.iloc[-1] >= 50e6
    return pd.DataFrame([
        (1, "Bid statewide contracts for shared vendors", "Ready", f"{len(bids)} vendors ranked; ${bids.low.sum() / 1e6:,.1f}M–${bids.high.sum() / 1e6:,.1f}M a year", "opp"),
        (2, "Confirm which reported savings recur", "Tracking", f"{seen} of {tot} checks seen in payments; {int(chk.changed.sum())} changed since last run", "track"),
        (3, "Name the seven renegotiated contracts", "Candidates found" if len(sets) else "No fit found", f"{sets.set.nunique() if len(sets) else 0} vendor sets fit $81M / $18M; awaiting GMI's list", "track"),
        (4, "Plan the rest of the path to $50M", "Plan reaches $50M" if reach else "Gap remains", f"{len(plan)} steps to ${plan.cumulative.iloc[-1] / 1e6:,.1f}M a year", "calc"),
        (5, "Keep one vendor and agency master list", "In place", f"{matched:.1%} of FY2026 payments matched to an agency", "data"),
        (6, "Tie spending to results", "Needs a data feed", "Current Managing for Results measures are published only in the budget books (PDF); the open data portal has 2016 files only", "data"),
    ], columns=["rec", "title", "status", "progress", "tab"])
