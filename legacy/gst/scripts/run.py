"""GMI Savings Tracker pipeline.

    python scripts/run.py                 # reuse downloads that still match the portal
    python scripts/run.py --fresh         # download everything again
    python scripts/run.py --inject-fault  # test: drop half of FY2015 and show the repair

Stages: raw (download + reconcile) -> staged (master lists) -> model -> checks -> publish -> run log.
If any check fails, nothing in out/ is replaced: the last good version stays published.
"""
import json
import os
import shutil
import sys
import time
import urllib.request

import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from common import RUN, OUT, MODEL, STAGED, ROOT, write_json  # noqa: E402
import sources  # noqa: E402
import model as Mo  # noqa: E402
import payments_legacy as P  # noqa: E402
import measures as Me  # noqa: E402

FRESH, FAULT = "--fresh" in sys.argv, "--inject-fault" in sys.argv


def site_total(url, tries=4):
    """Fetch a state site's JSON, retrying transient network errors with backoff (self-healing)."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            RUN.repairs += 1
            RUN.event(f"retry {i + 1} for {url}: {e}")
            time.sleep(2 ** i * 3)


def main():
    t0 = time.time()
    raw, info = {}, []
    for key in sources.SOURCES:
        df, i = sources.load(key, fresh=FRESH, inject_fault=FAULT)
        raw[key] = df
        info.append(i)

    # ---- staged: master lists
    am = Mo.agency_master(raw["payments"], raw["budget"])
    vm = Mo.vendor_master(raw["payments"])
    am.to_csv(STAGED / "agency_master.csv", index=False)
    vm.to_csv(STAGED / "vendor_master.csv", index=False)

    # ---- model
    # budget stage per year, as the state's Operating Budget site states it
    try:
        cfg = site_total("https://operatingbudget.maryland.gov/api/content_config.json")[0]
        stages = Mo.official_stages(cfg.get("homepage", "") + " " + cfg.get("about_page", ""))
    except Exception as e:
        stages = None
        RUN.event(f"could not read the Operating Budget site's year statement: {e}")
    years = sorted(int(y) for y in raw["budget"].fiscal_year.astype(int).unique())
    RUN.check("model", "Budget stage for every year comes from the Operating Budget site", bool(stages) and all(y in stages for y in years),
              ("; ".join(f"FY{y} {stages[y].lower()}" for y in years if stages and y in stages)) if stages else "site statement not found; using the file's own labels")
    bm = Mo.budget_model(raw["budget"], stages)
    stale = bm.groupby("fiscal_year").agg(file_stage=("file_stage", "first"), stage=("stage", "first")).reset_index()
    stale = stale[stale.file_stage != stale.stage]
    if len(stale):
        RUN.check("model", "Out-of-date stage labels in the budget file corrected", True,
                  "; ".join(f"FY{r.fiscal_year}: file says {r.file_stage.lower()}, site says {r.stage.lower()}" for r in stale.itertuples()))
    pm = Mo.payments_model(raw["payments"], am, vm)
    ay = Mo.agency_year(bm, raw["fte"], pm)
    fund = raw["fund"].assign(fiscal_year=lambda d: d.fiscal_year.astype(int), budget=lambda d: pd.to_numeric(d.budget, errors="coerce").fillna(0))
    code_agency = (bm.groupby(["fiscal_year", "stage", "agency_code", "object_name", "code", "comptroller_subobject_name",
                               "controllable", "area"], dropna=False).budget.sum().reset_index())
    code_agency.to_csv(MODEL / "budget_code_agency_fy.csv", index=False)
    pm.groupby(["fiscal_year", "agency_code", "family", "lens", "is_government", "passthrough"], dropna=False).amount.sum() \
      .reset_index().to_csv(MODEL / "payments_family_agency_fy.csv", index=False)
    ay.to_csv(MODEL / "agency_year.csv", index=False)

    # ---- checks
    cov = pm.groupby("fiscal_year").apply(lambda d: d.loc[d.agency_code.notna(), "amount"].sum() / d.amount.sum())
    RUN.check("staged", "Payments linked to an agency", cov.min() >= 0.99,
              f"{cov.min():.1%} of dollars linked in the weakest year (FY{cov.idxmin()}), {cov.loc[2026]:.1%} in FY2026", warn=cov.min() >= 0.9)
    un = am[am.agency_code.isna()]
    RUN.check("staged", "Agency names mapped across years", len(un) <= 5,
              f"{len(am):,} payment agency names; {len(un)} unmatched" + (f" ({', '.join(un.payment_agency_name.head(5))})" if len(un) else ""), warn=True)
    fam_multi = vm[vm.family != vm.vendor_key].family.nunique()
    RUN.check("staged", "Vendor master list built", True,
              f"{vm.vendor_key.nunique():,} payee names grouped into {vm.family.nunique():,} vendors; {fam_multi} company families merged")
    bt = bm.groupby("fiscal_year").budget.sum(); ft = fund.groupby("fiscal_year").budget.sum()
    gap = ((bt - ft).abs() / ft).max()
    RUN.check("model", "Operating budget matches its funding-source totals", gap < 0.005, f"largest gap {gap:.3%} across FY{bt.index.min()}–FY{bt.index.max()}")
    a25 = bm[(bm.fiscal_year == 2025) & (bm.stage == "Actual")]
    share = a25.loc[a25.controllable, "budget"].sum() / a25.budget.sum()
    RUN.check("model", "Controllable spending in a plausible range", 0.05 < share < 0.4,
              f"FY2025: ${a25.loc[a25.controllable,'budget'].sum()/1e9:,.2f}B controllable of ${a25.budget.sum()/1e9:,.2f}B ({share:.1%})")
    fte25 = ay[(ay.fiscal_year == 2025) & ay.budget_actual.notna()]
    RUN.check("model", "Staffing joined to agencies", fte25.fte.notna().mean() > 0.8,
              f"{fte25.fte.notna().sum()} of {len(fte25)} agencies with FY2025 actuals have staffing counts")
    for y in (2025, 2026, 2027):
        try:
            site = site_total(f"https://operatingbudget.maryland.gov/api/opex/totals.json?year={y}")[0]["amount"]
            g = abs(bm[bm.fiscal_year == y].budget.sum() - float(site))
            RUN.check("cross-check", f"FY{y} budget matches operatingbudget.maryland.gov", g <= 10, f"site ${float(site):,.0f}; gap ${g:,.0f}")
        except Exception as e:
            RUN.check("cross-check", f"FY{y} budget matches operatingbudget.maryland.gov", False, f"site not reachable: {e}", warn=True)
    tot = pm.groupby("fiscal_year").amount.sum()
    for y in (2024, 2025, 2026):
        try:
            site = float(site_total(f"https://vendorpayments.maryland.gov/api/opex/totals.json?year={y}")[0]["amount"])
            RUN.check("cross-check", f"FY{y} payments match vendorpayments.maryland.gov", abs(tot[y] - site) <= 10, f"site ${site:,.0f}; gap ${abs(tot[y]-site):,.0f}")
        except Exception as e:
            RUN.check("cross-check", f"FY{y} payments match vendorpayments.maryland.gov", False, f"site not reachable: {e}", warn=True)

    # ---- publish tables (built in a staging folder, swapped in only if no check failed)
    pub = {}
    pub["totals_by_fy"] = Me.yoy(pm.groupby("fiscal_year").agg(total_payments=("amount", "sum"), payment_records=("amount", "size"),
                                                                agencies=("agency_code", "nunique"), vendors=("family", "nunique")).reset_index(),
                                 [], ["total_payments"], table="totals_by_fy")
    pub["budget_by_function"] = Me.yoy(bm.groupby(["fiscal_year", "stage", "category_title"]).budget.sum().reset_index(),
                                       ["category_title"], ["budget"], table="budget_by_function")
    stage_of = bm.groupby("fiscal_year").stage.first()
    pub["budget_by_fund"] = Me.yoy(fund.groupby(["fiscal_year", "fund_type_name"]).budget.sum().reset_index()
                                   .assign(stage=lambda d: d.fiscal_year.map(stage_of)), ["fund_type_name"], ["budget"], table="budget_by_fund")
    obj = bm.groupby(["fiscal_year", "stage", "object_name"]).agg(budget=("budget", "sum"),
                                                                 controllable=("budget", lambda s: s[bm.loc[s.index, "controllable"]].sum())).reset_index()
    pub["budget_by_object"] = Me.yoy(obj, ["object_name"], ["budget", "controllable"], table="budget_by_object", good="lower")
    scope = bm.assign(scope=pd.Series(["Controllable purchases"] * len(bm), index=bm.index)
                      .mask(bm.internal, "Charges between agencies").mask(bm.entitlement, "Client payments and debt service")
                      .mask(bm.object_name.isin(Mo.EXCLUDED_OBJECTS) & ~bm.entitlement & ~bm.internal, "Staff, grants and capital"))
    pub["spending_scope"] = Me.yoy(scope.groupby(["fiscal_year", "stage", "scope"]).budget.sum().reset_index(),
                                   ["scope"], ["budget"], table="spending_scope")
    ay = ay.rename(columns={"budget_actual": "operating_spending"})
    pub["agency_year"] = Me.yoy(ay[["agency_code", "agency", "fiscal_year", "stage", "operating_spending", "controllable", "fte", "payments", "controllable_per_fte"]]
                                .dropna(subset=["stage"]), ["agency_code"], ["controllable", "fte", "controllable_per_fte"], table="agency_year", good="lower")
    pub["agency_master"] = am.groupby(["agency_code", "agency", "in_budget"], dropna=False).agg(
        payment_names=("payment_agency_name", "nunique"), how_matched=("matched_by", lambda s: "; ".join(sorted(set(map(str, s)))[:3]))).reset_index()
    y26 = pm[(pm.fiscal_year == 2026) & ~pm.is_government]
    fams = y26.groupby("family").agg(payee_names=("vendor_name", "nunique"), spend=("amount", "sum"), agencies=("agency_code", "nunique")).reset_index()
    pub["vendor_families"] = fams[fams.payee_names >= 2].sort_values("spend", ascending=False)
    # ---- focus areas: the six GMI areas, by the state's spending codes and by payee name
    fa = bm[bm.area.notna()]
    names = bm.sort_values("fiscal_year").groupby("agency_code").agency_name.last()
    ay_area = fa.groupby(["fiscal_year", "stage", "area"]).agg(spend=("budget", "sum"), agencies=("agency_code", "nunique"),
                                                               codes=("code", "nunique")).reset_index()
    pay_area = pm[pm.lens.notna()].groupby(["fiscal_year", "lens"]).agg(payee_spend=("amount", "sum"), vendors=("family", "nunique")) \
        .reset_index().rename(columns={"lens": "area"})
    ay_area = ay_area.merge(pay_area, on=["fiscal_year", "area"], how="outer")
    ay_area["stage"] = ay_area.stage.fillna("Payments only")
    pub["area_year"] = Me.yoy(ay_area, ["area"], ["spend", "payee_spend"], table="area_year", good="lower")
    aa = fa.groupby(["fiscal_year", "stage", "area", "agency_code"]).budget.sum().rename("spend").reset_index()
    aa["agency"] = aa.agency_code.map(names)
    pub["area_agency_year"] = Me.yoy(aa, ["area", "agency_code"], ["spend"], table="area_agency_year", good="lower")
    ac = fa.groupby(["fiscal_year", "stage", "area", "code", "comptroller_subobject_name"]).agg(
        spend=("budget", "sum"), agencies=("agency_code", "nunique")).reset_index().rename(columns={"comptroller_subobject_name": "spending_code"})
    pub["area_code_year"] = Me.yoy(ac, ["area", "code"], ["spend"], table="area_code_year", good="lower")
    av = pm[pm.lens.notna() & (pm.fiscal_year >= 2022)].groupby(["fiscal_year", "lens", "family"]).agg(
        spend=("amount", "sum"), agencies=("agency_code", "nunique")).reset_index().rename(columns={"lens": "area", "family": "vendor"})
    av = av.sort_values("spend", ascending=False).groupby(["fiscal_year", "area"]).head(15)
    pub["area_vendor_year"] = Me.yoy(av, ["area", "vendor"], ["spend"], table="area_vendor_year", good="lower")
    a25 = pub["area_year"].query("fiscal_year == 2025")
    RUN.check("model", "Focus areas built from spending codes and payee names", a25.spend.notna().sum() == 6,
              f"FY2025: ${a25.spend.sum()/1e9:,.2f}B by spending code; ${a25.payee_spend.sum()/1e6:,.0f}M found by payee name")
    # ---- fact tables at agency grain: every dashboard card filters these by year, area and agency
    stage_of = bm.groupby("fiscal_year").stage.first()
    g = lambda d, keys, vals: d.groupby(keys, dropna=False)[vals].sum().reset_index()
    pub["f_function"] = g(bm, ["fiscal_year", "stage", "agency_code", "category_title"], ["budget"])
    obj2 = bm.assign(ctrl=bm.budget.where(bm.controllable, 0.0))
    pub["f_object"] = g(obj2, ["fiscal_year", "stage", "agency_code", "object_name"], ["budget", "ctrl"]).rename(columns={"ctrl": "controllable"})
    pub["f_scope"] = g(scope, ["fiscal_year", "stage", "agency_code", "scope"], ["budget"])
    fund["stage"] = fund.fiscal_year.map(stage_of)
    pub["f_fund"] = g(fund, ["fiscal_year", "stage", "agency_code", "fund_type_name"], ["budget"])
    fa_code = g(fa, ["fiscal_year", "stage", "agency_code", "area", "code", "comptroller_subobject_name"], ["budget"]) \
        .rename(columns={"comptroller_subobject_name": "spending_code", "budget": "spend"})
    pub["f_code"] = fa_code
    pay_ag = pm[pm.lens.notna()].groupby(["fiscal_year", "agency_code", "lens"]).amount.sum().reset_index() \
        .rename(columns={"lens": "area", "amount": "payee_spend"})
    fa_ag = g(fa, ["fiscal_year", "agency_code", "area"], ["budget"]).rename(columns={"budget": "spend"})
    f_area = fa_ag.merge(pay_ag, on=["fiscal_year", "agency_code", "area"], how="outer")
    f_area["stage"] = f_area.fiscal_year.map(stage_of).fillna("Payments only")
    pub["f_area"] = f_area[["fiscal_year", "stage", "agency_code", "area", "spend", "payee_spend"]]
    fv = pm[pm.lens.notna() & (pm.fiscal_year >= 2022)].groupby(["fiscal_year", "agency_code", "lens", "family"]).amount.sum().reset_index() \
        .rename(columns={"lens": "area", "family": "vendor", "amount": "spend"})
    pub["f_vendor"] = fv
    import savings as Sv
    pub["d_savings"], pub["f_savings_check"], pub["d_vendor_moves"] = Sv.build(pm)
    import opportunities as Op
    pub["d_opps"] = Op.build(code_agency, pub["agency_year"], pm)
    import forecast as Fc
    pub["f_forecast"], pub["d_forecast_model"] = Fc.build(pub["f_code"], pub["f_scope"], pub["f_fund"])
    import recs as Rc
    _ops = Rc._ops(pm); _names = pub["agency_year"].groupby("agency_code").agency.last()
    pub["d_bid_list"] = Rc.bid_list(_ops, _names)
    _lev = pub["d_opps"].loc[pub["d_opps"].detector == "Leverage", "spending_code"].tolist() if "d_opps" in pub else []
    pub["f_vendor_detail"], pub["d_vendor_names"] = Rc.vendor_detail(_ops, list(pub["d_bid_list"].vendor) + _lev)
    pub["d_savings_status"] = Rc.recurrence(pub["d_savings"], pub["f_savings_check"], RUN.run_id, MODEL / "savings_status_history.csv")
    pub["d_plan50"] = Rc.plan50(pub["d_forecast_model"], pub["f_forecast"], pub["d_bid_list"])
    pub["d_master_quality"], _matched = Rc.master_quality(pm, am, vm, MODEL / "payee_names_prev.txt")
    pub["d_rec_status"] = Rc.status(pub["d_bid_list"], pub["d_savings_status"], pub["d_plan50"], _matched)
    _rh = MODEL / "rec_history.csv"; _h = pd.read_csv(_rh) if _rh.exists() else pd.DataFrame()
    _h = pd.concat([_h, pub["d_rec_status"].assign(run_id=RUN.run_id)], ignore_index=True); _h.to_csv(_rh, index=False)
    _prev = _h[_h.run_id != RUN.run_id].groupby("rec").tail(1).set_index("rec") if "run_id" in _h else pd.DataFrame()
    pub["d_rec_status"]["previous"] = pub["d_rec_status"].rec.map(_prev.progress) if len(_prev) else None
    RUN.check("recs", "Bid list has shared vendors", len(pub["d_bid_list"]) > 0, f"{len(pub['d_bid_list'])} vendors paid by 10+ agencies")
    RUN.check("recs", "Every reported savings item has a status", pub["d_savings_status"].status.notna().all(), pub["d_rec_status"].progress[1])
    _ds = pub["d_savings"]
    RUN.check("recs", "Every reported savings item cites its source and page", bool((_ds.source_url.str.startswith("https://") & (_ds.source_page.str.len() > 0) & (_ds.source_quote.str.len() > 0)).all()),
              f"{len(_ds)} items; sources: " + "; ".join(sorted(_ds.source.unique())))
    RUN.check("recs", "Named contract types checked against payments", pub["d_savings_status"].check_id.isin(["S02", "S03", "S04", "S05"]).sum() == 4, pub["d_rec_status"].progress[2])
    RUN.check("recs", "Path to $50M adds up", abs(pub["d_plan50"].saving.sum() - pub["d_plan50"].cumulative.iloc[-1]) < 1, pub["d_rec_status"].progress[3])
    RUN.check("recs", "Payments match the agency master list", _matched >= .99, f"{_matched:.2%} of FY2026 payments matched")
    fc = pub["f_forecast"].dropna(subset=["p50"])
    RUN.check("model", "Forecast intervals are ordered and positive", bool(((fc.p10 <= fc.p50) & (fc.p50 <= fc.p90) & (fc.p10 > 0)).all()), f"{len(fc)} forecast years across {fc.area.nunique()} spending groups, FY2026-FY2031")
    for mrow in pub["d_forecast_model"].itertuples():
        RUN.check("model", f"Forecast backtest: {mrow.area}", mrow.backtest_mape < 0.25, f"{mrow.method}; FY2023-FY2025 error {mrow.backtest_mape:.1%} (trend {mrow.trend_mape:.1%}, naive {mrow.naive_mape:.1%}, drift {mrow.drift_mape:.1%})", warn=True)
    RUN.check("publish", "Opportunity detectors produced findings", len(pub["d_opps"]) > 0 and pub["d_opps"].likely.ge(0).all(),
              f"{len(pub['d_opps'])} findings, likely total ${pub['d_opps'].likely.sum() / 1e6:,.0f}M (range ${pub['d_opps'].low.sum() / 1e6:,.0f}M-${pub['d_opps'].high.sum() / 1e6:,.0f}M)")
    sc = pub["f_savings_check"].groupby(["check_id", "fiscal_year"]).paid.sum().unstack()
    RUN.check("publish", "Every savings check has FY2025 and FY2026 payments", bool((sc[[2025, 2026]] > 0).all().all()),
              f"{len(sc)} payment checks for {len(pub['d_savings'])} reported items")
    pub["f_agency"] = pub["agency_year"][["agency_code", "agency", "fiscal_year", "stage", "operating_spending", "controllable", "fte", "payments"]]
    pub["d_agency"] = pub["agency_year"].groupby("agency_code").agency.last().reset_index().dropna()
    # invariants: the agency-grain facts add up to the statewide figures
    inv = [
        ("Functions by agency add up to the statewide budget", pub["f_function"].groupby("fiscal_year").budget.sum(), bm.groupby("fiscal_year").budget.sum()),
        ("Funds by agency add up to the funding-source totals", pub["f_fund"].groupby("fiscal_year").budget.sum(), fund.groupby("fiscal_year").budget.sum()),
        ("Controllable purchases agree across tables", pub["f_object"].groupby("fiscal_year").controllable.sum(),
         pub["f_scope"].query("scope == 'Controllable purchases'").groupby("fiscal_year").budget.sum()),
        ("Focus areas by agency add up to the statewide areas", pub["f_area"].groupby("fiscal_year").spend.sum().reindex(pub["area_year"].groupby("fiscal_year").spend.sum().index),
         pub["area_year"].groupby("fiscal_year").spend.sum()),
        ("Spending codes add up to the focus areas", pub["f_code"].groupby("fiscal_year").spend.sum(), pub["f_area"].groupby("fiscal_year").spend.sum().loc[lambda s: s > 0]),
    ]
    for name, a_, b_ in inv:
        gap = (a_.fillna(0) - b_.reindex(a_.index).fillna(0)).abs().max()
        RUN.check("publish", name, gap <= 1, f"largest gap ${gap:,.0f} across {len(a_)} years")
    linked = pub["f_area"].payee_spend.sum() / pm[pm.lens.notna()].amount.sum()
    RUN.check("publish", "Payee-name spending linked to agencies", linked > 0.99, f"{linked:.2%} of payee-name focus spending has an agency")
    ev = pd.read_csv(MODEL / "stage_evidence.csv") if (MODEL / "stage_evidence.csv").exists() else pd.DataFrame()
    pub["stage_evidence"] = ev
    for e in ev[ev.programs_compared.notna()].itertuples():
        RUN.check("cross-check", f"FY{e.fiscal_year} matches DBM's published actuals", e.programs_exact / e.programs_compared > 0.6,
                  f"{int(e.programs_exact)} of {int(e.programs_compared)} programs match to the dollar; {e.evidence}")
    pub["sources"] = pd.DataFrame(info)
    pub["measures"] = Me.catalog()
    for k, v in pub.items():
        assert not v.duplicated().any(), f"duplicate rows in {k}"
    yo = pub["agency_year"]
    RUN.check("publish", "Year-over-year measures computed", yo.controllable_yoy.notna().sum() > 0,
              f"{len(Me.catalog())} measures across {Me.catalog().table.nunique()} tables; agency FY2027 rows: {int((yo.fiscal_year==2027).sum())}")
    RUN.check("publish", "Published tables have no duplicate rows", True, f"{len(pub)} tables, {sum(len(v) for v in pub.values()):,} rows")

    tmp = ROOT / "out_next"
    shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir()
    for k, v in pub.items():
        v = v.copy()
        for c in v.columns:
            if v[c].dtype.kind == "f":
                v[c] = v[c].round(5 if c.endswith(("_yoy", "_rate", "_mape", "_share")) or c == "growth" else 2)  # rates and shares keep their precision
        v.to_csv(tmp / f"{k}.csv", index=False)
    # ---- dashboard tests: render the page against the new tables before publishing anything
    if os.environ.get("SKIP_PAGE_TEST") != "1":
        import page_test as PT
        try:
            tabs = PT.tables_from([tmp, OUT])
            for name, ok, detail in PT.run_tests(tabs, PT.top3(tabs), latest=int(pub["agency_year"].query("stage == 'Actual'").fiscal_year.max())):
                RUN.check("page", name, ok, detail)
        except Exception as e:  # noqa: BLE001
            RUN.check("page", "Dashboard tests could run", False, f"{type(e).__name__}: {e}")
    status = "failed" if RUN.failed else "passed"
    pd.DataFrame(RUN.checks).to_csv(tmp / "run_checks.csv", index=False)
    if status == "passed":
        for f in tmp.iterdir():
            shutil.copy(f, OUT / f.name)
    else:
        pd.DataFrame(RUN.checks).to_csv(OUT / "run_checks_failed.csv", index=False)

    # ---- run history (always written, so a failed run is visible)
    hist_path = MODEL / "pipeline_runs.csv"
    hist = pd.read_csv(hist_path) if hist_path.exists() else pd.DataFrame()
    row = {"run_id": RUN.run_id, "started_utc": RUN.started.isoformat(timespec="seconds"), "seconds": round(time.time() - t0, 1),
           "status": status, "published": status == "passed", "checks": len(RUN.checks),
           "passed": sum(c["status"] == "pass" for c in RUN.checks), "warnings": sum(c["status"] == "warn" for c in RUN.checks),
           "failed": RUN.failed, "repairs": RUN.repairs, "payment_rows": len(raw["payments"]), "budget_rows": len(raw["budget"]),
           "mode": "fresh download" if FRESH else ("test fault injected" if FAULT else "incremental")}
    hist = pd.concat([hist, pd.DataFrame([row])], ignore_index=True)
    hist.to_csv(hist_path, index=False); hist.to_csv(OUT / "pipeline_runs.csv", index=False)
    write_json(MODEL / f"run_{RUN.run_id}.json", {"run": row, "checks": RUN.checks, "events": RUN.events})
    print(json.dumps(row))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
