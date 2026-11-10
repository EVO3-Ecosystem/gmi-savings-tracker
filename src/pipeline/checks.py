"""Phase 2 checks: written to ops.check_result and data/check_history.csv; any failed "stop" check fails the run.

Severity: stop = the run fails and nothing is exported; warn = reported, never blocks (context sources, drift).
"""
import datetime as dt
import re
from pathlib import Path

import pandas as pd
import yaml

from ..models import opportunities, recommendations, savings

HIST = Path(__file__).resolve().parents[2] / "data" / "check_history.csv"
SUM_COL = {"budget": ("core.fact_budget", "budget"), "fund": ("core.fact_fund", "budget"), "fte": ("core.fact_fte", "fte"),
           "payments": ("core.fact_payment", "amount"), "grants": ("core.fact_grant", "amount"), "highered": ("core.fact_budget_highered", "budget")}
HIGHER_ED = ("R13", "R14", "R30", "R95")  # agencies of 4mca-332u: kept out of every GMI savings baseline


class _Reads:
    """The connection as the checks see it: records which warehouse tables each check's queries read (ops.check_coverage)."""
    REF = re.compile(r"\b(raw|ref|core|mart|ops)\.([A-Za-z_][A-Za-z0-9_]*)")

    def __init__(self, con):
        self._con, self.seen = con, set()

    def execute(self, q, *a, **k):
        if isinstance(q, str):
            self.seen.update(f"{s}.{t}".lower() for s, t in self.REF.findall(q))
        return self._con.execute(q, *a, **k)

    def __getattr__(self, name):
        return getattr(self._con, name)


def run(con, run_id, manifest):
    out, cover = [], []
    real, con = con, _Reads(con)

    def check(layer, name, ok, detail, severity="stop"):
        out.append({"run_id": run_id, "layer": layer, "check": name, "severity": severity,
                    "result": "pass" if ok else ("fail" if severity == "stop" else "warn"), "detail": detail})
        cover.append({"check": name, "layer": layer, "tables": " ".join(sorted(con.seen))})
        con.seen.clear()

    check.run_id = run_id
    one = lambda q, *a: con.execute(q, list(a)).fetchone()[0]  # noqa: E731

    # raw: what we loaded is what the portal has
    for d in manifest["datasets"]:
        n = one(f"SELECT count(*) FROM raw.{d['dataset']}")
        check("raw", f"Rows loaded = portal count: {d['dataset']}", n == d["portal_count"], f"{n:,} loaded, {d['portal_count']:,} on the portal")

    # core: yearly totals and row counts tie to the portal's own sums; typing lost nothing
    loaded = {d["dataset"] for d in manifest["datasets"]}
    for ds, (table, col) in SUM_COL.items():
        if ds not in loaded:  # an extract run from before the dataset was added
            continue
        g = con.execute(f"""SELECT p.fiscal_year, p.total, p.rows, coalesce(c.t, 0), coalesce(c.n, 0) FROM ops.portal_year_total p
            LEFT JOIN (SELECT fiscal_year, sum({col}) t, count(*) n FROM {table} GROUP BY 1) c USING (fiscal_year) WHERE p.dataset = ?""", [ds]).fetchall()
        gap = max(abs(r[1] - r[3]) for r in g)
        rows_off = sum(r[2] != r[4] for r in g)
        check("core", f"Yearly totals = portal: {ds}", gap < 0.01 and rows_off == 0,
              f"{len(g)} years ({min(r[0] for r in g)}-{max(r[0] for r in g)}); largest gap ${gap:,.2f}; {rows_off} years with a row-count difference")
        nulls = one(f"SELECT count(*) FROM {table} WHERE fiscal_year IS NULL OR {col} IS NULL")
        check("core", f"No missing year or amount: {ds}", nulls == 0, f"{nulls:,} rows")
    gap = one("""SELECT max(abs(b.t - f.t)) FROM (SELECT fiscal_year, sum(budget) t FROM core.fact_budget GROUP BY 1) b
                 JOIN (SELECT fiscal_year, sum(budget) t FROM core.fact_fund GROUP BY 1) f USING (fiscal_year)""")
    check("core", "Budget totals = funding-source totals (within $1)", gap <= 1, f"largest yearly gap ${gap:,.2f}")
    bad = one("SELECT count(*) FROM core.fact_budget WHERE NOT regexp_full_match(object_code, '[0-9]{2}') OR NOT regexp_full_match(program_code, '[0-9]{2}')")
    check("core", "Object and program codes are two digits", bad == 0, f"{bad:,} rows")
    bad, n, units = con.execute("""SELECT count(*) FILTER (WHERE unit_code IS NULL OR program_code IS NULL OR NOT regexp_full_match(program_code, '[0-9]{2}')),
        count(*), count(DISTINCT agency_code || '/' || unit_code || '/' || program_code) FROM core.fact_fund""").fetchone()
    check("core", "Funding-source rows keep their unit and two-digit program", bad == 0, f"{bad:,} of {n:,} rows without both; {units:,} agency-unit-programs")
    spell = one("SELECT count(DISTINCT comptroller_subobject_code) FROM raw.budget")
    codes = one("SELECT count(*) FROM ref.dim_subobject")
    lead = one("SELECT count(*) FROM core.fact_budget WHERE subobject_code LIKE '0%' AND subobject_code <> '0'")
    check("core", "Sub-object codes normalized (no leading zeros)", lead == 0, f"{spell:,} spellings on the portal -> {codes:,} codes")
    suffix = one("SELECT count(*) FROM core.fact_budget WHERE regexp_matches(agency_name, ':[A-Z][0-9]{2}$')")
    check("core", "Agency names carry no code suffix", suffix == 0, f"{suffix:,} rows; {one('SELECT count(*) FROM ref.dim_agency WHERE names_used > 1')} agencies renamed over time")
    multi = one("SELECT count(*) FROM ref.dim_function WHERE codes > 1")
    check("ref", "Functions keyed by title", True, f"{one('SELECT count(*) FROM ref.dim_function')} functions; {multi} titles span more than one code", "warn")
    miss = one("SELECT count(*) FROM (SELECT DISTINCT fiscal_year FROM core.fact_budget) b LEFT JOIN ref.dim_stage s USING (fiscal_year) WHERE s.stage IS NULL")
    stages = ", ".join(f"FY{y} {s}" for y, s in con.execute("SELECT fiscal_year, stage FROM ref.dim_stage WHERE fiscal_year >= 2025 ORDER BY 1").fetchall())
    check("ref", "Every budget year has a confirmed stage", miss == 0, stages)
    py = one("SELECT max(fiscal_year) FROM core.fact_payment")
    check("core", "Latest payments year flagged as partial", one("SELECT bool_and(partial_year) FROM core.fact_payment WHERE fiscal_year = ?", py),
          f"FY{py}: {one('SELECT count(*) FROM core.fact_payment WHERE fiscal_year = ?', py):,} rows, ${one('SELECT sum(amount) FROM core.fact_payment WHERE fiscal_year = ?', py) / 1e9:,.1f}B so far")

    # context sources for the recommendations: reported, never blocking
    tabs = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'core'").fetchall()}
    last_actual = one("SELECT max(fiscal_year) FROM ref.dim_stage WHERE stage = 'Actual'")
    if "cpi_fy" in tabs:
        have = {r[0] for r in con.execute("SELECT fiscal_year FROM core.cpi_fy WHERE months >= 11").fetchall()}
        need = set(range(2017, last_actual + 2))
        check("core", "CPI covers every actual budget year (real dollars)", need <= have,
              f"full fiscal years FY{min(have)}-FY{max(have)}; dollars of FY{one('SELECT max(dollars_of_fy) FROM core.cpi_fy')}", "warn")
    else:
        check("core", "CPI covers every actual budget year (real dollars)", False, "CPI not downloaded this run", "warn")
    if "fact_federal_award" in tabs:
        z = one("SELECT count(*) FROM core.fact_federal_award WHERE NOT reporting_incomplete AND amount <= 0")
        lag = ", ".join(f"FY{r[0]}" for r in con.execute("SELECT federal_fy FROM core.fact_federal_award WHERE reporting_incomplete ORDER BY 1").fetchall())
        check("core", "Federal awards present for every complete year", z == 0, f"still being reported: {lag or 'none'}", "warn")
    if "fact_population" in tabs:
        mx = one("SELECT max(fiscal_year) FROM core.fact_population")
        check("core", "Population covers every actual budget year", mx >= last_actual, f"through FY{mx} (July 1 estimates)", "warn")
    if "mfr_document" in tabs:
        n = one("SELECT count(*) FROM core.mfr_document")
        check("core", "Managing for Results plans downloaded (recommendation 6)", n >= 50, f"{n} agency PDFs, FY{one('SELECT max(fiscal_year) FROM core.mfr_document')}", "warn")
    for src, status, detail in con.execute("SELECT source, status, detail FROM ops.enrichment").fetchall():
        check("raw", f"Context source pulled: {src}", status == "pass", detail[:200], "warn")

    phase3(con, check, one)
    phase4(con, check, one)
    phase5(con, check, one)
    phase5_opportunities(con, check, one)
    phase5_savings(con, check, one)
    phase5_recommendations(con, check, one)
    phase5_reference_marts(con, check, one)
    phase5_higher_education(con, check, one, "highered" in loaded)
    phase5_deflator(con, check, one)
    phase5_payment_screen(con, check, one)
    con = real
    df = pd.DataFrame(out)
    while hasattr(con, "_con"):  # the DuckDB connection itself (build.py may pass a recording wrapper): replacement scans look in this frame
        con = con._con
    con.execute("CREATE TABLE ops.check_result AS SELECT * FROM df")
    cov = pd.DataFrame(cover, columns=["check", "layer", "tables"])  # noqa: F841 - read by the next statement
    con.execute("CREATE TABLE ops.check_coverage AS SELECT * FROM cov")
    fails = int((df.result == "fail").sum())
    con.execute("CREATE TABLE ops.run_log (run_id TEXT, built_utc TEXT, checks INTEGER, passed INTEGER, warnings INTEGER, failed INTEGER)")
    con.execute("INSERT INTO ops.run_log VALUES (?,?,?,?,?,?)", [run_id, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), len(df),
                int((df.result == "pass").sum()), int((df.result == "warn").sum()), fails])
    hist = pd.read_csv(HIST) if HIST.exists() else pd.DataFrame()
    pd.concat([hist[hist.get("run_id", pd.Series(dtype=str)) != run_id] if len(hist) else hist, df], ignore_index=True).to_csv(HIST, index=False)
    for r in out:
        print(f"{r['result']:4s}  [{r['layer']}] {r['check']}: {r['detail']}")
    print(f"{len(df)} checks: {int((df.result == 'pass').sum())} passed, {int((df.result == 'warn').sum())} warnings, {fails} failed")
    return fails == 0


