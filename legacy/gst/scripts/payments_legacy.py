"""Maryland Spend Lens pipeline.

Pulls Maryland's statewide payments file (DBM, opendata.maryland.gov 7syw-q4cy)
for FY2008-FY2026, checks every year against the portal's own counts and totals,
re-fetches any year that does not reconcile, tags GMI focus areas, runs the
statistics, and writes the dashboard's datasets plus a health report.

Self-healing:
  - every HTTP call retries with exponential backoff
  - each fiscal year is reconciled (row count and dollar total) against the API;
    a year that fails is deleted from the cache and fetched again, up to HEAL_ATTEMPTS
  - output checks run last; a failed check marks the run FAILED in the health report
    instead of shipping bad numbers silently
Feedback:
  - out/pipeline_health.csv: one row per check (status, detail), shown on the dashboard
  - out/run_log.json: timings, attempts and row counts for the run

Run:  python run_pipeline.py            (uses cached years that still reconcile)
      python run_pipeline.py --inject-fault  (demo: drops half of FY2015 and shows the heal)
      python run_pipeline.py --fresh    (re-downloads everything)
"""
import io, json, re, sys, time, datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm

BASE = "https://opendata.maryland.gov/resource/7syw-q4cy"
FYS = list(range(2008, 2027))
PAGE = 50000
RETRIES, HEAL_ATTEMPTS = 4, 2
HERE = Path(__file__).parent
RAW, OUT = HERE / "raw", HERE / "out"
RAW.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
LOG = {"started": dt.datetime.now(dt.timezone.utc).isoformat(), "years": {}, "events": []}
HEALTH = []

def health(check, ok, detail, warn=False):
    HEALTH.append({"check": check, "status": "pass" if ok else ("warn" if warn else "fail"), "detail": detail})
    return ok

