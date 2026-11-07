"""Pipeline facts for the dashboard's Data & pipeline tab, from this pipeline's own records (not the legacy pipeline's).

Builds four dashboard files as mart tables, after the checks have run (two of them describe the checks):
  mart.sources         one row per portal dataset: ID, title, portal update date, rows, years, reconciled
  mart.run_checks      every check of this build (stage = layer: raw, core, ref, mart)
  mart.pipeline_runs   one row per extract run: status, timing, repairs, rows, and the checks of its build
  mart.d_master_quality  how well payments match the agency and vendor master lists

Column order and meaning follow docs/schemas/dashboard_columns.csv. Run history comes from data/runs.csv (extract
runs) and data/check_history.csv (builds), so it spans runs even though the database is rebuilt each time.
"""
import datetime as dt
import json
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]

# Dataset titles and what each contributes (carried over from the legacy sources.py, which the dashboard shows).
SOURCES = {
    "payments": ("State of Maryland Payments Data", "All payments by state agencies to businesses, local governments, non-profits and individuals, by agency and payee, per fiscal year (portal description)"),
    "budget": ("Maryland Operating Budget", "Operating budget and actuals by agency, program and Comptroller spending code"),
    "fund": ("Maryland Operating Budget - Funding Source", "Operating budget by fund type and fund source"),
    "fte": ("State of Maryland Full Time Equivalents", "Budgeted full-time-equivalent positions by agency and program"),
    "grants": ("State of Maryland Grant and Loan Data", "State aid grants (from FY2009) and loans (from FY2010) to for-profit and non-profit entities; the portal says $50,000 or more, but some rows are smaller"),
}
ORDER = ["payments", "budget", "fund", "fte", "grants"]
RUN_COLUMNS = ["run_id", "started_utc", "seconds", "status", "published", "checks", "passed", "warnings", "failed", "repairs",
               "payment_rows", "budget_rows", "mode"]


def _row(con, sql, *a):
    """First row of a query, read fully so the connection has no open result afterwards."""
    rows = con.execute(sql, list(a)).fetchall()
    return rows[0] if rows else None


def sources(con, man):
    cfg = yaml.safe_load((ROOT / "config" / "datasets.yaml").read_text())["datasets"]
    by = {d["dataset"]: d for d in man["datasets"]}
    rows = []
    for key in [k for k in ORDER if k in by]:
        d = by[key]
        lo, hi = _row(con, f"SELECT min(CAST({cfg[key]['year_col']} AS INTEGER)), max(CAST({cfg[key]['year_col']} AS INTEGER)) FROM raw.{key}")
        title, use = SOURCES[key]
        rows.append({"source": key, "dataset_id": d["id"], "title": title, "use": use, "portal_name": title,
                     "portal_updated": str(d.get("rowsUpdatedAt_utc", ""))[:10], "rows_portal": d["portal_count"], "rows_downloaded": d["rows"],
                     "years": f"FY{lo}-FY{hi}", "reconciled": int(bool(d["match"]))})
    return pd.DataFrame(rows)


def run_checks(con, run_id):
    return con.execute("""SELECT run_id, layer AS stage, "check", result AS status, detail FROM ops.check_result ORDER BY
        CASE layer WHEN 'raw' THEN 1 WHEN 'core' THEN 2 WHEN 'ref' THEN 3 WHEN 'mart' THEN 4 ELSE 5 END, rowid""").df().assign(run_id=run_id)


def _started(run_id):
    try:
        return dt.datetime.strptime(run_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return None


def pipeline_runs(data, hist_path):
    runs = pd.read_csv(data / "runs.csv") if (data / "runs.csv").exists() else pd.DataFrame(columns=["run_id"])
    hist = pd.read_csv(hist_path) if Path(hist_path).exists() else pd.DataFrame(columns=["run_id", "result"])
    per = hist.groupby("run_id").result.agg(checks="size", passed=lambda s: (s == "pass").sum(), warnings=lambda s: (s == "warn").sum(),
                                            failed=lambda s: (s == "fail").sum()) if len(hist) else pd.DataFrame()
    out = []
    for r in runs.itertuples():
        c = per.loc[r.run_id] if len(per) and r.run_id in per.index else None
        man = data / "raw" / r.run_id / "manifest.json"
        ds = {d["dataset"]: d["rows"] for d in json.loads(man.read_text())["datasets"]} if man.exists() else {}
        mode = "fresh download" if (r.forced or r.downloaded == 5) else ("freshness reuse" if r.reused == 5 else "incremental")
        out.append({"run_id": r.run_id, "started_utc": _started(r.run_id), "seconds": r.seconds, "status": r.status,
                    "published": int(c is not None and c.failed == 0 and r.status == "passed"),
                    "checks": None if c is None else int(c.checks), "passed": None if c is None else int(c.passed),
                    "warnings": None if c is None else int(c.warnings), "failed": None if c is None else int(c.failed),
                    "repairs": int(r.heals), "payment_rows": ds.get("payments"), "budget_rows": ds.get("budget"), "mode": mode})
    return pd.DataFrame(out, columns=RUN_COLUMNS)  # fixed columns, so an empty history still has the documented shape


def master_quality(con):
    fy = _row(con, "SELECT max(fiscal_year) FROM core.fact_payment WHERE NOT partial_year")[0]
    share = _row(con, "SELECT sum(amount) FILTER (WHERE agency_code IS NOT NULL) / sum(amount) FROM core.fact_payment_mapped WHERE fiscal_year = ?", fy)[0]
    mapped, total = _row(con, "SELECT count(*) FILTER (WHERE agency_code IS NOT NULL), count(*) FROM ref.map_payment_agency")
    unmapped = [r[0] for r in con.execute("SELECT payment_agency_name FROM ref.map_payment_agency WHERE agency_code IS NULL ORDER BY 1").fetchall()]
    names, comps = _row(con, """SELECT count(*), count(DISTINCT vendor) FROM ref.map_payee_vendor
        WHERE vendor IN (SELECT vendor FROM ref.map_payee_vendor GROUP BY vendor HAVING count(*) > 1)""")
    new = _row(con, """SELECT detail FROM ops.check_result WHERE "check" = 'New payee names since the last build'""")
    new = (new[0] if new else "") or ""
    new_value = "first run recorded" if (not new or new.startswith("first build")) else new.split(" new")[0] if " new" in new else new
    rows = [(f"FY{fy} payments matched to a budget agency", f"{share:.2%}", int(share >= .99)),
            ("Payment agency names mapped", f"{mapped:,} of {total:,}", 1),
            ("Payee names grouped into companies", f"{names:,} names in {comps:,} companies" if names else "-", 1),
            ("New payee names since the last run", new_value, 1),
            ("Agency names not yet mapped", (", ".join(unmapped[:6]) + (" ..." if len(unmapped) > 6 else "")) if unmapped else "none", int(len(unmapped) <= 10))]
    return pd.DataFrame(rows, columns=["measure", "value", "ok"])


def build(con, run_id, man, data, hist_path):
    """Create the four tables in the mart schema (call after checks.run, which writes ops.check_result)."""
    tables = {"sources": sources(con, man), "run_checks": run_checks(con, run_id),
              "pipeline_runs": pipeline_runs(Path(data), hist_path), "d_master_quality": master_quality(con)}
    for name, df in tables.items():
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE mart.{name} AS SELECT * FROM _df")
        con.unregister("_df")
    return {k: len(v) for k, v in tables.items()}