def phase3(con, check, one):
    """Reference data: match rates at or above the dashboard pipeline's (reference/baseline_quality.csv)."""
    if not one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'ref' AND table_name = 'map_payment_agency'"):
        return
    base = dict(con.execute("SELECT measure, CAST(value AS DOUBLE) FROM ref.baseline_quality").fetchall())
    fy = one("SELECT max(fiscal_year) FROM core.fact_payment WHERE NOT partial_year")
    share = one("SELECT sum(amount) FILTER (WHERE agency_code IS NOT NULL) / sum(amount) FROM core.fact_payment_mapped WHERE fiscal_year = ?", fy)
    check("ref", f"FY{fy} payment dollars matched to a budget agency", share >= base["fy2026_payment_dollars_matched"] - 1e-9,
          f"{share:.4%} (dashboard: {base['fy2026_payment_dollars_matched']:.2%})")
    partial = one("SELECT max(fiscal_year) FROM core.fact_payment")
    ps = one("SELECT sum(amount) FILTER (WHERE agency_code IS NOT NULL) / sum(amount) FROM core.fact_payment_mapped WHERE fiscal_year = ?", partial)
    check("ref", f"FY{partial} (partial year) payment dollars matched", ps >= 0.99, f"{ps:.4%}", "warn")
    mapped, total = one("SELECT count(*) FILTER (WHERE agency_code IS NOT NULL) FROM ref.map_payment_agency"), one("SELECT count(*) FROM ref.map_payment_agency")
    un = [r[0] for r in con.execute("SELECT payment_agency_name FROM ref.map_payment_agency WHERE agency_code IS NULL ORDER BY 1").fetchall()]
    check("ref", "Payment agency names mapped", mapped >= base["payment_agency_names_mapped"],
          f"{mapped} of {total} (dashboard: {int(base['payment_agency_names_mapped'])} of 145); unmapped: {', '.join(un) or 'none'}")
    names, comps = con.execute("""SELECT count(*), count(DISTINCT vendor) FROM ref.map_payee_vendor
        WHERE vendor IN (SELECT vendor FROM ref.map_payee_vendor GROUP BY vendor HAVING count(*) > 1)""").fetchone()
    check("ref", "Payee names grouped into companies", names >= base["payee_names_grouped"],
          f"{names:,} names in {comps:,} companies (dashboard, FY2026 payees only: {int(base['payee_names_grouped']):,} in {int(base['companies_with_several_names']):,})")
    c25 = one("SELECT sum(budget) FROM core.fact_budget_scope WHERE fiscal_year = 2025 AND controllable")
    check("ref", "Controllable purchases FY2025 = dashboard", abs(c25 - base["controllable_fy2025"]) < 1, f"${c25:,.0f} (dashboard ${base['controllable_fy2025']:,.0f})")
    a25 = one("SELECT sum(budget) FROM core.fact_budget_scope WHERE fiscal_year = 2025 AND focus_area IS NOT NULL")
    codes = one("SELECT count(DISTINCT subobject_code) FROM ref.map_focus_area")
    check("ref", "Focus areas FY2025 = dashboard", abs(a25 - base["focus_area_fy2025"]) < 1 and codes >= base["focus_area_codes"],
          f"${a25:,.0f} in {codes} spending codes (dashboard ${base['focus_area_fy2025']:,.0f} in {int(base['focus_area_codes'])})")
    miss = one("SELECT count(*) FROM ref.map_focus_area m LEFT JOIN ref.dim_subobject s USING (subobject_code) WHERE s.subobject_code IS NULL")
    check("ref", "Every focus-area code exists in the budget", miss == 0, f"{miss} missing")
    # New payee names, against the history kept by passing builds only (data/payee_name_seen.csv; written by record_payees)
    seen = read_payee_history(HIST.parent)
    now = {r[0] for r in con.execute("SELECT payee FROM ref.map_payee_vendor").fetchall()}
    new, baseline = new_payee_names(now, seen, check.run_id)
    _payee_table(con, seen)
    check("ref", "New payee names since the last build", not new,
          "first build recorded" if baseline else (f"{len(new)} new since the last passing build: " + "; ".join(new[:8]) + (" ..." if len(new) > 8 else "")
                                                     if new else "0 new since the last passing build"), "warn")
    if one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = 'mfr_measure'"):
        docs, matched = con.execute("SELECT count(*), count(agency_code) FROM ref.map_mfr_agency").fetchone()
        n, ag = con.execute("SELECT count(DISTINCT agency_file || measure), count(DISTINCT agency_file) FROM core.mfr_measure").fetchone()
        check("ref", "Managing for Results measures read from the plans (recommendation 6)", ag >= 0.8 * docs,
              f"{n:,} measures from {ag} of {docs} plans; {matched} plans matched to a budget agency", "warn")


