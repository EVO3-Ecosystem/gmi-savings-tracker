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