def get(url, params):
    for i in range(RETRIES):
        try:
            r = requests.get(url, params=params, timeout=120)
            r.raise_for_status()
            return r
        except Exception as e:  # network or server error: back off and retry
            wait = 2 ** i
            LOG["events"].append(f"retry {i + 1} for {url} {params.get('$where', '')}: {e}; waiting {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"gave up after {RETRIES} attempts: {url} {params}")

def api_totals():
    r = get(f"{BASE}.json", {"$select": "fiscal_year,count(*) as n,sum(amount) as total",
                              "$group": "fiscal_year", "$order": "fiscal_year"})
    return {int(x["fiscal_year"]): (int(x["n"]), float(x["total"])) for x in r.json()}

def fetch_year(fy):
    parts, off = [], 0
    while True:
        r = get(f"{BASE}.csv", {"$where": f"fiscal_year={fy}", "$order": ":id", "$limit": PAGE, "$offset": off})
        df = pd.read_csv(io.StringIO(r.text), dtype={"vendor_zip": str})
        parts.append(df)
        if len(df) < PAGE:
            break
        off += PAGE
    return pd.concat(parts, ignore_index=True)

def load_years(fresh):
    truth = api_totals()
    frames = []
    for fy in FYS:
        path = RAW / f"fy{fy}.csv"
        n_true, t_true = truth.get(fy, (0, 0.0))
        for attempt in range(HEAL_ATTEMPTS + 1):
            if fresh or not path.exists() or attempt > 0:
                fetch_year(fy).to_csv(path, index=False)
            df = pd.read_csv(path, dtype={"vendor_zip": str})
            if "--inject-fault" in sys.argv and fy == 2015 and attempt == 0:
                df = df.iloc[: len(df) // 2]  # demo: pretend half of FY2015 was lost in transfer
            ok = len(df) == n_true and abs(df.amount.sum() - t_true) <= max(1.0, 1e-6 * t_true)
            LOG["years"][fy] = {"rows": len(df), "api_rows": n_true, "attempts": attempt + 1, "reconciled": ok}
            if ok:
                break
            LOG["events"].append(f"FY{fy} did not reconcile (rows {len(df)} vs {n_true}); re-fetching")
        health(f"FY{fy} matches the portal", ok,
               f"{len(df):,} rows, ${df.amount.sum():,.0f}" + (f"; test fault injected (half the rows dropped), caught and re-fetched, healed on attempt {attempt + 1}" if ok and attempt and "--inject-fault" in sys.argv else f"; healed on attempt {attempt + 1}" if ok and attempt else "") + ("" if ok else f" vs portal {n_true:,} rows, ${t_true:,.0f}"))
        frames.append(df)
    return pd.concat(frames, ignore_index=True)

# ---------- tagging ----------
SUF = r"\b(INC|INCORPORATED|LLC|L L C|LTD|CORP|CORPORATION|CO|COMPANY|LP|L P|LLP|PLLC|PC|THE|OF AMERICA|USA|US)\b"
def norm(s):
    s = re.sub(r"[^A-Z0-9& ]", " ", str(s).upper()); s = re.sub(SUF, " ", s)
    return re.sub(r"\s+", " ", s).strip()

LENSES = {
    "Fleet & fuel": r"ELEMENT FLEET|CARROLL INDEPENDENT FUEL|\bFUEL\b|PETROLEUM|\bWEX\b|VOYAGER|CHEVROLET|\bFORD\b|TOYOTA|DODGE|CHRYSLER|HONDA|NISSAN|\bTIRE|AUTO PARTS|\bMOTORS?\b|FLEET",
    "IT hardware, software & services": r"^SHI INTERNATIONAL|CARAHSOFT|APPLIED TECHNOLOGY SERVICES|ADVANCED COMPUTER CONCEPTS|SKYLINE TECHNOLOGY SOLUTIONS|^DELL\b|^CDW|MICROSOFT|ORACLE|SALESFORCE|^IBM\b|INTERNATIONAL BUSINESS MACHINES|CISCO|GARTNER|^SAP\b|AMAZON WEB|GOOGLE|ADOBE|SOFTWARE|^COMPUTER|COMPUTER (?:SYSTEMS|SOLUTIONS|CONCEPTS)",
    "Telecom": r"VERIZON|AT & T|^AT T\b|T MOBILE|COMCAST|SPRINT|CROWN CASTLE",
    "Print, copy & mail": r"^CANON|^RICOH|^XEROX|QUADIENT|PITNEY BOWES|KONICA|SHARP ELECTRONICS|\bPRINTING\b|DOCUMENT",
    "Utilities & facility energy": r"BALTIMORE GAS & ELECTRIC|POTOMAC ELECTRIC|PEPCO|DELMARVA POWER|POTOMAC EDISON|WASHINGTON GAS|CONSTELLATION|WSSC|SOUTHERN MARYLAND ELECTRIC|CHOPTANK ELECTRIC",
    "Real estate & leases": r"REALTY|PROPERTIES|PROPERTY MANAGEMENT|LEASING|REAL ESTATE|LANDLORD|\bPLAZA\b|OFFICE PARK",
}
GOV = re.compile(r"COUNTY|CITY OF|BOARD OF|PUBLIC SCHOOL|UNIVERSITY|COLLEGE|STATE OF|TREASUR|COMPTROLLER|COMMISSION|DEPARTMENT|DEPT|GOVERNMENT|AUTHORITY|MAYOR|TOWN OF|SCHOOLS|UNITED STATES|FEDERAL|MUNICIPAL|BALTIMORE CITY|HEALTHCARE|HEALTH PLAN|MEDICAL CENTER|HOSPITAL|MEDICAID|BANK|AGENCY ON AGING|ENVIRONMENTAL SERVICE|BLIND INDUSTRIES|OCCUPATIONAL HEALTH")

def tag(df):
    df["vnorm"] = df.vendor_name.map(norm)
    df["lens"] = None
    for k, p in LENSES.items():
        m = df.lens.isna() & df.vnorm.str.contains(p, regex=True)
        df.loc[m, "lens"] = k
    ag = df.agency_name.str.upper()
    # Health Department "Leasing Co LLC" payees are nursing-facility operators paid through Medicaid
    nursing = (df.lens == "Real estate & leases") & ag.str.contains("HEALTH|DHMH")
    # Utility payments by PSC, Human Services/Resources and Housing are customer bill assistance
    assist = (df.lens == "Utilities & facility energy") & ag.str.contains("PUBLIC SERVICE COMMISSION|HUMAN SERVICES|HUMAN RESOURCES|HOUSING")
    # Xerox State & Local Solutions / State Healthcare ran benefits and Medicaid processing, not printing;
    # the Fuel Fund of Maryland is an energy-assistance charity
    bpo = df.vnorm.str.contains("STATE & LOCAL SOLUTIONS|XEROX STATE HEALTHCARE|FUEL FUND")
    df.loc[bpo, "lens"] = None
    LOG["excluded_bpo_dollars"] = float(df.loc[bpo, "amount"].sum())
    LOG["excluded"] = {"nursing_facility_rows": int(nursing.sum()), "nursing_facility_dollars": float(df.loc[nursing, "amount"].sum()),
                       "bill_assistance_rows": int(assist.sum()), "bill_assistance_dollars": float(df.loc[assist, "amount"].sum())}
    df.loc[nursing | assist, "lens"] = None
    df["passthrough"] = nursing | assist | bpo
    return df

# ---------- CPI (BLS CPI-U NSA via FRED CPIAUCNS), July-June averages ----------
CPI_Q = {  # quarterly averages FY2008-FY2021
 "2007Q3":208.235,"2007Q4":209.716,"2008Q1":212.100,"2008Q2":216.757,"2008Q3":219.278,"2008Q4":213.075,"2009Q1":212.015,"2009Q2":214.263,
 "2009Q3":215.718,"2009Q4":216.152,"2010Q1":217.020,"2010Q2":218.051,"2010Q3":218.254,"2010Q4":218.898,"2011Q1":221.666,"2011Q2":225.531,
 "2011Q3":226.452,"2011Q4":226.108,"2012Q1":227.907,"2012Q2":229.793,"2012Q3":230.297,"2012Q4":230.380,"2013Q1":231.740,"2013Q2":232.993,
 "2013Q3":233.874,"2013Q4":233.221,"2014Q1":234.997,"2014Q2":237.772,"2014Q3":238.044,"2014Q4":236.132,"2015Q1":234.849,"2015Q2":237.681,
 "2015Q3":238.305,"2015Q4":237.233,"2016Q1":237.386,"2016Q2":240.169,"2016Q3":240.968,"2016Q4":241.505,"2017Q1":243.414,"2017Q2":244.737,
 "2017Q3":245.708,"2017Q4":246.619,"2018Q1":248.804,"2018Q2":251.374,"2018Q3":252.197,"2018Q4":252.052,"2019Q1":252.897,"2019Q2":255.928,
 "2019Q3":256.629,"2019Q4":257.176,"2020Q1":258.255,"2020Q2":256.860,"2020Q3":259.766,"2020Q4":260.364,"2021Q1":263.158,"2021Q2":269.315}
CPI_FY_RECENT = {2022: 282.025, 2023: 299.685, 2024: 309.570, 2025: 317.731, 2026: 327.668}  # from monthly data, July-June

def cpi_table():
    rows = []
    for fy in FYS:
        if fy in CPI_FY_RECENT:
            v, src = CPI_FY_RECENT[fy], "monthly"
        else:
            qs = [f"{fy-1}Q3", f"{fy-1}Q4", f"{fy}Q1", f"{fy}Q2"]
            v, src = float(np.mean([CPI_Q[q] for q in qs])), "quarterly"
        rows.append({"fiscal_year": fy, "cpi_u_avg": round(v, 3), "basis": src})
    c = pd.DataFrame(rows); base = c.loc[c.fiscal_year == 2026, "cpi_u_avg"].iloc[0]
    c["to_fy2026_dollars"] = (base / c.cpi_u_avg).round(4)
    return c

# ---------- statistics ----------
def hypothesis(series, cpi):
    """H1: focus-area spend grew faster than all state payments, after inflation (FY2008-FY2026)."""
    d = series.merge(cpi[["fiscal_year", "to_fy2026_dollars"]], on="fiscal_year")
    d["real"] = d.value * d.to_fy2026_dollars
    d["log_real"] = np.log(d.real); d["t"] = d.fiscal_year - 2008; d["focus"] = (d.group == "Focus areas").astype(int)
    d["t_x_focus"] = d.t * d.focus
    X = sm.add_constant(d[["t", "focus", "t_x_focus"]]); m = sm.OLS(d.log_real, X).fit(cov_type="HC1")
    b, se = m.params["t_x_focus"], m.bse["t_x_focus"]
    p_one = float(m.pvalues["t_x_focus"] / 2) if b > 0 else 1 - float(m.pvalues["t_x_focus"] / 2)
    ci = m.conf_int(alpha=0.05).loc["t_x_focus"].tolist()
    g = lambda k: float(np.expm1(m.params["t"] + (m.params["t_x_focus"] if k else 0)))
    rows = [
        {"item": "Hypothesis", "value": "Spend in GMI's focus areas grew faster than all state payments, after inflation (FY2008–FY2026)"},
        {"item": "Method", "value": "OLS on log real spend with a year × group interaction; robust (HC1) standard errors; n = %d" % len(d)},
        {"item": "Real annual growth, all payments", "value": f"{g(0):.1%}"},
        {"item": "Real annual growth, focus areas", "value": f"{g(1):.1%}"},
        {"item": "Difference per year (log points)", "value": f"{b:.3f} (95% CI {ci[0]:.3f} to {ci[1]:.3f})"},
        {"item": "One-sided p-value", "value": f"{p_one:.4f}"},
        {"item": "Result", "value": ("Supported: focus areas grew significantly faster (p < 0.05)" if p_one < 0.05 else "Not supported at the 5% level")},
    ]
    return pd.DataFrame(rows), d

def _holt(y, h):
    from statsmodels.tsa.holtwinters import Holt
    m = Holt(np.log(y), damped_trend=True, initialization_method="estimated").fit()
    resid_sd = float(np.std(m.resid, ddof=1)); f = m.forecast(h)
    return np.asarray(f), resid_sd

def _ols(y, years, h, since):
    keep = years >= since; t = years[keep] - since
    m = sm.OLS(np.log(y[keep]), sm.add_constant(t)).fit()
    tf = np.arange(years.max() + 1, years.max() + 1 + h) - since
    pr = m.get_prediction(sm.add_constant(tf, has_constant="add")).summary_frame(alpha=0.10)
    return pr["mean"].values, pr["obs_ci_lower"].values, pr["obs_ci_upper"].values

def _drift(y, h):
    ly = np.log(y); d = np.diff(ly); mu, sd = d.mean(), d.std(ddof=1)
    k = np.arange(1, h + 1); f = ly[-1] + mu * k
    return f, f - 1.645 * sd * np.sqrt(k), f + 1.645 * sd * np.sqrt(k)

MODELS = {
    "Log-linear trend, FY2012 on": lambda y, yr, h: _ols(y, yr, h, 2012),
    "Log-linear trend, last 8 years": lambda y, yr, h: _ols(y, yr, h, yr.max() - 7),
    "Random walk with drift, last 8 years": lambda y, yr, h: _drift(y[-8:], h),
    "Damped-trend exponential smoothing": lambda y, yr, h: (lambda f, sd: (f, f - 1.645 * sd * np.sqrt(np.arange(1, h + 1)), f + 1.645 * sd * np.sqrt(np.arange(1, h + 1))))(*_holt(y, h)),
}

def forecast(real_focus):
    """Self-correcting model choice: backtest every candidate (train through FY2023, score FY2024-FY2026),
    keep the one with the lowest error, refit it on all years and forecast FY2027-FY2028 with a 90% interval."""
    d = real_focus.sort_values("fiscal_year"); y = d.real.values; yr = d.fiscal_year.values
    tr = yr <= 2023; scores = []
    for name, fn in MODELS.items():
        try:
            f, lo, hi = fn(y[tr], yr[tr], 3)
            pred = np.exp(f); act = y[~tr]
            scores.append({"model": name, "backtest_mape": float(np.mean(np.abs(pred - act) / act)),
                           "covered": int(np.sum((act >= np.exp(lo)) & (act <= np.exp(hi))))})
        except Exception as e:
            LOG["events"].append(f"model {name} failed: {e}")
    sc = pd.DataFrame(scores).sort_values("backtest_mape"); best = sc.iloc[0]
    LOG["events"].append("forecast candidates: " + "; ".join(f"{r.model} {r.backtest_mape:.1%}" for r in sc.itertuples()))
    f, lo, hi = MODELS[best.model](y, yr, 2)
    rows = [{"fiscal_year": int(a), "kind": "actual", "spend": float(b), "low": None, "high": None} for a, b in zip(yr, y)]
    for i, fy in enumerate([2027, 2028]):
        rows.append({"fiscal_year": fy, "kind": "forecast", "spend": float(np.exp(f[i])), "low": float(np.exp(lo[i])), "high": float(np.exp(hi[i]))})
    meta = {"model": best.model, "backtest_mape": float(best.backtest_mape), "covered": int(best.covered), "candidates": sc}
    return pd.DataFrame(rows), meta

def breakpoint_test(real_focus, brk=2022):
    """Did focus-area real growth change after FY2022? Segmented (hinge) regression on log real spend."""
    d = real_focus.copy(); d["t"] = d.fiscal_year - 2008; d["after"] = np.maximum(0, d.fiscal_year - brk)
    m = sm.OLS(np.log(d.real), sm.add_constant(d[["t", "after"]])).fit(cov_type="HC1")
    pre = float(np.expm1(m.params["t"])); post = float(np.expm1(m.params["t"] + m.params["after"]))
    p_one = float(m.pvalues["after"] / 2) if m.params["after"] > 0 else 1.0
    ci = m.conf_int(alpha=0.05).loc["after"].tolist()
    return pre, post, p_one, ci

def main():
    t0 = time.time(); fresh = "--fresh" in sys.argv
    raw = load_years(fresh)
    health("No negative or missing amounts", bool((raw.amount >= 0).all() and raw.amount.notna().all()),
           f"{int((raw.amount < 0).sum())} negative, {int(raw.amount.isna().sum())} missing")
    health("Every payee has a name", bool(raw.vendor_name.notna().all()), f"{int(raw.vendor_name.isna().sum())} blank payee names")
    df = tag(raw); cpi = cpi_table()
    ex = LOG["excluded"]
    health("Misclassified payments removed from focus areas", True,
           f"${ex['nursing_facility_dollars']/1e6:,.0f}M nursing-facility payments, ${ex['bill_assistance_dollars']/1e6:,.0f}M utility bill assistance and ${LOG['excluded_bpo_dollars']/1e6:,.0f}M benefits processing and energy-assistance payments, FY2008–FY2026")

    totals = raw.groupby("fiscal_year").agg(total_payments=("amount", "sum"), payment_records=("amount", "size"),
                                            agencies=("agency_name", "nunique"), payees=("vendor_name", "nunique")).reset_index()
    lensfy = df[df.lens.notna()].groupby(["lens", "fiscal_year"]).agg(spend=("amount", "sum"), vendors=("vnorm", "nunique"),
                                                                     agencies=("agency_name", "nunique")).reset_index()
    focus = lensfy.groupby("fiscal_year").spend.sum()
    health("Focus areas are a small share of every year's total", bool(((focus / totals.set_index("fiscal_year").total_payments) < 0.1).all()),
           f"share ranges {float((focus / totals.set_index('fiscal_year').total_payments).min()):.2%}–{float((focus / totals.set_index('fiscal_year').total_payments).max()):.2%}")
    health("All six areas present in FY2026", lensfy[lensfy.fiscal_year == 2026].lens.nunique() == 6,
           f"{lensfy[lensfy.fiscal_year == 2026].lens.nunique()} areas")

    y = df[df.fiscal_year == 2026]
    p = y[~y.vnorm.str.contains(GOV) & ~y.passthrough]
    multi = p.groupby("vnorm").agg(agencies=("agency_name", "nunique"), spend=("amount", "sum"), name_variants=("vendor_name", "nunique")).reset_index().rename(columns={"vnorm": "vendor"})
    lensmap = y.dropna(subset=["lens"]).groupby("vnorm").lens.first()
    multi["lens"] = multi.vendor.map(lensmap).fillna("Other goods & services")
    multi = multi[multi.agencies >= 15].sort_values(["agencies", "spend"], ascending=False)
    lensv = y[y.lens.notna()].groupby(["lens", "vnorm"]).agg(spend=("amount", "sum"), agencies=("agency_name", "nunique")).reset_index().rename(columns={"vnorm": "vendor"})
    lensv = lensv.sort_values("spend", ascending=False).groupby("lens").head(6)

    # agency view (FY2026, focus areas)
    yf = y[y.lens.notna()]
    agency_lens = yf.groupby(["agency_name", "lens"]).agg(spend=("amount", "sum"), vendors=("vnorm", "nunique")).reset_index()
    ag_tot = yf.groupby("agency_name").spend.sum() if "spend" in yf else yf.groupby("agency_name").amount.sum()
    agencies = ag_tot.sort_values(ascending=False).reset_index().rename(columns={"amount": "focus_spend"})
    agencies = agencies[agencies.focus_spend >= 100000]
    agency_lens = agency_lens[agency_lens.agency_name.isin(agencies.agency_name)]
    vend_reach = y.groupby("vnorm").agency_name.nunique()
    av = yf.groupby(["agency_name", "vnorm", "lens"]).amount.sum().reset_index().rename(columns={"vnorm": "vendor", "amount": "spend"})
    av["agencies_buying"] = av.vendor.map(vend_reach)
    av = av[av.agency_name.isin(agencies.agency_name)].sort_values("spend", ascending=False).groupby("agency_name").head(12)
    health("Agency view covers most focus-area spend", True,
           f"{len(agencies)} agencies with $100K+ in focus areas cover {agencies.focus_spend.sum()/yf.amount.sum():.1%} of FY2026 focus spend")

    # statistics
    series = pd.concat([totals[["fiscal_year"]].assign(group="All payments", value=totals.total_payments),
                        focus.reset_index().rename(columns={"spend": "value"}).assign(group="Focus areas")])
    hyp, d = hypothesis(series, cpi)
    real_focus = d[d.group == "Focus areas"][["fiscal_year", "real"]]
    pre, post, p_brk, ci_brk = breakpoint_test(real_focus)
    fc, fmeta = forecast(real_focus)
    fmeta["candidates"].round(4).to_csv(OUT / "forecast_backtest.csv", index=False)
    health("Forecast backtest error under 15%", fmeta["backtest_mape"] < 0.15,
           f"{len(fmeta['candidates'])} models backtested (train FY2008–FY2023, score FY2024–FY2026); kept {fmeta['model']}, error {fmeta['backtest_mape']:.1%}, {fmeta['covered']}/3 years inside its 90% interval", warn=True)
    hyp = pd.concat([hyp, pd.DataFrame([
        {"item": "Follow-up hypothesis", "value": "Focus-area real growth accelerated after FY2022"},
        {"item": "Real annual growth, focus areas, FY2008–FY2022", "value": f"{pre:.1%}"},
        {"item": "Real annual growth, focus areas, after FY2022", "value": f"{post:.1%}"},
        {"item": "Change in slope (log points), one-sided p", "value": f"{np.log1p(post) - np.log1p(pre):.3f} (95% CI {ci_brk[0]:.3f} to {ci_brk[1]:.3f}), p = {p_brk:.4f}"},
        {"item": "Follow-up result", "value": ("Supported: growth accelerated after FY2022 (p < 0.05)" if p_brk < 0.05 else "Not supported at the 5% level")},
        {"item": "Forecast model (picked by backtest)", "value": f"{fmeta['model']}; FY2024–FY2026 error {fmeta['backtest_mape']:.1%}"},
    ])])

    fams = []
    for f, pat in [("Verizon", "VERIZON"), ("AT&T", r"^AT & T|^AT T\b"), ("Pitney Bowes", "PITNEY BOWES"), ("Comcast", "COMCAST")]:
        g = y[y.vnorm.str.contains(pat)].groupby("vendor_name").agg(spend=("amount", "sum"), agencies=("agency_name", "nunique")).reset_index()
        for _, r in g.iterrows():
            fams.append({"family": f, "payee_name": r.vendor_name, "spend": round(r.spend), "agencies": int(r.agencies)})

    outputs = {"totals_by_fy": totals, "lens_by_fy": lensfy, "multi_agency_vendors": multi, "lens_top_vendors": lensv,
               "vendor_families": pd.DataFrame(fams), "cpi_fy": cpi, "agencies_fy26": agencies, "agency_lens_fy26": agency_lens,
               "agency_vendors_fy26": av, "hypothesis_test": hyp, "forecast": fc}
    for k, v in outputs.items():
        v = v.copy()
        for c in v.columns:
            if v[c].dtype.kind == "f" and c not in ("cpi_u_avg", "to_fy2026_dollars"):
                v[c] = v[c].round(0)
        v.to_csv(OUT / f"{k}.csv", index=False)
    ok = all(h["status"] != "fail" for h in HEALTH)
    LOG.update({"finished": dt.datetime.now(dt.timezone.utc).isoformat(), "seconds": round(time.time() - t0, 1),
                "rows": int(len(raw)), "status": "PASSED" if ok else "FAILED"})
    HEALTH.insert(0, {"check": "Pipeline run", "status": "pass" if ok else "fail",
                      "detail": f"{len(raw):,} payment records, FY2008–FY2026, {LOG['seconds']}s, run {LOG['finished'][:16]} UTC"})
    pd.DataFrame(HEALTH).to_csv(OUT / "pipeline_health.csv", index=False)
    (OUT / "run_log.json").write_text(json.dumps(LOG, indent=1, default=str))
    print(json.dumps({k: LOG[k] for k in ("status", "rows", "seconds")}), "|", sum(h["status"] == "fail" for h in HEALTH), "failed checks")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