def phase4(con, check, one):
    """Marts: every roll-up ties back to its core total; every vendor and agency is classified."""
    if not one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'agency_rollup'"):
        return
    bad = con.execute("""SELECT count(*) FROM (SELECT fiscal_year, sum(amount) s FROM core.fact_payment GROUP BY 1) c
        FULL JOIN (SELECT fiscal_year, sum(paid) s FROM mart.vendor_agency_year GROUP BY 1) m USING (fiscal_year)
        WHERE abs(coalesce(c.s, 0) - coalesce(m.s, 0)) > 1""").fetchone()[0]
    check("mart", "Vendor payments by year = core payments (every year, to the dollar)", bad == 0, f"{bad} years differ")
    bad = con.execute("""SELECT count(*) FROM (SELECT fiscal_year, sum(budget) s FROM core.fact_budget GROUP BY 1) c
        FULL JOIN (SELECT fiscal_year, sum(budget) s FROM mart.agency_rollup GROUP BY 1) m USING (fiscal_year)
        WHERE abs(coalesce(c.s, 0) - coalesce(m.s, 0)) > 1""").fetchone()[0]
    check("mart", "Agency roll-up budget by year = core budget (every year, to the dollar)", bad == 0, f"{bad} years differ")
    d = one("SELECT count(*) - count(DISTINCT vendor) FROM mart.vendor_master")
    n = one("SELECT count(*) FROM mart.vendor_master")
    m = one("SELECT count(DISTINCT vendor) FROM mart.vendor_agency_year")
    check("mart", "One vendor master row per vendor paid", d == 0 and n == m, f"{n:,} vendors, {d} duplicates, {m:,} in payments")
    low = one("SELECT count(*) FROM mart.agency_function WHERE function_share < 0.99")
    check("mart", "Each agency's budget sits in one function (no allocation needed)", low == 0, f"{low} agency-years below 99%", "warn")
    nf = one("SELECT sum(paid) FILTER (WHERE agency_code IS NOT NULL AND function_name IS NULL) FROM mart.vendor_agency_year") or 0
    check("mart", "Every mapped payment rolls up to a function or a named exception", nf < 1, f"${nf:,.0f} without a function")
    stale = [r[0] for r in con.execute("SELECT agency_code FROM ref.function_exceptions WHERE agency_code IN (SELECT DISTINCT agency_code FROM core.fact_budget)").fetchall()]
    check("mart", "Function exceptions are not in the operating budget", not stale, f"now in the budget: {', '.join(stale)}" if stale else "none are")
    ex = con.execute("""SELECT x.function_name, sum(v.paid) FROM mart.vendor_agency_year v JOIN ref.function_exceptions x USING (agency_code)
        WHERE v.fiscal_year = (SELECT max(fiscal_year) FROM core.fact_payment WHERE NOT partial_year) GROUP BY 1 ORDER BY 1""").fetchall()
    check("mart", "Payments outside the operating budget data (latest full year)", True, "; ".join(f"{k}: ${v / 1e9:,.2f}B" for k, v in ex) or "none", "warn")
    types = dict(con.execute("SELECT payee_type, sum(paid_all_years) FROM mart.vendor_master GROUP BY 1").fetchall())
    tot = sum(types.values())
    check("mart", "Every vendor has a payee type", one("SELECT count(*) FROM mart.vendor_master WHERE payee_type IS NULL") == 0,
          "; ".join(f"{k} {v / tot:.1%}" for k, v in sorted(types.items())) + " of all payment dollars")
    if one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'd_vendors'"):
        bad = one("""SELECT count(*) FROM (SELECT vendor, sum(paid) FILTER (WHERE fiscal_year = 2026) s FROM mart.f_vendor_pay GROUP BY 1) f
            JOIN mart.d_vendors d USING (vendor) WHERE abs(coalesce(f.s, 0) - d.fy2026) > 1""")
        check("mart", "Vendors tab: vendor pages add up to the vendor list (FY2026)", bad == 0, f"{bad} vendors differ; {one('SELECT count(*) FROM mart.d_vendors'):,} vendors listed")
        bad = one("""SELECT count(*) FROM (SELECT fiscal_year, sum(amount) s FROM core.fact_payment GROUP BY 1) c
            FULL JOIN (SELECT fiscal_year, sum(paid) s FROM mart.f_payee_type GROUP BY 1) m USING (fiscal_year) WHERE abs(coalesce(c.s, 0) - coalesce(m.s, 0)) > 1""")
        check("mart", "Vendors tab: payments by payee type = core payments (every year)", bad == 0, f"{bad} years differ")
    if one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'd_multi'"):
        bad = one("SELECT count(*) FROM mart.d_multi WHERE agencies < 15")
        check("mart", "Vendors tab: every multi-agency vendor is paid by 15+ agencies", bad == 0, f"{bad} below 15; {one('SELECT count(*) FROM mart.d_multi WHERE fiscal_year = 2026')} in FY2026")
        bad = one("""SELECT count(*) FROM mart.f_concentration WHERE top5_share > 1.000001 OR top5_share <= 0 OR hhi < 0 OR hhi > 10000
            OR hhi < 10000.0 / vendors - 1""")  # HHI can't be below 10,000/n (equal shares)
        check("mart", "Vendors tab: concentration shares and HHI within bounds", bad == 0, f"{bad} area-years out of bounds")
        bad = one("""SELECT count(*) FROM (SELECT fiscal_year, area, sum(amount) s FROM mart.v_purchase WHERE area <> 'Other goods & services' GROUP BY ALL HAVING sum(amount) > 0) v
            FULL JOIN mart.f_concentration c USING (fiscal_year, area) WHERE abs(coalesce(v.s, 0) - coalesce(c.spend, 0)) > 1""")
        check("mart", "Vendors tab: concentration spend = private focus-area payments (every area and year)", bad == 0, f"{bad} differ")
        bad = one("SELECT count(*) FROM (SELECT fiscal_year, family FROM mart.d_families GROUP BY ALL HAVING count(DISTINCT payee_name) < 2)")
        check("mart", "Vendors tab: every company listed has two or more payee names", bad == 0, f"{bad} with one name")
        k = dict(con.execute("SELECT basis, vendors FROM mart.d_multi_basis WHERE fiscal_year = 2026").fetchall())
        check("mart", "Vendors tab: 15+ agency count on both bases (FY2026)", k.get("company and budget agency") == one("SELECT count(*) FROM mart.d_multi WHERE fiscal_year = 2026"),
              "; ".join(f"{b}: {v}" for b, v in sorted(k.items())) + " (the Maryland Spend Lens showed 54 on the payee-name basis)", "warn")
    if one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'f_overlap'"):
        bad = one("""SELECT count(*) FROM (SELECT fiscal_year, sum(amount) s, count(*) n FROM core.fact_grant GROUP BY 1) c
            FULL JOIN (SELECT fiscal_year, sum(amount) s, count(*) n FROM mart.f_grants GROUP BY 1) m USING (fiscal_year)
            WHERE abs(coalesce(c.s, 0) - coalesce(m.s, 0)) > 1 OR c.n IS DISTINCT FROM m.n""")
        check("mart", "Grants as listed = core grants (rows and dollars, every year)", bad == 0, f"{bad} years differ")
        bad = one("""SELECT count(*) FROM (SELECT fiscal_year, sum(budget) b FROM core.fact_budget GROUP BY 1) c
            FULL JOIN (SELECT fiscal_year, sum(budget) b, sum(payments) p FROM mart.f_budget_vs_pay GROUP BY 1) m USING (fiscal_year)
            LEFT JOIN (SELECT fiscal_year, sum(amount) p FROM core.fact_payment WHERE fiscal_year >= 2017 GROUP BY 1) q USING (fiscal_year)
            WHERE abs(coalesce(c.b, 0) - coalesce(m.b, 0)) > 1 OR abs(coalesce(q.p, 0) - coalesce(m.p, 0)) > 1""")
        check("mart", "Budget vs payments: budget and payments = core totals (every year)", bad == 0, f"{bad} years differ")
        bad = one("""SELECT count(*) FROM (SELECT fiscal_year, sum(budget) b FROM mart.f_program GROUP BY 1) a
            FULL JOIN (SELECT fiscal_year, sum(budget) b FROM mart.f_fund_source GROUP BY 1) f USING (fiscal_year) WHERE abs(coalesce(a.b, 0) - coalesce(f.b, 0)) > 1""")
        check("mart", "Where it's going = how it's funded (budget by program = budget by fund source, every year)", bad == 0, f"{bad} years differ")
        lo = one("SELECT min(grants_in_payments_share) FROM mart.f_overlap WHERE grants_and_loans > 0") or 0
        check("mart", "Grants whose grantee is also a payee that year (name match)", True, f"lowest year {lo:.0%} of grant dollars; grants are shown as part of payments, never added", "warn")
    r, m = one("SELECT count(*) FROM mart.agency_results"), one("SELECT count(*) FROM core.mfr_measure WHERE agency_code IS NOT NULL")
    check("mart", "Agency results rows = matched Managing for Results rows", r == m, f"{r:,} of {m:,}")


