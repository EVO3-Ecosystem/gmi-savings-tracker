"""Phase 2 checks: written to ops.check_result and data/check_history.csv; any failed "stop" check fails the run.

Severity: stop = the run fails and nothing is exported; warn = reported, never blocks (context sources, drift).
"""
import datetime as dt
from pathlib import Path

import pandas as pd

from ..models import opportunities, savings

HIST = Path(__file__).resolve().parents[2] / "data" / "check_history.csv"
SUM_COL = {"budget": ("core.fact_budget", "budget"), "fund": ("core.fact_fund", "budget"), "fte": ("core.fact_fte", "fte"),
           "payments": ("core.fact_payment", "amount"), "grants": ("core.fact_grant", "amount")}


def run(con, run_id, manifest):
    out = []

    def check(layer, name, ok, detail, severity="stop"):
        out.append({"run_id": run_id, "layer": layer, "check": name, "severity": severity,
                    "result": "pass" if ok else ("fail" if severity == "stop" else "warn"), "detail": detail})

    one = lambda q, *a: con.execute(q, list(a)).fetchone()[0]  # noqa: E731

    # raw: what we loaded is what the portal has
    for d in manifest["datasets"]:
        n = one(f"SELECT count(*) FROM raw.{d['dataset']}")
        check("raw", f"Rows loaded = portal count: {d['dataset']}", n == d["portal_count"], f"{n:,} loaded, {d['portal_count']:,} on the portal")

    # core: yearly totals and row counts tie to the portal's own sums; typing lost nothing
    for ds, (table, col) in SUM_COL.items():
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
    df = pd.DataFrame(out)
    con.execute("CREATE TABLE ops.check_result AS SELECT * FROM df")
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
    prev = HIST.parent / "payee_names.txt"
    now = {r[0] for r in con.execute("SELECT payee FROM ref.map_payee_vendor").fetchall()}
    old = set(prev.read_text().splitlines()) if prev.exists() else set()
    new = sorted(now - old) if old else []
    check("ref", "New payee names since the last build", not new, (f"{len(new)} new: " + "; ".join(new[:8]) + (" ..." if len(new) > 8 else "")) if old else "first build recorded", "warn")
    prev.write_text("\n".join(sorted(now)))
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

