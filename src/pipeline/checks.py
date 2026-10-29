"""Phase 2 checks: written to ops.check_result and data/check_history.csv; any failed "stop" check fails the run.

Severity: stop = the run fails and nothing is exported; warn = reported, never blocks (context sources, drift).
"""
import datetime as dt
from pathlib import Path

import pandas as pd

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