def phase5(con, check, one):
    """Forecasts: structurally sound, tied to the budget, and the chosen model is not worse than the naive baseline."""
    if not one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'f_forecast'"):
        return
    bad = one("SELECT count(*) FROM mart.f_forecast WHERE kind = 'Forecast' AND NOT (p10 <= p50 AND p50 <= p90)")
    check("mart", "Forecast ranges are ordered (p10 <= p50 <= p90)", bad == 0, f"{bad} forecast rows out of order")
    gap = one("""SELECT coalesce(max(abs(a.v - s.b)), 0) FROM (SELECT fiscal_year, sum(value) v FROM mart.f_forecast WHERE kind = 'Actual' GROUP BY 1) a
        JOIN (SELECT fiscal_year, sum(budget) b FROM mart.f_scope WHERE scope = 'Controllable purchases' AND stage = 'Actual' GROUP BY 1) s USING (fiscal_year)""")
    base = one("""SELECT coalesce(max(abs(m.baseline_fy2025 - f.value)), 0) FROM mart.d_forecast_model m
        JOIN mart.f_forecast f ON f.area = m.area AND f.kind = 'Actual' AND f.fiscal_year = 2025""")
    check("mart", "Forecast actuals add up to controllable purchases (every actual year)", gap <= 10 and base <= 1,
          f"largest yearly gap ${gap:,.0f} (rows are rounded to the dollar); FY2025 baseline gap ${base:,.0f}")
    short = one("""SELECT count(*) FROM (SELECT area, count(*) FILTER (WHERE kind = 'Actual') a, count(*) FILTER (WHERE kind = 'Forecast') f
        FROM mart.f_forecast GROUP BY 1) WHERE a < 9 OR f < 6""")
    n = one("SELECT count(*) FROM mart.d_forecast_model")
    check("mart", "Every forecast area has nine actual years and six forecast years", short == 0 and n >= 7, f"{n} areas; {short} short")
    unordered = one("SELECT count(*) FROM mart.d_forecast_backtest WHERE NOT (p10 <= p50 AND p50 <= p90)")
    check("mart", "Backtest ranges are ordered (p10 <= p50 <= p90)", unordered == 0, f"{unordered} backtest rows out of order")
    unplanned = one("""SELECT count(*) FROM (SELECT area FROM mart.d_forecast_backtest WHERE target = 'plan' GROUP BY area
        HAVING count(DISTINCT forecast_fy) < 2)""") + one("SELECT count(*) FROM mart.d_forecast_model WHERE area NOT IN (SELECT area FROM mart.d_forecast_backtest WHERE target = 'plan')")
    check("mart", "Every forecast area is also scored against the State's plan for FY2026 and FY2027", unplanned == 0, f"{unplanned} areas without both plan years")
    cov = con.execute("SELECT covered_share, scored, nominal, widen_by FROM mart.d_forecast_calibration WHERE area = 'All areas'").fetchone()
    if cov:
        share, scored, nominal, widen = cov
        check("mart", "Published forecast ranges cover about their nominal share on the rolling backtest", abs(share - nominal) <= 0.10,
              f"{share:.1%} of {scored} forecasts of actual spending fell inside the p10-p90 range (nominal {nominal:.0%}); "
              f"about {widen:.2f}x wider ranges would have been needed (in-sample, a handful of points)", "warn")
    worse = con.execute("""SELECT m.area, avg(b.mase) FILTER (WHERE b.method = m.method) AS chosen, avg(b.mase) FILTER (WHERE b.method = 'Naive (last actual)') AS naive
        FROM mart.d_forecast_model m JOIN mart.d_forecast_backtest b USING (area) WHERE b.target = 'actual' GROUP BY m.area, m.method
        HAVING avg(b.mase) FILTER (WHERE b.method = m.method) > avg(b.mase) FILTER (WHERE b.method = 'Naive (last actual)') + 1e-9""").fetchall()
    check("mart", "Chosen forecast model is no worse than the naive baseline in the rolling-origin backtest", not worse,
          "; ".join(f"{a}: MASE {c:.2f} vs naive {nv:.2f}" for a, c, nv in worse) if worse else "every area's chosen model matches or beats naive (mean MASE over FY2021-FY2024 origins, scored against actuals)", "warn")


