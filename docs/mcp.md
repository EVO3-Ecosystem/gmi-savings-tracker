# MCP server: the tracker's data for AI agents

`src/mcp/` is a read-only [Model Context Protocol](https://modelcontextprotocol.io) server over the GMI Savings Tracker
data, built on the official Python SDK (`mcp==2.3.0`, `MCPServer`, the SDK's FastMCP-style API). An agent such as Claude
can list the tables, read their definitions, run SQL, and ask the two common questions (an agency's spending, a vendor's
payments) without a copy of the database, and every answer says which tables and which pipeline run it came from.

Independent prototype by Sierra Napier, built from Maryland's open data; not an official State of Maryland product.

## Run it

```bash
pip install -e ".[mcp]"
python -m src.mcp.server                      # stdio; data/md_transparency.duckdb if present, else the export
python -m src.mcp.server --backend export --export site_data   # the checked-in snapshot only (what a fresh clone has)
```

Data: `data/md_transparency.duckdb` opened **read-only** (all five layers: raw, ref, core, mart, ops) when it exists;
otherwise the exported marts (`data/export/latest`, else the checked-in `site_data/`; Parquet, or the CSVs when there is no
Parquet) loaded into an in-memory DuckDB as schema `mart`. Options: `--db`, `--export`, `--backend auto|duckdb|export`,
`--timeout` (seconds per statement, default 10); the same as environment variables `GMI_MCP_DB`, `GMI_MCP_EXPORT`,
`GMI_MCP_BACKEND`, `GMI_MCP_TIMEOUT`.

### Claude Desktop

Settings > Developer > Edit Config (`claude_desktop_config.json`), with the paths of your clone and its Python:

```json
{
  "mcpServers": {
    "gmi-savings-tracker": {
      "command": "/path/to/gmi-savings-tracker/.venv/bin/python",
      "args": ["-m", "src.mcp.server"],
      "env": {"PYTHONPATH": "/path/to/gmi-savings-tracker"}
    }
  }
}
```

### Claude Code

From the repository root:

```bash
claude mcp add gmi-savings-tracker -- python -m src.mcp.server
```

or check a project-scoped `.mcp.json` into the clone:

```json
{"mcpServers": {"gmi-savings-tracker": {"command": "python", "args": ["-m", "src.mcp.server"]}}}
```

## Tools

| tool | arguments | returns |
|---|---|---|
| `list_tables` | none | every table: name (`layer.table`), layer, rows, one-line description (from `docs/schemas/*.csv`, the `sql/mart` headers and the model descriptions, as on `site/catalog.html`) |
| `describe_table` | `name` (`mart.f_agency` or `f_agency`) | columns with DuckDB types and their definitions from [data-governance.md](data-governance.md) section 11 |
| `query` | `sql`, `limit` (1 to 500, default 100) | `columns`, `rows`, `row_count`, `truncated`; the source tables come from DuckDB's own binder |
| `agency_spending` | `agency` (code such as `R00`, or a name or part of one), `fiscal_year` (optional) | `mart.f_agency` rows: stage, operating spending, controllable purchases, budgeted positions, payments, with definitions |
| `vendor_payments` | `vendor` (name or part of one, any case), `fiscal_year` (optional), `top_agencies` (default 10) | total paid, paid and agencies per year, the agencies that paid most (`mart.f_vendor_pay`) |
| `get_sources` | none | the source datasets: portal id and link, title, portal update date, portal and downloaded row counts, whether they match, and the year-by-year website reconciliation (`docs/reconciliation/summary.csv`); the latest pipeline run and its checks |

Resource: `catalog://tables`, the catalog as markdown (every table with layer, rows and description).

Every result has a `provenance` block:

```json
{"tables": ["mart.f_agency"], "run_id": "20261109T154457Z", "as_of": "2026-11-09", "portal_updated": "2026-10-09",
 "partial_payment_years": [2027], "backend": "duckdb", "source": "data/md_transparency.duckdb", "disclaimer": "..."}
```

`as_of` is the date of the pipeline run, `portal_updated` the latest portal update of any source dataset, and
`partial_payment_years` the payments years that are still partial (the database keeps them; the export holds them back,
so the list is empty on the export backend). Names that match several agencies or vendors are refused with the list of
candidates rather than guessed.

## Guardrails

The server cannot change anything or reach outside its data:

1. **One SELECT.** `query` takes exactly one statement, which DuckDB's parser must type as SELECT and which must start
   with `SELECT` or `WITH` (so no DDL, DML, `ATTACH`, `DETACH`, `COPY`, `EXPORT`, `INSTALL`, `LOAD`, `PRAGMA`, `SET`,
   `CALL`, `EXPLAIN`, or a second statement after a semicolon).
2. **No files, URLs or SQL strings.** In the parsed tree every table reference must be a plain name (a quoted path such as
   `'/etc/passwd'` or `'https://...'` used as a table is refused) and table functions are limited to `range`,
   `generate_series` and `unnest` (no `read_csv`, `read_parquet`, `glob`, `query`, ...). Outside string literals the
   keywords above and file-reading functions are refused again.
3. **A locked connection.** The database file is opened `read_only`; external access is disabled (no file reads, no
   `ATTACH`, no extensions) and the configuration is locked, so even SQL that got past the check could not turn it back
   on (`tests/test_mcp_security.py` runs such statements on the connection directly). On the export backend the tables
   live in memory: the files on disk are never written.
4. **Bounded work.** At most 500 rows per call (`truncated` says when there were more); every statement is interrupted
   after the timeout (10 s by default).

Tests: `tests/test_mcp.py` (30-question golden set in `tests/fixtures/mcp_golden.yaml`, asked through an in-process MCP
client, each answer checked against an independent SQL query run on its own connection against the same files; on the
export snapshot and, when present, the database file) and `tests/test_mcp_security.py` (the statements refused above,
through the check, through the tool and on the bare connection; read-only file; timeout; row limit).

## Example transcript

Produced by `python -m src.mcp.transcript --write --backend export --export site_data`, which starts the stdio server and
calls the tools over MCP (lists cut to three items, `definitions` and `disclaimer` omitted).

<!-- transcript -->
**Call** `get_sources` `{}`

```json
{
 "datasets": [
  {
   "source": "budget",
   "dataset_id": "yu65-jmmv",
   "portal_url": "https://opendata.maryland.gov/d/yu65-jmmv",
   "title": "Maryland Operating Budget",
   "portal_name": "Maryland Operating Budget (current)",
   "use": "Operating budget and actuals by agency, program and Comptroller spending code",
   "years": "FY2017-FY2027",
   "portal_updated": "2026-08-10",
   "rows_portal": 741957,
   "rows_downloaded": 741957,
   "portal_count_matched": true,
   "website_reconciliation": {
    "rows_web": 741957,
    "rows_api": 741957,
    "years": 11,
    "years_differing": 0,
    "status": "matches every year"
   }
  },
  {
   "source": "fte",
   "dataset_id": "x8qy-486w",
   "portal_url": "https://opendata.maryland.gov/d/x8qy-486w",
   "title": "State of Maryland Full Time Equivalents",
   "portal_name": "State of Maryland Full Time Equivalents",
   "use": "Budgeted full-time-equivalent positions by agency and program",
   "years": "FY2017-FY2027",
   "portal_updated": "2026-08-10",
   "rows_portal": 6026,
   "rows_downloaded": 6026,
   "portal_count_matched": true,
   "website_reconciliation": {
    "status": "no website download to compare"
   }
  },
  {
   "source": "fund",
   "dataset_id": "gy87-e27x",
   "portal_url": "https://opendata.maryland.gov/d/gy87-e27x",
   "title": "Maryland Operating Budget - Funding Source",
   "portal_name": "Maryland Operating Budget - Funding Source",
   "use": "Operating budget by fund type and fund source",
   "years": "FY2017-FY2027",
   "portal_updated": "2026-08-10",
   "rows_portal": 26178,
   "rows_downloaded": 26178,
   "portal_count_matched": true,
   "website_reconciliation": {
    "rows_web": 26178,
    "rows_api": 26178,
    "years": 11,
    "years_differing": 0,
    "status": "matches every year"
   }
  },
  "... 3 more"
 ],
 "latest_run": {
  "run_id": "20261109T154457Z",
  "started_utc": "2026-11-09T15:44:57+00:00",
  "status": "passed",
  "checks": 93.0,
  "passed": 92.0,
  "warnings": 1.0,
  "failed": 0.0
 },
 "provenance": {
  "tables": [
   "mart.pipeline_runs",
   "mart.sources"
  ],
  "run_id": "20261109T154457Z",
  "as_of": "2026-11-09",
  "portal_updated": "2026-10-09",
  "partial_payment_years": [],
  "backend": "parquet",
  "source": "site_data",
  "export": "20261109T154457Z"
 }
}
```

**Call** `agency_spending` `{"agency": "Department of Transportation", "fiscal_year": 2025}`

```json
{
 "agency_code": "J00",
 "agency": "Department of Transportation",
 "fiscal_year": 2025,
 "rows": [
  {
   "fiscal_year": 2025,
   "stage": "Actual",
   "operating_spending": 6505039391.0,
   "controllable": 1607501428.0,
   "fte": 10910.5,
   "payments": 4814777405.6
  }
 ],
 "provenance": {
  "tables": [
   "mart.f_agency"
  ],
  "run_id": "20261109T154457Z",
  "as_of": "2026-11-09",
  "portal_updated": "2026-10-09",
  "partial_payment_years": [],
  "backend": "parquet",
  "source": "site_data",
  "export": "20261109T154457Z"
 }
}
```

**Call** `vendor_payments` `{"vendor": "grainger", "fiscal_year": 2025, "top_agencies": 3}`

```json
{
 "vendor": "GRAINGER",
 "fiscal_year": 2025,
 "total_paid": 7068386.41,
 "by_year": [
  {
   "fiscal_year": 2025,
   "paid": 7068386.41,
   "agencies": 16
  }
 ],
 "top_agencies": [
  {
   "agency_code": "J00",
   "agency": "Department of Transportation",
   "paid": 3474452.41
  },
  {
   "agency_code": "Q00",
   "agency": "Department of Public Safety and Correctional Services",
   "paid": 1854448.12
  },
  {
   "agency_code": "V00",
   "agency": "Department of Juvenile Services",
   "paid": 527182.39
  }
 ],
 "note": "Payments to private vendors, merged across payee-name variants, by agency and year (mart.f_vendor_pay); nominal dollars",
 "provenance": {
  "tables": [
   "mart.d_agency",
   "mart.f_vendor_pay"
  ],
  "run_id": "20261109T154457Z",
  "as_of": "2026-11-09",
  "portal_updated": "2026-10-09",
  "partial_payment_years": [],
  "backend": "parquet",
  "source": "site_data",
  "export": "20261109T154457Z"
 }
}
```

**Call** `query` `{"sql": "SELECT fiscal_year, round(total_payments / 1e9, 2) AS payments_billion FROM totals_by_fy WHERE fiscal_year >= 2023 ORDER BY 1", "limit": 10}`

```json
{
 "columns": [
  "fiscal_year",
  "payments_billion"
 ],
 "rows": [
  {
   "fiscal_year": 2023,
   "payments_billion": 39.28
  },
  {
   "fiscal_year": 2024,
   "payments_billion": 40.39
  },
  {
   "fiscal_year": 2025,
   "payments_billion": 43.7
  },
  "... 1 more"
 ],
 "row_count": 4,
 "truncated": false,
 "limit": 10,
 "provenance": {
  "tables": [
   "mart.totals_by_fy"
  ],
  "run_id": "20261109T154457Z",
  "as_of": "2026-11-09",
  "portal_updated": "2026-10-09",
  "partial_payment_years": [],
  "backend": "parquet",
  "source": "site_data",
  "export": "20261109T154457Z"
 }
}
```

**Call** `query` `{"sql": "DROP TABLE mart.f_agency"}`

**Error:** `Error executing tool query: query rejected: only SELECT or WITH queries are allowed (got DROP)`

**Call** `query` `{"sql": "SELECT * FROM read_csv('/etc/passwd')"}`

**Error:** `Error executing tool query: query rejected: table function not allowed: read_csv`

**Call** `agency_spending` `{"agency": "Department"}`

**Error:** `Error executing tool agency_spending: 'Department' matches 27 agencies; use a code: D10 Executive Department - Governor; D12 Department of Disabilities; D15 Executive Department-Boards, Commissions and Offices; D24 Department of Social and Economic Mobility; D26 Department of Aging; D40 Departmen...`
<!-- /transcript -->

## Appendix: publish dry run

<!-- publish-dry-run -->
Recorded Nov 10, 2026 with `python -m src.pipeline.publish --dry-run --src site_data` (no network; exit=0). The same command runs in `.github/workflows/publish_data.yml` before any upload, and staging validates again.

```text
warning: manifest.csv says 23133 rows for f_grants, the Parquet file has 23085 (the export counts CSV lines; a quoted text field contains line breaks); the card uses the file's count
staged 48 Parquet files (2.2 MB), manifest and dataset card in <temporary folder>/hf_stage; validated
run_id=20261109T154457Z
dry run (no network): the publish would do this

Hugging Face dataset: thedatavigilante/maryland-gmi-spending (upload_folder of hf_stage/, replaces parquet/*.parquet)
GitHub Release: tag data-20261109T154457Z, title 'Data export 20261109T154457Z', assets: 48 Parquet files + manifest.csv
```

| file | bytes |
|---|---|
| README.md | 8,815 |
| manifest.csv | 2,140 |
| parquet/agency_master.parquet | 6,286 |
| parquet/d_agency.parquet | 3,522 |
| parquet/d_all_funds.parquet | 5,729 |
| parquet/d_area_top.parquet | 6,657 |
| parquet/d_bid_list.parquet | 7,661 |
| parquet/d_deflator.parquet | 5,280 |
| parquet/d_families.parquet | 23,535 |
| parquet/d_forecast_model.parquet | 8,624 |
| parquet/d_master_quality.parquet | 2,593 |
| parquet/d_multi.parquet | 16,102 |
| parquet/d_multi_basis.parquet | 3,131 |
| parquet/d_opps.parquet | 23,210 |
| parquet/d_payment_screen.parquet | 20,943 |
| parquet/d_payment_screen_summary.parquet | 8,616 |
| parquet/d_plan50.parquet | 7,079 |
| parquet/d_rec_status.parquet | 5,415 |
| parquet/d_savings.parquet | 13,157 |
| parquet/d_savings_status.parquet | 5,871 |
| parquet/d_vendor_moves.parquet | 6,082 |
| parquet/d_vendor_names.parquet | 10,616 |
| parquet/d_vendors.parquet | 173,966 |
| parquet/f_agency.parquet | 24,983 |
| parquet/f_area.parquet | 71,885 |
| parquet/f_budget_vs_pay.parquet | 42,215 |
| parquet/f_code.parquet | 107,641 |
| parquet/f_concentration.parquet | 6,769 |
| parquet/f_forecast.parquet | 6,793 |
| parquet/f_function.parquet | 9,988 |
| parquet/f_fund.parquet | 17,636 |
| parquet/f_fund_source.parquet | 128,510 |
| parquet/f_grants.parquet | 667,211 |
| parquet/f_object.parquet | 89,296 |
| parquet/f_overlap.parquet | 12,945 |
| parquet/f_payee_type.parquet | 64,032 |
| parquet/f_program.parquet | 77,706 |
| parquet/f_savings_check.parquet | 14,623 |
| parquet/f_scope.parquet | 22,042 |
| parquet/f_vendor.parquet | 52,213 |
| parquet/f_vendor_detail.parquet | 58,983 |
| parquet/f_vendor_pay.parquet | 319,253 |
| parquet/f_vendor_year.parquet | 4,986 |
| parquet/measures.parquet | 4,146 |
| parquet/pipeline_runs.parquet | 8,332 |
| parquet/run_checks.parquet | 8,810 |
| parquet/sources.parquet | 8,045 |
| parquet/stage_evidence.parquet | 8,118 |
| parquet/totals_by_fy.parquet | 5,719 |
| parquet/vendor_families.parquet | 5,743 |
| total | 2,223,653 |

The warning is a real finding: `src/pipeline/export.py` writes each file's `rows` in `manifest.csv` as its CSV line count, and line breaks inside `f_grants` text values add 48 lines, so the manifest says 23,133 where the file has 23,085 records. The dataset card now takes row counts from the Parquet files; the export's count is for its owner to fix.
<!-- /publish-dry-run -->
