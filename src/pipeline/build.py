"""Phase 2 — Database: data/raw/<run_id>/ -> data/md_transparency.duckdb (layers raw, ref, core, ops; mart in Phase 4).

Rebuilt from scratch on every run (seconds). raw is never edited: fixes happen in core or in reference CSVs.
Then src/pipeline/checks.py runs every check, writes ops.check_result and exits non-zero if a "stop" check fails.

Usage: python -m src.pipeline.build [run_id]   (default: the latest passed extract run)
"""
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

from ..models import forecast, opportunities, recommendations, savings
from . import checks, facts, marts, reference

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DB = DATA / "md_transparency.duckdb"


def latest_run():
    r = pd.read_csv(DATA / "runs.csv")
    return str(r[r.status == "passed"].run_id.iloc[-1])


def build(run_id):
    raw = DATA / "raw" / run_id
    man = json.loads((raw / "manifest.json").read_text())
    tmp = DB.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    for s in ("raw", "ref", "core", "mart", "ops"):
        con.execute(f"CREATE SCHEMA {s}")

    # ---- raw: portal rows exactly as delivered, plus the run ID; and the context sources
    for d in man["datasets"]:
        con.execute(f"CREATE TABLE raw.{d['dataset']} AS SELECT *, '{run_id}' AS _run_id FROM read_parquet('{raw}/{d['dataset']}.parquet')")
    for name in ("cpi", "federal_awards", "population", "mfr_index"):
        if (raw / f"{name}.parquet").exists():
            con.execute(f"CREATE TABLE raw.{name} AS SELECT *, '{run_id}' AS _run_id FROM read_parquet('{raw}/{name}.parquet')")

    # ---- ops: what the portal reported for this run
    con.execute("""CREATE TABLE ops.source_snapshot (run_id TEXT, dataset TEXT, dataset_id TEXT, rows_downloaded BIGINT, portal_count BIGINT,
                   rows_updated_at BIGINT, source TEXT, heal_attempts INTEGER)""")
    con.execute("CREATE TABLE ops.portal_year_total (run_id TEXT, dataset TEXT, fiscal_year INTEGER, total DOUBLE, rows BIGINT)")
    for d in man["datasets"]:
        con.execute("INSERT INTO ops.source_snapshot VALUES (?,?,?,?,?,?,?,?)",
                    [run_id, d["dataset"], d["id"], d["rows"], d["portal_count"], d["rowsUpdatedAt"], d["source"], d["heal_attempts"]])
        for t in d["portal_totals"]:
            con.execute("INSERT INTO ops.portal_year_total VALUES (?,?,?,?,?)", [run_id, d["dataset"], t["fiscal_year"], t["total"], t["rows"]])
    con.execute("CREATE TABLE ops.enrichment (run_id TEXT, source TEXT, status TEXT, rows BIGINT, detail TEXT)")
    for e in man.get("enrichment", []):
        con.execute("INSERT INTO ops.enrichment VALUES (?,?,?,?,?)", [run_id, e["source"], e["status"], e["rows"], e["detail"]])

    # ---- core: typed, codes normalized (object/program codes two digits, sub-object codes without leading zeros,
    #      agency names without the ":A15"-style suffix, functions keyed by title)
    pad = lambda c, n: f"lpad(trim(CAST({c} AS VARCHAR)), {n}, '0')"  # noqa: E731
    con.execute(f"""CREATE TABLE core.fact_budget AS SELECT
        CAST(fiscal_year AS INTEGER) AS fiscal_year, trim(agency_code) AS agency_code,
        regexp_replace(trim(agency_name), ':[A-Z][0-9]{{2}}$', '') AS agency_name,
        trim(unit_code) AS unit_code, trim(unit_name) AS unit_name, {pad('program_code', 2)} AS program_code, trim(program_name) AS program_name,
        trim(subprogram_code) AS subprogram_code, trim(subprogram_name) AS subprogram_name,
        {pad('object_code', 2)} AS object_code, trim(object_name) AS object_name,
        coalesce(nullif(ltrim(trim(comptroller_subobject_code), '0'), ''), '0') AS subobject_code, trim(comptroller_subobject_name) AS subobject_name,
        trim(fund_type_name) AS fund_type, trim(type) AS portal_type,
        CAST(category AS INTEGER) AS function_code, trim(category_title) AS function_name,
        trim(organization_code) AS organization_code, CAST(budget AS DOUBLE) AS budget
      FROM raw.budget""")
    # Public higher education (4mca-332u): the same layout as yu65-jmmv for agencies that dataset leaves out. Kept in its own
    # table so no existing figure or GMI savings baseline reads it; core.fact_budget_all_funds is the labeled union.
    if "highered" in _tables(con, "raw"):
        con.execute(f"""CREATE TABLE core.fact_budget_highered AS SELECT
            CAST(fiscal_year AS INTEGER) AS fiscal_year, trim(agency_code) AS agency_code,
            regexp_replace(trim(agency_name), ':[A-Z][0-9]{{2}}$', '') AS agency_name,
            trim(unit_code) AS unit_code, trim(unit_name) AS unit_name, {pad('program_code', 2)} AS program_code, trim(program_name) AS program_name,
            {pad('object_code', 2)} AS object_code, trim(object_name) AS object_name,
            coalesce(nullif(ltrim(trim(comptroller_subobject_code), '0'), ''), '0') AS subobject_code, trim(comptroller_subobject_name) AS subobject_name,
            trim(fund_type_name) AS fund_type, CAST(category AS INTEGER) AS function_code, trim(category_title) AS function_name,
            CAST(budget AS DOUBLE) AS budget, '4mca-332u' AS source_dataset
          FROM raw.highered""")
    else:  # an extract run from before the dataset was added: an empty table of the same shape
        con.execute("""CREATE TABLE core.fact_budget_highered (fiscal_year INTEGER, agency_code VARCHAR, agency_name VARCHAR, unit_code VARCHAR,
            unit_name VARCHAR, program_code VARCHAR, program_name VARCHAR, object_code VARCHAR, object_name VARCHAR, subobject_code VARCHAR,
            subobject_name VARCHAR, fund_type VARCHAR, function_code INTEGER, function_name VARCHAR, budget DOUBLE, source_dataset VARCHAR)""")
    con.execute("""CREATE TABLE core.fact_budget_all_funds AS
      SELECT fiscal_year, agency_code, agency_name, unit_code, unit_name, program_code, program_name, object_code, object_name,
             subobject_code, subobject_name, fund_type, function_code, function_name, budget, 'yu65-jmmv' AS source_dataset FROM core.fact_budget
      UNION ALL
      SELECT fiscal_year, agency_code, agency_name, unit_code, unit_name, program_code, program_name, object_code, object_name,
             subobject_code, subobject_name, fund_type, function_code, function_name, budget, source_dataset FROM core.fact_budget_highered""")
    con.execute("""CREATE TABLE core.fact_fund AS SELECT CAST(fiscal_year AS INTEGER) AS fiscal_year, trim(agency_code) AS agency_code,
        trim(fund_type_name) AS fund_type, trim(fund_source_code) AS fund_source_code, trim(fund_source_name) AS fund_source_name,
        CAST(budget AS DOUBLE) AS budget FROM raw.fund""")
    con.execute(f"""CREATE TABLE core.fact_fte AS SELECT CAST(fiscal_year AS INTEGER) AS fiscal_year, trim(agency_code) AS agency_code,
        trim(unit_code) AS unit_code, {pad('program_code', 2)} AS program_code, trim(organization_code) AS organization_code,
        CAST("count" AS DOUBLE) AS fte FROM raw.fte""")
    con.execute("""CREATE TABLE core.fact_payment AS SELECT CAST(fiscal_year AS INTEGER) AS fiscal_year,
        regexp_replace(trim(agency_name), ':[A-Z][0-9]{2}$', '') AS agency_name_as_paid, trim(vendor_name) AS vendor_name_as_paid,
        trim(vendor_zip) AS vendor_zip, trim(category) AS agency_code_as_paid, CAST(amount AS DOUBLE) AS amount,
        CAST(fiscal_year AS INTEGER) = (SELECT max(CAST(fiscal_year AS INTEGER)) FROM raw.payments) AS partial_year
      FROM raw.payments""")
    con.execute("""CREATE TABLE core.fact_grant AS SELECT CAST(fiscalyear AS INTEGER) AS fiscal_year, trim(grantor) AS grantor, trim(grantee) AS grantee,
        CASE upper(trim(category)) WHEN 'L' THEN 'Loan' WHEN 'LOAN' THEN 'Loan' WHEN 'G' THEN 'Grant' WHEN 'GRANT' THEN 'Grant' ELSE trim(category) END AS category,
        upper(trim(nonprofit)) AS nonprofit, CAST(amount AS DOUBLE) AS amount,
        trim(description) AS description, trim(zipcode) AS zipcode FROM raw.grants""")

    # ---- ref: dimensions derived from the portal (hand-kept reference CSVs arrive in Phase 3)
    con.execute("""CREATE TABLE ref.dim_agency AS SELECT agency_code, arg_max(agency_name, fiscal_year) AS agency_name,
        count(DISTINCT agency_name) AS names_used, min(fiscal_year) AS first_fy, max(fiscal_year) AS last_fy
      FROM core.fact_budget GROUP BY agency_code""")
    con.execute("""CREATE TABLE ref.dim_function AS SELECT function_name, min(function_code) AS min_code, max(function_code) AS max_code,
        count(DISTINCT function_code) AS codes FROM core.fact_budget GROUP BY function_name""")
    con.execute("CREATE TABLE ref.dim_object AS SELECT object_code, arg_max(object_name, fiscal_year) AS object_name FROM core.fact_budget GROUP BY object_code")
    con.execute("""CREATE TABLE ref.dim_subobject AS SELECT subobject_code, arg_max(subobject_name, fiscal_year) AS subobject_name,
        arg_max(object_code, fiscal_year) AS object_code FROM core.fact_budget GROUP BY subobject_code""")
    con.execute("CREATE TABLE ref.dim_fund_type AS SELECT DISTINCT fund_type FROM core.fact_budget")
    # Budget stages follow mtp.maryland.gov; the portal's own type column is out of date
    con.execute("""CREATE TABLE ref.dim_stage AS SELECT fiscal_year, any_value(portal_type) AS portal_type,
        CASE WHEN fiscal_year <= 2025 THEN 'Actual' WHEN fiscal_year = 2026 THEN 'Working budget' ELSE 'Legislative appropriation' END AS stage
      FROM core.fact_budget GROUP BY fiscal_year""")

    # ---- core: context sources for the recommendations
    if "cpi" in _tables(con, "raw"):
        # Maryland fiscal year runs July-June: FY2025 = Jul 2024 - Jun 2025. Deflator = latest complete FY's average / that FY's average.
        con.execute("""CREATE TABLE core.cpi_fy AS WITH m AS (SELECT CASE WHEN month >= 7 THEN year + 1 ELSE year END AS fiscal_year, cpi FROM raw.cpi)
          SELECT fiscal_year, avg(cpi) AS cpi_avg, count(*) AS months FROM m GROUP BY fiscal_year""")
        con.execute("""CREATE OR REPLACE TABLE core.cpi_fy AS SELECT *, (SELECT cpi_avg FROM core.cpi_fy WHERE months >= 11 ORDER BY fiscal_year DESC LIMIT 1) / cpi_avg AS to_latest_dollars,
          (SELECT max(fiscal_year) FROM core.cpi_fy WHERE months >= 11) AS dollars_of_fy FROM core.cpi_fy""")
    if "federal_awards" in _tables(con, "raw"):
        con.execute("""CREATE TABLE core.fact_federal_award AS SELECT federal_fy, amount, partial, reporting_incomplete,
          'USAspending: federal grants (types 02-05) to government recipients located in Maryland' AS definition FROM raw.federal_awards""")
    if "population" in _tables(con, "raw"):
        con.execute("CREATE TABLE core.fact_population AS SELECT year AS calendar_year, year + 1 AS fiscal_year, population, vintage FROM raw.population")
    if "mfr_index" in _tables(con, "raw"):
        con.execute("""CREATE TABLE core.mfr_document AS SELECT fiscal_year, agency_file,
          replace(replace(agency_file, '-MFR.pdf', ''), '-', ' ') AS agency_title, url, bytes, last_modified FROM raw.mfr_index""")

    reference.build(con, raw)  # Phase 3: reference CSVs -> ref layer, mapped payments, budget scope, MFR measures
    marts.build(con)  # Phase 4: sql/mart/*.sql -> mart layer
    forecast.write(con)  # Phase 5: forecasts and their rolling-origin backtest, built on the marts
    opportunities.write(con)  # Phase 5: opportunity detectors and the bid list
    savings.write(con, run_id, DATA)  # Phase 5: GMI's reported savings checked against payments
    recommendations.write(con, run_id, DATA)  # Phase 5: the six recommendations, the path to $50M, vendor drill-downs
    res = checks.run(con, run_id, man)
    facts.build(con, run_id, man, DATA, checks.HIST)  # Data & pipeline tab: sources, runs, checks, master-list quality
    if res:
        savings.record(con, run_id, DATA)  # status history only for a build that passed its checks
        recommendations.record(con, run_id, DATA)
        checks.record_payees(con, run_id, DATA)  # payee-name history (ops.payee_name_seen), likewise
    con.close()
    if res:
        tmp.replace(DB)  # only a database that passes every stop check replaces the last good one
    else:
        failed = DB.with_name("md_transparency.failed.duckdb")
        tmp.replace(failed)
        print(f"FAILED: kept the last good database; this build is in {failed} for inspection")
    return res


def _tables(con, schema):
    return {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = ?", [schema]).fetchall()}


if __name__ == "__main__":
    rid = sys.argv[1] if len(sys.argv) > 1 else latest_run()
    sys.exit(0 if build(rid) else 1)