def phase5_opportunities(con, check, one):
    """Opportunity detectors: well-formed findings, a bid list that obeys its thresholds, and a warning when one detector's
    total leans on findings that look like re-coding (growth of 1,000% or more)."""
    if not one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'd_opps'"):
        return
    bad = one("SELECT count(*) FROM mart.d_opps WHERE low < 0 OR high < low OR likely IS NULL OR baseline < 0")
    dup_ids = one("SELECT count(*) - count(DISTINCT opp_id) FROM mart.d_opps")
    dup_codes = one("""SELECT count(*) FROM (SELECT agency_code, spending_code FROM mart.d_opps WHERE agency_code IS NOT NULL
        GROUP BY ALL HAVING count(*) > 1)""")
    check("mart", "Opportunity findings are well formed (low <= high, no duplicate id, one finding per agency and spending code)",
          bad == 0 and dup_ids == 0 and dup_codes == 0, f"{bad} malformed, {dup_ids} duplicate ids, {dup_codes} repeated agency and code")
    cfg = opportunities.assumptions()["bid_list"]
    off = one("SELECT count(*) FROM mart.d_bid_list WHERE agencies < ? OR fy2026 < ?", cfg["min_agencies"], cfg["min_spend"])
    ranks = one("SELECT count(*) FROM mart.d_bid_list WHERE rank <> (SELECT count(*) FROM mart.d_bid_list b WHERE b.fy2026 > mart.d_bid_list.fy2026) + 1")
    check("mart", "Bid list vendors meet the agency and spend thresholds and are ranked by FY2026 payments", off == 0 and ranks == 0,
          f"{off} vendors below the thresholds, {ranks} ranks out of order")
    row = con.execute("""SELECT coalesce(sum(likely) FILTER (WHERE TRY_CAST(regexp_extract(evidence, 'grew ([+-]?[0-9]+)%', 1) AS DOUBLE) >= 1000), 0),
          coalesce(sum(likely), 0) FROM mart.d_opps WHERE detector = 'Growth above trend'""").fetchone()
    share = row[0] / row[1] if row[1] else 0
    check("mart", "Growth detector does not lean on findings that grew 1,000% or more (likely re-coding)", share <= 0.25,
          f"${row[0] / 1e6:,.1f}M of the growth detector's ${row[1] / 1e6:,.1f}M likely saving ({share:.0%}) comes from findings that grew 1,000% or more; "
          "a minimum prior-year base (assumptions.yaml, opportunities.growth.min_base_budget) removes most of them", "warn")
    if one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'd_detector_backtest'"):
        n, bad, flagged = con.execute("""SELECT count(*), count(*) FILTER (WHERE flagged_next > units OR units_zero_next > units OR units < 0),
            count(*) FILTER (WHERE cohort = 'Flagged' AND units > 0) FROM mart.d_detector_backtest""").fetchone()
        rates = "; ".join(f"{d} {r:.0%}" for d, r in con.execute("""SELECT detector, sum(flagged_next) / nullif(sum(units), 0) FROM mart.d_detector_backtest
            WHERE cohort = 'Flagged' GROUP BY 1 ORDER BY 1""").fetchall() if r is not None)
        check("mart", "Detector backtest: every detector, as-of year and cohort present and well formed", n == 24 and bad == 0,
              f"{n} rows, {bad} malformed, {flagged} flagged cohorts with units; flags recurring next year (pooled FY2022-FY2024): {rates}")


def phase5_savings(con, check, one):
    """GMI's reported savings and their payment checks: every item cited, every check backed by payments, a status for each."""
    if not one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'd_savings'"):
        return
    n, ids, cited, ordered = con.execute("""SELECT count(*), count(DISTINCT saving_id), count(*) FILTER (WHERE trim(source_quote) <> '' AND trim(source_page) <> ''),
        count(*) FILTER (WHERE reported_low > reported_high) FROM mart.d_savings""").fetchone()
    check("mart", "Every reported savings item is unique, cites a page and a quote, and has low <= high", n == ids == cited and ordered == 0,
          f"{n} items, {ids} distinct, {cited} with a page and quote, {ordered} with low above high")
    missing = one("""SELECT count(DISTINCT check_id) FROM mart.d_savings WHERE check_id IS NOT NULL
        AND check_id NOT IN (SELECT check_id FROM mart.f_savings_check)""")
    named = one("SELECT count(*) FROM mart.d_savings_status WHERE check_id IN ('S02', 'S03', 'S04', 'S05')")
    check("mart", "Every payment check matches payments, and the four named contract types are checked", missing == 0 and named == 4,
          f"{missing} checks with no matching payments; {named} of 4 named contract types in the status table")
    st = con.execute("SELECT status, count(*) FROM mart.d_savings_status WHERE reported IS NOT NULL GROUP BY 1").fetchall()
    quantified = sum(c for _, c in st)
    by = {s: c for s, c in st}
    bad = one("SELECT count(*) FROM mart.d_savings_status WHERE status IS NULL OR status NOT IN ('Seen', 'Partly seen', 'Not seen yet', 'Payments fell', 'Payments did not fall')")
    check("mart", "Every payment check has a status", bad == 0 and one("SELECT count(*) FROM mart.d_savings_status") > 0,
          f"{by.get('Seen', 0)} Seen, {by.get('Partly seen', 0)} Partly seen, {by.get('Not seen yet', 0)} Not seen yet among {quantified} checks with a reported saving "
          "(payments fell by half the reported saving or more = Seen); the rest show only whether payments fell")
    cfg = savings.assumptions()["vendor_moves"]
    off = one("SELECT count(*) FROM mart.d_vendor_moves WHERE change > 0 OR agencies < ? OR fy2025 < ?", cfg["min_agencies"], cfg["min_before"])
    check("mart", "Vendor moves are decreases by vendors paid by enough agencies, largest first", off == 0 and one("SELECT count(*) FROM mart.d_vendor_moves") <= cfg["top"],
          f"{off} rows that are not decreases or fall below the thresholds")


def phase5_recommendations(con, check, one):
    """The six recommendations: all present, a path to $50M that adds up and agrees with its status, vendor drill-downs that tie to
    their payee names, and a warning when too much of the path rests on assumed rates."""
    if not one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'd_rec_status'"):
        return
    cfg = recommendations.assumptions()
    n, distinct, blank = con.execute("""SELECT count(*), count(DISTINCT rec), count(*) FILTER (WHERE status IS NULL OR progress IS NULL OR trim(progress) = '')
        FROM mart.d_rec_status""").fetchone()
    check("mart", "All six recommendations have a status and a key number", n == 6 and distinct == 6 and blank == 0, f"{n} rows, {distinct} distinct, {blank} blank")
    steps, lo, hi, drift, top = con.execute("""SELECT count(*), min(step), max(step),
        (SELECT count(*) FROM (SELECT cumulative, sum(saving) OVER (ORDER BY step) AS c FROM mart.d_plan50) WHERE abs(cumulative - c) > 1),
        max(cumulative) FROM mart.d_plan50""").fetchone()
    reached = top >= cfg["target_saving"]
    says = one("SELECT status FROM mart.d_rec_status WHERE rec = 4") == "Plan reaches $50M"
    check("mart", "The path to $50M is numbered, adds up, and agrees with recommendation 4's status", lo == 1 and hi == steps and drift == 0 and reached == says,
          f"{steps} steps to ${top / 1e6:,.1f}M a year; running total off in {drift} steps; status says {'reaches' if says else 'gap'}, total {'reaches' if reached else 'falls short'}")
    ties = one("""SELECT count(*) FROM (SELECT vendor, sum(fy2026) s FROM mart.d_vendor_names GROUP BY 1) a
        JOIN (SELECT vendor, sum(paid) p FROM mart.f_vendor_detail WHERE fiscal_year = ? GROUP BY 1) b USING (vendor) WHERE abs(a.s - b.p) > 10""",
               cfg["vendor_detail"]["names_fy"])
    missing = one("SELECT count(*) FROM mart.d_bid_list WHERE vendor NOT IN (SELECT vendor FROM mart.f_vendor_detail)")
    check("mart", "Vendor drill-downs tie to their payee names, and every bid-list vendor has one", ties == 0 and missing == 0,
          f"{ties} vendors whose payee names do not add up to their payments; {missing} bid-list vendors without a drill-down")
    share = one("SELECT coalesce(sum(saving) FILTER (WHERE step > 1) / nullif(sum(saving), 0), 0) FROM mart.d_plan50")
    check("mart", "Most of the path to $50M does not rest on assumed saving rates", share <= 0.5,
          f"{share:.0%} of the path (${(top or 0) * share / 1e6:,.1f}M) is assumed savings on statewide contracts and fallback areas; the rest carries forward savings GMI reported", "warn")


def phase5_reference_marts(con, check, one):
    """The measures catalog describes exactly the year-over-year columns the marts have, and the stage evidence agrees with the
    confirmed stages and with the database's own totals."""
    if not one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'measures'"):
        return
    missing = one("""SELECT count(*) FROM mart.measures m WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = 'mart' AND c.table_name = m."table" AND c.column_name = m.measure)""")
    undescribed = one("""SELECT count(*) FROM information_schema.columns c WHERE c.table_schema = 'mart' AND c.column_name LIKE '%\\_yoy' ESCAPE '\\'
        AND NOT EXISTS (SELECT 1 FROM mart.measures m WHERE m."table" = c.table_name AND m.measure = c.column_name)""")
    bad = one("SELECT count(*) FROM mart.measures WHERE higher_is NOT IN ('lower', 'neutral')")
    n = one("SELECT count(*) FROM mart.measures")
    check("mart", "The measures catalog describes exactly the year-over-year columns of the marts", missing == 0 and undescribed == 0 and bad == 0 and n > 0,
          f"{n} measures; {missing} described but absent, {undescribed} year-over-year columns undescribed, {bad} with an unknown higher_is")
    cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "assumptions.yaml").read_text())["stage_evidence"]
    off = one("SELECT count(*) FROM mart.stage_evidence e LEFT JOIN ref.dim_stage s USING (fiscal_year) WHERE s.stage IS NULL OR e.official_stage <> s.stage")
    whole = one("""SELECT count(*) FROM mart.stage_evidence e JOIN (SELECT fiscal_year, sum(budget) t FROM core.fact_budget GROUP BY 1) b USING (fiscal_year)
        WHERE e.programs_compared IS NULL AND abs(e.file_total - b.t) > 1""")
    weak = one("SELECT count(*) FROM mart.stage_evidence WHERE programs_compared IS NOT NULL AND programs_exact / programs_compared <= ?", cfg["min_exact_share"])
    check("mart", "Stage evidence agrees with the confirmed stages, with the database's whole-year totals, and with DBM's printed actuals", off == 0 and whole == 0 and weak == 0,
          f"{off} rows whose official stage differs from ref.budget_stage; {whole} whole-file totals that differ from the database; "
          f"{weak} program comparisons with {cfg['min_exact_share']:.0%} or fewer matching exactly")
    unevidenced = one("""SELECT count(*) FROM (SELECT fiscal_year, any_value(portal_type) pt FROM core.fact_budget GROUP BY 1) p JOIN ref.dim_stage s USING (fiscal_year)
        WHERE NOT ((s.stage = 'Actual' AND p.pt LIKE '%Actual') OR (s.stage = 'Working budget' AND p.pt LIKE '%Working'))
        AND p.fiscal_year NOT IN (SELECT fiscal_year FROM mart.stage_evidence)""")
    check("mart", "Every year whose portal stage label differs from the confirmed stage has evidence", unevidenced == 0,
          f"{unevidenced} years where the portal's label and the confirmed stage differ but no evidence is recorded")


def phase5_higher_education(con, check, one, loaded):
    """Public higher education (4mca-332u): disjoint from the operating budget dataset, added only in the labeled all-funds
    figure, and kept out of every GMI savings baseline."""
    if not loaded or not one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'd_all_funds'"):
        return
    codes = ", ".join(f"'{c}'" for c in HIGHER_ED)
    have = [r[0] for r in con.execute("SELECT DISTINCT agency_code FROM core.fact_budget_highered ORDER BY 1").fetchall()]
    overlap = one(f"SELECT count(*) FROM core.fact_budget WHERE agency_code IN ({codes})")
    other = [c for c in have if c not in HIGHER_ED]
    check("core", "Higher education dataset holds only its four agencies, none of them in the operating budget dataset", overlap == 0 and not other and have,
          f"agencies {', '.join(have)}; {overlap} operating-budget rows for them; {len(other)} unexpected agencies")
    bad = one("""SELECT count(*) FROM mart.d_all_funds a
        FULL JOIN (SELECT fiscal_year, sum(budget) b FROM core.fact_budget GROUP BY 1) o USING (fiscal_year)
        LEFT JOIN (SELECT fiscal_year, sum(budget) h FROM core.fact_budget_highered GROUP BY 1) h USING (fiscal_year)
        WHERE abs(coalesce(a.operating_budget, 0) - coalesce(o.b, 0)) > 1 OR abs(coalesce(a.public_higher_education, 0) - coalesce(h.h, 0)) > 1
           OR abs(a.all_funds_including_higher_education - coalesce(o.b, 0) - coalesce(h.h, 0)) > 1""")
    fy = one("SELECT max(fiscal_year) FROM ref.dim_stage WHERE stage = 'Working budget'")
    row = con.execute("SELECT public_higher_education, all_funds_including_higher_education FROM mart.d_all_funds WHERE fiscal_year = ?", [fy]).fetchone()
    check("mart", "All-funds total including public higher education = operating budget + higher education (every year, to the dollar)", bad == 0,
          f"{bad} years differ; FY{fy}: ${(row[0] or 0) / 1e9:,.2f}B higher education, ${row[1] / 1e9:,.2f}B all funds including it" if row else f"{bad} years differ")
    scope = one(f"SELECT count(*) FROM core.fact_budget_scope WHERE agency_code IN ({codes})")
    opps = one(f"SELECT count(*) FROM mart.d_opps WHERE agency_code IN ({codes})")
    cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "assumptions.yaml").read_text())
    excl = set(cfg.get("gmi_baseline_exclusions", {}).get("agency_codes", []))
    moves = set(cfg["savings"]["vendor_moves"]["excluded_agency_codes"])
    paid = one(f"""SELECT coalesce(sum(amount), 0) FROM mart.payment_area WHERE agency_code IN ({codes})
        AND fiscal_year = {int(cfg['opportunities']['payments_fy'])} AND NOT is_government AND NOT passthrough""")
    check("mart", "Public higher education is kept out of every GMI savings baseline", scope == 0 and opps == 0 and set(HIGHER_ED) <= excl and set(HIGHER_ED) <= moves,
          f"{scope} budget-scope rows and {opps} opportunity findings for {', '.join(HIGHER_ED)}; the payment detectors, bid list and vendor moves leave out "
          f"${paid / 1e6:,.1f}M of FY{cfg['opportunities']['payments_fy']} private payments by these agencies")


def phase5_deflator(con, check, one):
    """Real and per-resident dollars: FY2026 is the base year, every actual budget year has a factor; population where published."""
    if not one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'd_deflator'"):
        return
    base = con.execute("SELECT CAST(factor AS DOUBLE) FROM mart.d_deflator WHERE fiscal_year = 2026").fetchone()
    miss = one("""SELECT count(*) FROM (SELECT DISTINCT fiscal_year FROM ref.dim_stage WHERE fiscal_year <= 2026) s
        LEFT JOIN mart.d_deflator d USING (fiscal_year) WHERE d.factor IS NULL OR d.cpi_months < 11 OR CAST(d.factor AS DOUBLE) <= 0""")
    lo, hi = con.execute("SELECT min(fiscal_year), max(fiscal_year) FROM mart.d_deflator WHERE population IS NOT NULL").fetchone()
    f17 = one("SELECT CAST(factor AS DOUBLE) FROM mart.d_deflator WHERE fiscal_year = 2017")
    check("mart", "Deflator: FY2026 = 1 and every budget year through FY2026 has a full-year CPI factor", bool(base) and abs(base[0] - 1) < 1e-9 and miss == 0,
          f"{miss} years missing or partial; FY2017 dollars x {f17:.4f} = FY2026 dollars; population FY{lo}-FY{hi}" if f17 else f"{miss} years missing or partial")
    bad = one("SELECT count(*) FROM mart.d_deflator WHERE population IS NOT NULL AND population <= 0")
    gap = one("""SELECT count(*) FROM (SELECT DISTINCT fiscal_year FROM ref.dim_stage WHERE stage = 'Actual') s
        LEFT JOIN mart.d_deflator d USING (fiscal_year) WHERE d.population IS NULL""")
    check("mart", "Deflator: population for every actual budget year", bad == 0 and gap == 0, f"{gap} actual years without population; {bad} non-positive", "warn")


def phase5_payment_screen(con, check, one):
    """Duplicate and split payment screen (sql/mart/47-49): leads well formed, never double-counted, summary ties, yearly backtest."""
    if not one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'd_payment_screen'"):
        return
    cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "assumptions.yaml").read_text())["payment_screen"]
    rows, keys, small = con.execute("""SELECT count(*), count(DISTINCT record_key),
        (SELECT count(*) FROM (SELECT group_id FROM mart.v_payment_screen_rows GROUP BY 1 HAVING count(*) < 2 OR count(DISTINCT rule) > 1))
        FROM mart.v_payment_screen_rows""").fetchone()
    neg = one("""SELECT count(*) FROM mart.d_payment_screen WHERE n < 2 OR total_amount < 0 OR review_amount < 0 OR review_amount > total_amount + 0.005
                 OR (rule <> 'Possible split purchase' AND (amount < ? OR abs(amount * n - total_amount) > 0.01))""", cfg["min_amount"])
    neg += one("SELECT count(*) FROM mart.d_payment_screen_summary WHERE groups < 0 OR records < 0 OR total_amount < 0 OR review_amount < 0")
    check("mart", "Payment screen: counts and dollars non-negative, every record in exactly one group of one rule",
          rows == keys and small == 0 and neg == 0,
          f"{rows:,} records in {one('SELECT count(*) FROM mart.d_payment_screen'):,} groups; {rows - keys} records in two groups; {small} malformed groups; {neg} negative or inconsistent rows")
    unl = one("""SELECT count(*) FROM mart.d_payment_screen a JOIN mart.d_payment_screen b ON a.agency = b.agency AND a.fiscal_year = b.fiscal_year
                 AND a.rule <> b.rule AND a.vendor = b.vendor AND a.vendor NOT LIKE 'Payee not named%' WHERE a.also_flagged_under IS NULL""")
    tie = one("""SELECT count(*) FROM mart.d_payment_screen_summary s LEFT JOIN (SELECT rule, fiscal_year, count(*) g, sum(n) r, sum(total_amount) t, sum(review_amount) v
                 FROM mart.d_payment_screen GROUP BY ALL) d USING (rule, fiscal_year)
                 WHERE s.groups <> coalesce(d.g, 0) OR s.records <> coalesce(d.r, 0) OR abs(s.total_amount - coalesce(d.t, 0)) > 0.01 OR abs(s.review_amount - coalesce(d.v, 0)) > 0.01""")
    orphan = one("SELECT count(*) FROM mart.d_payment_screen d LEFT JOIN mart.d_payment_screen_summary s USING (rule, fiscal_year) WHERE s.rule IS NULL")
    bad_type = one("SELECT count(*) FROM mart.v_payment_screen_rows WHERE payee_type IN (SELECT unnest(?::VARCHAR[]))", cfg["excluded_payee_types"])
    check("mart", "Payment screen: summary ties to the groups by rule and year; overlap between rules labeled; excluded payee types absent",
          tie == 0 and orphan == 0 and unl == 0 and bad_type == 0,
          f"{tie} summary rows that do not tie; {orphan} groups outside the summary; {unl} overlapping groups without a label; {bad_type} records of an excluded payee type")
    yrs = con.execute("""SELECT fiscal_year, sum(groups), sum(review_amount) FROM mart.d_payment_screen_summary WHERE status = 'Measured'
                         GROUP BY 1 ORDER BY 1""").fetchall()
    st = dict(con.execute("SELECT rule, any_value(status) FROM mart.d_payment_screen_summary GROUP BY 1").fetchall())
    want = set(range(cfg["first_fy"], cfg["last_fy"] + 1))
    check("mart", f"Payment screen backtest: every screened year FY{cfg['first_fy']}-FY{cfg['last_fy']} and rule reported (stability)",
          {r[0] for r in yrs} == want and one("SELECT count(*) FROM mart.d_payment_screen_summary") == 3 * len(want),
          "groups (review $) by year: " + "; ".join(f"FY{y} {int(g)} (${v / 1e6:,.2f}M)" for y, g, v in yrs)
          + f"; split rule: {st.get('Possible split purchase', 'missing')}", "warn")


# ---- New-payee-name history (ops.payee_name_seen). Only a build whose stop checks all pass writes it (build.py calls
# record_payees after checks.run returns True), so a failed build leaves no trace, and a rerun of the same extract run
# updates last_seen in place: one row per payee name, never a duplicate. "New" = not seen by a passing build of an
# earlier extract run, so an identical rerun reports the same names as its first passing build did, and none extra.
PAYEE_HISTORY = "payee_name_seen.csv"
PAYEE_COLUMNS = ["payee_name", "first_seen_run_id", "first_seen_date", "last_seen_run_id", "last_seen_date"]


def _run_date(run_id):
    try:
        return dt.datetime.strptime(run_id, "%Y%m%dT%H%M%SZ").date().isoformat()
    except ValueError:
        return None


def read_payee_history(data):
    f = Path(data) / PAYEE_HISTORY
    return pd.read_csv(f, dtype=str, keep_default_na=False) if f.exists() else pd.DataFrame(columns=PAYEE_COLUMNS)


def new_payee_names(now, seen, run_id):
    """(sorted new names, baseline) for this build. baseline is True when no passing build of an earlier extract run is
    recorded yet: the first build records every name and reports none as new."""
    earlier = seen[seen.first_seen_run_id != run_id]
    if earlier.empty:
        return [], True
    return sorted(set(now) - set(earlier.payee_name)), False


def update_payee_history(seen, now, run_id):
    """History after a passing build of run_id that saw the names `now` (pure; no file access)."""
    day = _run_date(run_id)
    h = seen.copy()
    hit = h.payee_name.isin(now)
    h.loc[hit, "last_seen_run_id"] = run_id
    h.loc[hit, "last_seen_date"] = day
    add = sorted(set(now) - set(h.payee_name))
    h = pd.concat([h, pd.DataFrame({"payee_name": add, "first_seen_run_id": run_id, "first_seen_date": day,
                                    "last_seen_run_id": run_id, "last_seen_date": day}, columns=PAYEE_COLUMNS)], ignore_index=True)
    return h.sort_values("payee_name", kind="stable").reset_index(drop=True)[PAYEE_COLUMNS]


def _payee_table(con, hist):
    con.execute("CREATE SCHEMA IF NOT EXISTS ops")
    con.execute("CREATE OR REPLACE TABLE ops.payee_name_seen (" + ", ".join(f"{c} VARCHAR" for c in PAYEE_COLUMNS) + ")")
    if len(hist):
        con.register("_ph", hist[PAYEE_COLUMNS].astype(str))
        con.execute("INSERT INTO ops.payee_name_seen SELECT * FROM _ph")
        con.unregister("_ph")


def record_payees(con, run_id, data):
    """Call only for a build that passed its stop checks: add new names, move last_seen, write the file and the table."""
    now = {r[0] for r in con.execute("SELECT payee FROM ref.map_payee_vendor").fetchall()}
    hist = update_payee_history(read_payee_history(data), now, run_id)
    Path(data).mkdir(parents=True, exist_ok=True)
    hist.to_csv(Path(data) / PAYEE_HISTORY, index=False)
    _payee_table(con, hist)
    return len(hist)

from . import checks_ml  # noqa: E402,F401 - ML layer checks (sizes, labels, evaluation metrics); registers itself
