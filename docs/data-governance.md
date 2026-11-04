# Data governance — GMI Savings Tracker

<!-- gen:stamp -->
_Generated 2026-11-04T13:52Z by `python -m src.pipeline.governance`. Source schemas from the Discovery API, read Nov 04, 2026._
<!-- /gen:stamp -->

The rules for where the tracker's data comes from, what every column means, who can change what, and how every figure is backed by a source. The schema sections are rebuilt from the sources on every run (`python -m src.pipeline.governance`), so they can't fall out of date. The policy sections are written by hand.

**Contents:** 1 Scope and roles · 2 Source registry · 3 Known source issues · 4 Lineage · 5 Quality controls · 6 Reference data change control · 7 Citations · 8 Assumptions register · 9 Privacy, licence and security · 10 Retention and versioning · 11 Schemas (sources, warehouse, dashboard) · 12 Coverage and drift

## 1. Scope and roles

Covers every dataset the pipeline reads, every table it builds (DuckDB layers `raw`, `ref`, `core`, `mart`, `ops`), and every file the dashboard publishes.

| Role | Who | Responsibility |
|---|---|---|
| Data owner (source) | Maryland Department of Budget and Management (DBM) | Publishes budget, funding, positions, payments and grants data |
| Source maintainer | Maryland Department of Information Technology (DoIT) | Uploads and maintains the portal datasets (portal metadata) |
| Data steward | Sierra Napier (repo owner, `@EVO3-Ecosystem` in CODEOWNERS) | Approves reference-data changes, assumptions and citations; resolves pending decisions |
| Pipeline | `src/pipeline/*` and the GitHub Actions workflow | Extracts, builds, checks, documents; blocks publishing on a failed stop check |

The tracker is an independent prototype, not an official State of Maryland product.

## 2. Source registry

Portal datasets (from the Discovery API; owner, licence and dates are the portal's own metadata):

<!-- gen:registry -->
| dataset | id | portal title | publisher | maintained by | licence | update frequency | period (portal) | data updated | columns |
|---|---|---|---|---|---|---|---|---|---|
| budget | [yu65-jmmv](https://opendata.maryland.gov/d/yu65-jmmv) | Maryland Operating Budget (current) | Maryland Department of Budget Management | Maryland Department of Information Technology | Public Domain | Annually | FY2017-FY2027 | 2026-08-10 | 23 |
| fte | [x8qy-486w](https://opendata.maryland.gov/d/x8qy-486w) | State of Maryland Full Time Equivalents | Maryland Department of Budget Management | Maryland Department of Information Technology | Public Domain | Annually | FY2017 - FY2026 | 2026-08-10 | 9 |
| fund | [gy87-e27x](https://opendata.maryland.gov/d/gy87-e27x) | Maryland Operating Budget - Funding Source | Maryland Department of Budget Management | Maryland Department of Information Technology | Public Domain | Annually | FY2017 - FY2026 | 2026-08-10 | 15 |
| grants | [absk-avps](https://opendata.maryland.gov/d/absk-avps) | State of Maryland Grant and Loan Data: FY2009 to FY2025 | Maryland Department of Budget and Management | Maryland Department of Information Technology | Public Domain | Annually | July 1, 2009 - June 30, 2024 | 2026-10-09 | 10 |
| payments | [7syw-q4cy](https://opendata.maryland.gov/d/7syw-q4cy) | State of Maryland Payments Data: FY2008 to FY2024 | Department of Budget and Management (DBM) | Maryland Department of Information Technology | Public Domain | Monthly | July 1, 2007 - present | 2026-10-07 | 8 |
<!-- /gen:registry -->

Context and evidence sources:

| Source | Used for | Access | Fallback |
|---|---|---|---|
| BLS CPI-U, series CUUR0000SA0 | Inflation adjustment | BLS API v2 (`BLS_API_KEY`) | FRED CPIAUCNS |
| USAspending.gov, spending by geography | Federal grants to Maryland governments (award types 02–05) | Public API | Warn and continue |
| U.S. Census Bureau, Population Estimates (NST-EST CSV files) | Per-resident figures | www2.census.gov | Warn and continue |
| DBM Managing for Results plans, FY2027 (111 PDFs) | Performance measures | dbm.maryland.gov, paced with Retry-After | Previous run's copies |
| DBM, Government Modernization Initiative Final Report (JCR p. 77), Jan 26, 2026 | Reported savings, contract types, fee basis | https://governor.maryland.gov/media/893 | DLS library copy |
| DGS, Government Modernization announcement | $326.3M facility cost avoidance (undated) | https://dgs.maryland.gov/Pages/Announcements/GovernmentModernization.aspx | — |
| WYPR, Jan 10, 2025 | $50M target; fee terms (20% of savings, up to $15M) | https://www.wypr.org/wypr-news/2025-01-10/gov-moore-announces-plan-to-save-50m-by-modernizing-maryland-government | — |

## 3. Known source issues

Each issue was checked against the portal's own metadata or the data on Nov 2, 2026, and is handled in code.

| Dataset | Issue | Evidence | Handling |
|---|---|---|---|
| All five | The portal gives no column descriptions | Every `columns_description` is empty in the Discovery API | Definitions in `reference/column_dictionary.csv` (section 11) |
| Payments (7syw-q4cy) | Title says "FY2008 to FY2024"; data runs through FY2027 | Portal title vs downloaded years | Years read from the data, not the title |
| Payments | Includes individuals, not only businesses | Portal description: "private businesses, local governments, non-profit organizations, and individuals" | See section 9 |
| Payments | No minimum amount (an earlier version of the dashboard said "$25,000 or more", which was wrong) | 5,122 of 23,221 FY2025 payments are under $25,000; smallest is $0.33 | Description corrected Nov 2, 2026 |
| Payments | `date` and `fiscal_period` are placeholders | Values repeat the fiscal-year end | Not used |
| Payments | Agency names, not codes | Schema has `agency_name` only | `ref.map_payment_agency` (rules + decisions) |
| Payments | Latest year is partial | Monthly updates (portal metadata) | `partial_year` flag |
| Grants (absk-avps) | Description says "$50,000 or more", but smaller rows exist | 1,726 of 23,085 rows are under $50,000 | Description corrected; no filter applied |
| Budget (yu65-jmmv) | `type` (stage) column is out of date | Compared with DBM budget books | `ref.budget_stage` from mtp.maryland.gov and the budget books |
| Funding source (gy87-e27x), FTE (x8qy-486w) | Descriptions still say FY2026 is the Governor's Allowance; data runs to FY2027 | Portal description vs data | Same stage table as the budget |
| Budget | Code spellings vary ("0930"/"930", "1"/"01"); function codes 10–12 have more than one title; A15's name carries ":A15" in FY2026–FY2027 | Phase 2 checks | Normalized in `core` |
| All five | 50,000-row pages drop without an app token | Phase 1 runs | 20,000-row pages, retries, self-healing re-download |

## 4. Lineage

```
opendata.maryland.gov (SODA) ──extract.py──> data/raw/<run_id>/*.parquet + manifest.json
BLS · USAspending · Census · DBM MFR ──enrich.py──┘
                                   │
                         build.py  ▼
raw (as delivered) ──> ref (dimensions, mapping rules, budget stages, reported savings, from reference/*.csv)
                  └──> core (typed facts: budget, fund, FTE, payments, grants, CPI, federal awards, population, MFR)
                                   │
                         (Phase 4) ▼
                       mart (dashboard tables) ──> dashboard datasets
ops: source snapshot · portal yearly totals · enrichment status · check results · run log
```

## 5. Quality controls

`docs/checks.md` lists every check with its layer, severity and phase. Rules:

- A **Stop** check that fails exits non-zero, keeps the last good database, and saves the failed build as `md_transparency.failed.duckdb`. Nothing is published.
- A **Warn** check is recorded and shown, but doesn't block.
- Every result is stored in `ops.check_result` and appended to `data/check_history.csv`. Every run, including failed runs, is appended to `data/runs.csv`.
- Totals must tie to the portal's own `sum()` to the cent, and budget totals to funding-source totals within $1.

## 6. Reference data change control

Every mapping rule, scope rule and manual decision is a CSV in `reference/`, reviewed through a pull request (CODEOWNERS). No rule lives only in code.

| File | Governs |
|---|---|
| `payment_agency_rules.csv` | How payment agency names map to budget agency codes |
| `payment_agency_decisions.csv` | Manual mapping decisions, with `decided_by` and `date` (pending rows need a decision) |
| `vendor_normalization.csv`, `vendor_families.csv` | How payee names are cleaned and grouped into companies |
| `payee_focus_area.csv`, `focus_area_rules.csv` | Which spending belongs to each GMI focus area |
| `controllable_rules.csv` | What counts as controllable purchases |
| `budget_stage.csv` | Confirmed stage of each budget year, with its source |
| `gmi_reported_savings.csv` | Every reported saving, with source, page and quote |
| `mfr_agency_map.csv` | Managing for Results plan files to agency codes |
| `baseline_quality.csv` | Match rates the pipeline must not fall below |
| `payee_type_rules.csv` | Payee type of every vendor (Government, Health care organization, Education institution, Financial institution, Utility, Non-profit, Business or other), in priority order |
| `function_exceptions.csv` | Payment accounts the operating budget data doesn't carry (capital accounts, independent authorities), named instead of given a function |
| `column_dictionary.csv` | The definition of every column (this document) |

## 7. Citations

- Every reported saving has a source, URL, page and verbatim quote in `reference/gmi_reported_savings.csv`. The run fails if any is missing ("Every reported savings item cites its source and page").
- A figure the sources don't publish is not filled in. For example, GMI names four contract types under the $18M but no vendors and no split, so the tracker checks payment categories and labels each match as a best match.
- Cost avoidance (DGS $326.3M) is kept apart from recurring yearly savings.

## 8. Assumptions register

Values that are not published by any source. Each one is labeled as an assumption wherever the dashboard shows it.

| Assumption | Value | Where used | Code |
|---|---|---|---|
| Statewide contract saving (bid list) | 2–5% of FY2026 payments | Opportunities, bid list | `recs.py bid_list` |
| Statewide contract saving (path to $50M) | 3.5% | Path to $50M | `recs.py plan50` |
| Starting savings in real estate and utilities | 1% of forecast spending | Path to $50M | `recs.py plan50` |
| Peer gap detector | 5–15% of the gap above the 75th percentile (capped at 3–10% of budget) | Opportunities | `opportunities.py` |
| Growth above trend detector | 10–30% of the excess growth | Opportunities | `opportunities.py` |
| Tail spend detector | 3–10% of spending outside the top 10 vendors | Opportunities | `opportunities.py` |
| Leverage detector | 2–5% of payments to vendors paid by 10 or more agencies (at least $5M) | Opportunities | `opportunities.py` |
| Delivery range (Monte Carlo) | 50–125% of each savings rate | Calculator | `index.html caSim` |
| Payment-match tolerance | "Seen" when the payment drop is at least 50% of the reported saving | Savings tracker | `recs.py recurrence` |

Not assumptions, and sourced: the default savings rates (GMI's reported recurring savings ÷ FY2025 spending), and the fee (20% of savings, $15M cap; WYPR).

## 9. Privacy, licence and security

- **Licence:** all five portal datasets are Public Domain (portal metadata).
- **Individuals:** the payments and grants data include individuals. The tracker analyzes companies: payee names are grouped into vendors, and the vendor views list companies paid by many agencies. Individual payee names must not be featured in published views or exports. *Open item:* add a check that flags payee names that look like a person's name in any published vendor table.
- **Secrets:** `MD_SODA_APP_TOKEN` and `BLS_API_KEY` live only in GitHub Actions secrets or a local `.env` (in `.gitignore`), never in the repo.
- **Access:** the dashboard is a private artifact until the owner shares it.
- **Open classification item:** the payee "MARYLAND CARE INC" ($1.31B in FY2025, paid by the Health function) is left as "Business or other". Its name does not match any of the nine HealthChoice MCOs on the Department of Health's chart (2/1/26), and we could not confirm which plan it is; classify it only with a source.

## 10. Retention and versioning

- Raw files: `data/raw/<run_id>/` (Parquet + manifest). Unchanged sources are hard-linked, not copied.
- Database: the last good `data/md_transparency.duckdb` is kept until a build passes.
- Run and check history: `data/runs.csv`, `data/check_history.csv` (append-only); uploaded as run evidence by the workflow.
- Rules, citations and this document: versioned in git.
- Source schema snapshots: `docs/schemas/catalog_snapshot.json`; changes go to `docs/schemas/drift_history.csv`.

## 11. Schemas

Also saved as CSV in `docs/schemas/` (`source_columns.csv`, `warehouse_columns.csv`, `dashboard_columns.csv`). Origin: **portal** = as published; **source** = other external source; **reference** = from `reference/*.csv`; **derived** = computed by the pipeline; **ops** = run metadata.

### 11.1 Source datasets (as published)

<!-- gen:sources -->
**budget** (yu65-jmmv, 23 columns)

| field_name | display_name | datatype | portal_description | definition |
|---|---|---|---|---|
| fiscal_year | Fiscal Year | Number | (none) | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_subobject_code | Agency Subobject Code | Text | (none) | Agency-specific spending code; not used (Comptroller sub-object is used) |
| description | Description | Text | (none) | Portal description column; not used |
| agency_subobject_name | Agency Subobject Name | Text | (none) | Agency-specific spending code name; not used |
| comptroller_subobject_name | Comptroller Subobject Name | Text | (none) | Comptroller sub-object name; renamed subobject_name in core |
| comptroller_subobject_code | Comptroller Subobject Code | Text | (none) | Comptroller sub-object (detailed spending) code; renamed subobject_code in core |
| object_name | Object Name | Text | (none) | Comptroller object name |
| object_code | Object Code | Text | (none) | Comptroller object code, two digits (for example 08 Contractual services) |
| subprogram_code | Subprogram Code | Text | (none) | Budget subprogram code |
| subprogram_name | Subprogram Name | Text | (none) | Budget subprogram name |
| program_name | Program Name | Text | (none) | Budget program name |
| unit_name | Unit Name | Text | (none) | Budget unit name |
| unit_code | Unit Code | Text | (none) | Budget unit code within an agency |
| agency_name | Agency Name | Text | (none) | Agency name as published; in core the code suffix the portal adds in some years is removed |
| agency_code | Agency Code | Text | (none) | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| category | Category | Number | (none) | Budget function code (renamed function_code in core) |
| organization_sub_code | Organization Sub Code | Text | (none) | Portal's combined code including subprogram |
| organization_code | Organization Code | Text | (none) | Portal's combined agency-unit-program code |
| type | Type | Text | (none) | Budget stage label published by the portal; out of date for recent years so ref.dim_stage is used instead |
| budget | Budget | Number | (none) | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| fund_type_name | Fund Type Name | Text | (none) | Fund type name as published |
| category_title | Category Title | Text | (none) | Budget function title (renamed function_name in core) |
| program_code | Program Code | Text | (none) | Budget program code, two digits in core |

**fte** (x8qy-486w, 9 columns)

| field_name | display_name | datatype | portal_description | definition |
|---|---|---|---|---|
| count | Count | Number | (none) | Budgeted full-time-equivalent positions (renamed fte in core) |
| program_name | Program Name | Text | (none) | Budget program name |
| unit_name | Unit Name | Text | (none) | Budget unit name |
| agency_name | Agency Name | Text | (none) | Agency name as published; in core the code suffix the portal adds in some years is removed |
| organization_code | Organization Code | Text | (none) | Portal's combined agency-unit-program code |
| fiscal_year | Fiscal Year | Number | (none) | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| program_code | Program Code | Text | (none) | Budget program code, two digits in core |
| unit_code | Unit Code | Text | (none) | Budget unit code within an agency |
| agency_code | Agency Code | Text | (none) | Three-character State budget agency code (for example D50); the key that joins budget and payments |

**fund** (gy87-e27x, 15 columns)

| field_name | display_name | datatype | portal_description | definition |
|---|---|---|---|---|
| fiscal_year | Fiscal Year | Number | (none) | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| category | Category | Number | (none) | Budget function code (renamed function_code in core) |
| program_name | Program Name | Text | (none) | Budget program name |
| budget | Budget | Number | (none) | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| program_code | Program Code | Text | (none) | Budget program code, two digits in core |
| category_title | Category Title | Text | (none) | Budget function title (renamed function_name in core) |
| unit_name | Unit Name | Text | (none) | Budget unit name |
| unit_code | Unit Code | Text | (none) | Budget unit code within an agency |
| agency_name | Agency Name | Text | (none) | Agency name as published; in core the code suffix the portal adds in some years is removed |
| agency_code | Agency Code | Text | (none) | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| organization_code | Organization Code | Text | (none) | Portal's combined agency-unit-program code |
| fund_source_name | Fund Source Name | Text | (none) | Fund source name |
| fund_source_code | Fund Source Code | Text | (none) | Fund source code within a fund type |
| fund_type_name | Fund Type Name | Text | (none) | Fund type name as published |
| description | Description | Text | (none) | Portal description column; not used |

**grants** (absk-avps, 10 columns)

| field_name | display_name | datatype | portal_description | definition |
|---|---|---|---|---|
| fiscalyear | Fiscal Year | Number | (none) | Fiscal year in the grants dataset (renamed fiscal_year in core) |
| description | Description | Text | (none) | Grant or loan purpose as written by the grantor |
| category | Category | Text | (none) | Grant or Loan |
| nonprofit | Nonprofit | Text | Whether or not the grantee is a non-profit (503C) entity.  | Y when the portal marks the grantee as a non-profit |
| fiscalperiod | Fiscal Period | Number | (none) | Accounting period in the grants dataset; not used |
| date | Date | Calendar date | (none) | Portal date column; a placeholder (fiscal year end) rather than the payment or award date; not used |
| grantor | Grantor | Text | (none) | State agency and program awarding the grant or loan |
| amount | Amount | Number | (none) | Dollars paid, awarded or reported on the row; nominal dollars |
| grantee | Grantee | Text | (none) | Recipient of the grant or loan |
| zipcode | Zip Code | Text | (none) | Grantee ZIP code as published |

**payments** (7syw-q4cy, 8 columns)

| field_name | display_name | datatype | portal_description | definition |
|---|---|---|---|---|
| fiscal_year | Fiscal Year | Number | (none) | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| category | Category | Text | (none) | Payment category as published by the portal |
| date | Date | Calendar date | (none) | Portal date column; a placeholder (fiscal year end) rather than the payment or award date; not used |
| agency_name | Agency Name | Text | (none) | Agency name as published; in core the code suffix the portal adds in some years is removed |
| fiscal_period | Fiscal Period | Number | (none) | Accounting period; the portal fills it with a placeholder value so it is not used |
| amount | Amount | Number | (none) | Dollars paid, awarded or reported on the row; nominal dollars |
| vendor_zip | Vendor Zip | Text | (none) | Payee ZIP code as published |
| vendor_name | Vendor Name | Text | (none) | Payee name as published; includes businesses and individuals |
<!-- /gen:sources -->

### 11.2 Warehouse (DuckDB)

<!-- gen:warehouse -->
**core.cpi_fy** (21 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| cpi_avg | DOUBLE | derived | Average CPI-U over the fiscal year's months |
| months | BIGINT | derived | Months of CPI available for the fiscal year |
| to_latest_dollars | DOUBLE | derived | Multiplier that converts the fiscal year's dollars to dollars of the latest full fiscal year |
| dollars_of_fy | INTEGER | derived | Fiscal year whose dollars to_latest_dollars converts to |

**core.fact_budget** (741,957 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name | VARCHAR | portal | Agency name as published; in core the code suffix the portal adds in some years is removed |
| unit_code | VARCHAR | portal | Budget unit code within an agency |
| unit_name | VARCHAR | portal | Budget unit name |
| program_code | VARCHAR | portal | Budget program code, two digits in core |
| program_name | VARCHAR | portal | Budget program name |
| subprogram_code | VARCHAR | portal | Budget subprogram code |
| subprogram_name | VARCHAR | portal | Budget subprogram name |
| object_code | VARCHAR | portal | Comptroller object code, two digits (for example 08 Contractual services) |
| object_name | VARCHAR | portal | Comptroller object name |
| subobject_code | VARCHAR | derived | Comptroller sub-object code without leading zeros |
| subobject_name | VARCHAR | derived | Comptroller sub-object name |
| fund_type | VARCHAR | derived | Fund type (General, Special, Federal, Reimbursable and so on) |
| portal_type | VARCHAR | derived | The portal's own stage label kept for comparison with the confirmed stage |
| function_code | INTEGER | derived | Budget function code (from the portal's category) |
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| organization_code | VARCHAR | portal | Portal's combined agency-unit-program code |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**core.fact_budget_scope** (741,957 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name | VARCHAR | portal | Agency name as published; in core the code suffix the portal adds in some years is removed |
| unit_code | VARCHAR | portal | Budget unit code within an agency |
| unit_name | VARCHAR | portal | Budget unit name |
| program_code | VARCHAR | portal | Budget program code, two digits in core |
| program_name | VARCHAR | portal | Budget program name |
| subprogram_code | VARCHAR | portal | Budget subprogram code |
| subprogram_name | VARCHAR | portal | Budget subprogram name |
| object_code | VARCHAR | portal | Comptroller object code, two digits (for example 08 Contractual services) |
| object_name | VARCHAR | portal | Comptroller object name |
| subobject_code | VARCHAR | derived | Comptroller sub-object code without leading zeros |
| subobject_name | VARCHAR | derived | Comptroller sub-object name |
| fund_type | VARCHAR | derived | Fund type (General, Special, Federal, Reimbursable and so on) |
| portal_type | VARCHAR | derived | The portal's own stage label kept for comparison with the confirmed stage |
| function_code | INTEGER | derived | Budget function code (from the portal's category) |
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| organization_code | VARCHAR | portal | Portal's combined agency-unit-program code |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| internal | BOOLEAN | derived | True for transfers between State agencies (reimbursable funds) excluded from controllable spending |
| entitlement | BOOLEAN | derived | True for spending set by law or formula (for example Medicaid benefits) excluded from controllable spending |
| controllable | BOOLEAN | derived | Controllable purchases: contractual services, supplies, equipment, rent and similar spending agencies can renegotiate, per reference/controllable_rules.csv |
| focus_area | VARCHAR | derived | One of GMI's six focus areas assigned by reference/focus_area_rules.csv; empty when none |
| scope | VARCHAR | derived | Spending scope bucket on the dashboard (controllable purchases or staff/grants/capital and so on) |

**core.fact_federal_award** (20 rows)

| column | type | origin | definition |
|---|---|---|---|
| federal_fy | BIGINT | source | Federal fiscal year (October to September) from USAspending |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| partial | BOOLEAN | derived | True when the year is not finished |
| reporting_incomplete | BOOLEAN | derived | True when a federal-award year is under 60% of the prior year (reporting lag) |
| definition | VARCHAR | source | What the federal award total includes (USAspending award types 02-05 to Maryland governments) |

**core.fact_fte** (6,026 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| unit_code | VARCHAR | portal | Budget unit code within an agency |
| program_code | VARCHAR | portal | Budget program code, two digits in core |
| organization_code | VARCHAR | portal | Portal's combined agency-unit-program code |
| fte | DOUBLE | derived | Budgeted full-time-equivalent positions |

**core.fact_fund** (26,178 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fund_type | VARCHAR | derived | Fund type (General, Special, Federal, Reimbursable and so on) |
| fund_source_code | VARCHAR | portal | Fund source code within a fund type |
| fund_source_name | VARCHAR | portal | Fund source name |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**core.fact_grant** (23,085 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| grantor | VARCHAR | portal | State agency and program awarding the grant or loan |
| grantee | VARCHAR | portal | Recipient of the grant or loan |
| category | VARCHAR | portal | Grant or Loan |
| nonprofit | VARCHAR | portal | Y when the portal marks the grantee as a non-profit |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |

**core.fact_payment** (411,231 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_name_as_paid | VARCHAR | derived | Agency name exactly as it appears in the payments dataset |
| vendor_name_as_paid | VARCHAR | derived | Payee name exactly as published in payments |
| vendor_zip | VARCHAR | portal | Payee ZIP code as published |
| agency_code_as_paid | VARCHAR | derived | Agency code when the payments dataset carries one in the name; otherwise empty |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| partial_year | BOOLEAN | derived | True for the latest payments year while it is still incomplete |

**core.fact_payment_mapped** (411,231 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_name_as_paid | VARCHAR | derived | Agency name exactly as it appears in the payments dataset |
| vendor_name_as_paid | VARCHAR | derived | Payee name exactly as published in payments |
| vendor_zip | VARCHAR | portal | Payee ZIP code as published |
| agency_code_as_paid | VARCHAR | derived | Agency code when the payments dataset carries one in the name; otherwise empty |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| partial_year | BOOLEAN | derived | True for the latest payments year while it is still incomplete |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| matched_by | VARCHAR | derived | Rule that mapped the payment agency name to a code |

**core.fact_population** (16 rows)

| column | type | origin | definition |
|---|---|---|---|
| calendar_year | BIGINT | source | Calendar year of the Census population estimate |
| fiscal_year | BIGINT | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| population | BIGINT | source | Maryland resident population (Census Population Estimates) |
| vintage | BIGINT | source | Census estimate vintage (release year) |

**core.mfr_document** (111 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | BIGINT | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_file | VARCHAR | source | File name of an agency's Managing for Results plan PDF |
| agency_title | VARCHAR | source | Agency name on the Managing for Results plan's web page |
| url | VARCHAR | source | Link to the source document |
| bytes | BIGINT | source | File size in bytes |
| last_modified | VARCHAR | source | Last-Modified header the source server returned |

**core.mfr_measure** (22,157 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_file | VARCHAR | source | File name of an agency's Managing for Results plan PDF |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| plan_year | BIGINT | source | Fiscal year of the Managing for Results plan |
| goal | VARCHAR | source | Plan goal text |
| objective | VARCHAR | source | Plan objective text |
| measure | VARCHAR | source | Performance measure name as printed |
| fiscal_year | BIGINT | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| kind | VARCHAR | source | Actual or estimate, from the plan's column heading |
| value_text | VARCHAR | source | Measure value exactly as printed |
| value | DOUBLE | derived | Measure value as a number |

**mart.agency_function** (795 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| function_share | DOUBLE | derived | Share of the agency's budget that year in its main function (1.0 for every agency today) |

**mart.agency_master** (86 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | VARCHAR | derived | Agency name shown on the dashboard |
| in_budget | BOOLEAN | derived | True when the agency code exists in the budget |
| payment_names | BIGINT | derived | Payment agency names mapped to the code |
| how_matched | VARCHAR | derived | How the payment names were matched to the code |

**mart.agency_name** (82 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | VARCHAR | derived | Agency name shown on the dashboard |

**mart.agency_results** (21,835 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name | VARCHAR | portal | Agency name as published; in core the code suffix the portal adds in some years is removed |
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| agency_file | VARCHAR | source | File name of an agency's Managing for Results plan PDF |
| plan_year | BIGINT | source | Fiscal year of the Managing for Results plan |
| goal | VARCHAR | source | Plan goal text |
| objective | VARCHAR | source | Plan objective text |
| measure | VARCHAR | source | Performance measure name as printed |
| fiscal_year | BIGINT | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| kind | VARCHAR | source | Actual or estimate, from the plan's column heading |
| value | DOUBLE | derived | Measure value as a number |
| value_text | VARCHAR | source | Measure value exactly as printed |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| controllable | DOUBLE | derived | Controllable purchases: contractual services, supplies, equipment, rent and similar spending agencies can renegotiate, per reference/controllable_rules.csv |
| fte | DOUBLE | derived | Budgeted full-time-equivalent positions |
| payments_non_government | DOUBLE | derived | Payments by the agency to payees whose payee type is not Government |
| to_latest_dollars | DOUBLE | derived | Multiplier that converts the fiscal year's dollars to dollars of the latest full fiscal year |
| population | BIGINT | source | Maryland resident population (Census Population Estimates) |

**mart.agency_rollup** (795 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name | VARCHAR | portal | Agency name as published; in core the code suffix the portal adds in some years is removed |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| controllable | DOUBLE | derived | Controllable purchases: contractual services, supplies, equipment, rent and similar spending agencies can renegotiate, per reference/controllable_rules.csv |
| focus_area_spend | DOUBLE | derived | Budget spending in GMI's six focus areas (spending codes in ref.map_focus_area) |
| fte | DOUBLE | derived | Budgeted full-time-equivalent positions |
| payments_all | DOUBLE | derived | All payments made by the agency in the year |
| payments_non_government | DOUBLE | derived | Payments by the agency to payees whose payee type is not Government |
| vendors | BIGINT | derived | Distinct payees in the year |
| to_latest_dollars | DOUBLE | derived | Multiplier that converts the fiscal year's dollars to dollars of the latest full fiscal year |
| dollars_of_fy | INTEGER | derived | Fiscal year whose dollars to_latest_dollars converts to |
| population | BIGINT | source | Maryland resident population (Census Population Estimates) |

**mart.agency_year** (795 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | VARCHAR | derived | Agency name shown on the dashboard |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| operating_spending | DOUBLE | derived | Operating budget (all funds) for the agency and year |
| controllable | DOUBLE | derived | Controllable purchases: contractual services, supplies, equipment, rent and similar spending agencies can renegotiate, per reference/controllable_rules.csv |
| fte | DOUBLE | derived | Budgeted full-time-equivalent positions |
| payments | DOUBLE | derived | Payments made by the agency in the year (all payees) |
| controllable_per_fte | DOUBLE | derived | Controllable purchases divided by budgeted positions |
| controllable_prior | DOUBLE | derived | controllable in the previous fiscal year for the same keys |
| fte_prior | DOUBLE | derived | fte in the previous fiscal year for the same keys |
| controllable_per_fte_prior | DOUBLE | derived | controllable_per_fte in the previous fiscal year for the same keys |
| controllable_yoy | DOUBLE | derived | Change in controllable from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| fte_yoy | DOUBLE | derived | Change in fte from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| controllable_per_fte_yoy | DOUBLE | derived | Change in controllable_per_fte from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| stage_pair | VARCHAR | derived | Stages compared by the change, e.g. 'Actual vs Actual' or 'Working budget vs Actual' |

**mart.area_agency_year** (3,584 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| area | VARCHAR | derived | One of GMI's six focus areas |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |
| agency | VARCHAR | derived | Agency name shown on the dashboard |
| spend_prior | DOUBLE | derived | spend in the previous fiscal year for the same keys |
| spend_yoy | DOUBLE | derived | Change in spend from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| stage_pair | VARCHAR | derived | Stages compared by the change, e.g. 'Actual vs Actual' or 'Working budget vs Actual' |

**mart.area_code_year** (935 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| area | VARCHAR | derived | One of GMI's six focus areas |
| code | VARCHAR | derived | Comptroller sub-object code |
| spending_code | VARCHAR | derived | Comptroller sub-object name (with code) shown on the dashboard |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |
| agencies | BIGINT | derived | Agencies paying the vendor (or with payments in the year) |
| spend_prior | DOUBLE | derived | spend in the previous fiscal year for the same keys |
| spend_yoy | DOUBLE | derived | Change in spend from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| stage_pair | VARCHAR | derived | Stages compared by the change, e.g. 'Actual vs Actual' or 'Working budget vs Actual' |

**mart.area_vendor_year** (440 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| area | VARCHAR | derived | One of GMI's six focus areas |
| vendor | VARCHAR | derived | Company name after grouping payee names |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |
| agencies | BIGINT | derived | Agencies paying the vendor (or with payments in the year) |
| spend_prior | DOUBLE | derived | spend in the previous fiscal year for the same keys |
| spend_yoy | DOUBLE | derived | Change in spend from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |

**mart.area_year** (120 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| area | VARCHAR | derived | One of GMI's six focus areas |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |
| agencies | BIGINT | derived | Agencies paying the vendor (or with payments in the year) |
| codes | BIGINT | derived | Spending codes with spending in the area |
| payee_spend | DOUBLE | derived | Payments to payees assigned to the focus area by payee name (pass-through payments excluded) |
| vendors | BIGINT | derived | Distinct payees in the year |
| spend_prior | DOUBLE | derived | spend in the previous fiscal year for the same keys |
| payee_spend_prior | DOUBLE | derived | payee_spend in the previous fiscal year for the same keys |
| spend_yoy | DOUBLE | derived | Change in spend from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| payee_spend_yoy | DOUBLE | derived | Change in payee_spend from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| stage_pair | VARCHAR | derived | Stages compared by the change, e.g. 'Actual vs Actual' or 'Working budget vs Actual' |

**mart.budget_by_function** (126 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| category_title | VARCHAR | portal | Budget function title (renamed function_name in core) |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| budget_prior | DOUBLE | derived | budget in the previous fiscal year for the same keys |
| budget_yoy | DOUBLE | derived | Change in budget from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| stage_pair | VARCHAR | derived | Stages compared by the change, e.g. 'Actual vs Actual' or 'Working budget vs Actual' |

**mart.budget_by_fund** (55 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| fund_type_name | VARCHAR | portal | Fund type name as published |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| budget_prior | DOUBLE | derived | budget in the previous fiscal year for the same keys |
| budget_yoy | DOUBLE | derived | Change in budget from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| stage_pair | VARCHAR | derived | Stages compared by the change, e.g. 'Actual vs Actual' or 'Working budget vs Actual' |

**mart.budget_by_object** (147 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| object_name | VARCHAR | portal | Comptroller object name |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| controllable | DOUBLE | derived | Controllable purchases: contractual services, supplies, equipment, rent and similar spending agencies can renegotiate, per reference/controllable_rules.csv |
| budget_prior | DOUBLE | derived | budget in the previous fiscal year for the same keys |
| controllable_prior | DOUBLE | derived | controllable in the previous fiscal year for the same keys |
| budget_yoy | DOUBLE | derived | Change in budget from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| controllable_yoy | DOUBLE | derived | Change in controllable from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| stage_pair | VARCHAR | derived | Stages compared by the change, e.g. 'Actual vs Actual' or 'Working budget vs Actual' |

**mart.d_agency** (82 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | VARCHAR | derived | Agency name shown on the dashboard |

**mart.d_vendors** (3,640 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | VARCHAR | derived | Company name after grouping payee names |
| payee_type | VARCHAR | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| main_function | VARCHAR | derived | Budget function with the most payments to the vendor, all years |
| focus_area | VARCHAR | derived | One of GMI's six focus areas assigned by reference/focus_area_rules.csv; empty when none |
| payee_names | BIGINT | derived | Payee names grouped into the vendor |
| fy2022 | DOUBLE | derived | Payments in FY2022 |
| fy2023 | DOUBLE | derived | Payments in FY2023 |
| fy2024 | DOUBLE | derived | Payments in FY2024 |
| fy2025 | DOUBLE | derived | Payments in FY2025 |
| fy2026 | DOUBLE | derived | Payments in FY2026 |
| agencies_fy2025 | BIGINT | derived | Agencies that paid the vendor in FY2025 |
| agencies_fy2026 | BIGINT | derived | Agencies that paid the vendor in FY2026 |

**mart.f_agency** (795 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | VARCHAR | derived | Agency name shown on the dashboard |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| operating_spending | DOUBLE | derived | Operating budget (all funds) for the agency and year |
| controllable | DOUBLE | derived | Controllable purchases: contractual services, supplies, equipment, rent and similar spending agencies can renegotiate, per reference/controllable_rules.csv |
| fte | DOUBLE | derived | Budgeted full-time-equivalent positions |
| payments | DOUBLE | derived | Payments made by the agency in the year |

**mart.f_area** (6,425 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| area | VARCHAR | derived | One of GMI's six focus areas |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |
| payee_spend | DOUBLE | derived | Payments to payees assigned to the focus area |

**mart.f_code** (14,744 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| area | VARCHAR | derived | One of GMI's six focus areas |
| code | VARCHAR | derived | Comptroller sub-object code |
| spending_code | VARCHAR | derived | Comptroller sub-object name (with code) shown on the dashboard |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |

**mart.f_function** (795 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| category_title | VARCHAR | portal | Budget function title (renamed function_name in core) |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**mart.f_fund** (1,919 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fund_type_name | VARCHAR | portal | Fund type name as published |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**mart.f_object** (7,817 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| object_name | VARCHAR | portal | Comptroller object name |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| controllable | DOUBLE | derived | Controllable purchases: contractual services, supplies, equipment, rent and similar spending agencies can renegotiate, per reference/controllable_rules.csv |

**mart.f_payee_type** (5,942 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| payee_type | VARCHAR | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| paid | DOUBLE | derived | Payments in dollars |
| vendors | BIGINT | derived | Distinct payees in the year |

**mart.f_scope** (2,484 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| scope | VARCHAR | derived | Spending scope bucket on the dashboard (controllable purchases or staff/grants/capital and so on) |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**mart.f_vendor** (5,706 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| area | VARCHAR | derived | One of GMI's six focus areas |
| vendor | VARCHAR | derived | Company name after grouping payee names |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |

**mart.f_vendor_pay** (30,845 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | VARCHAR | derived | Company name after grouping payee names |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| paid | DOUBLE | derived | Payments in dollars |

**mart.f_vendor_year** (20 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| vendors | BIGINT | derived | Distinct payees in the year |
| paid_non_government | DOUBLE | derived | Payments to non-government payees in the year |
| top10_share | DOUBLE | derived | Share of non-government payments held by the 10 largest vendors that year |
| top100_share | DOUBLE | derived | Share of non-government payments held by the 100 largest vendors that year |
| vendors_1m | BIGINT | derived | Non-government vendors paid $1M or more that year |

**mart.payment_area** (411,231 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name_as_paid | VARCHAR | derived | Agency name exactly as it appears in the payments dataset |
| vendor_name | VARCHAR | portal | Payee name as published |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| vendor | VARCHAR | derived | Company name after grouping payee names |
| is_government | BOOLEAN | derived | True when the payee is a government body (excluded from vendor analysis) |
| area | VARCHAR | derived | One of GMI's six focus areas |
| passthrough | BOOLEAN | derived | True when the payment matches reference/payee_area_exclusions.csv (nursing facilities, bill assistance, outsourced benefits processing); its focus area is removed |

**mart.spending_scope** (44 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| scope | VARCHAR | derived | Spending scope bucket on the dashboard (controllable purchases or staff/grants/capital and so on) |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| budget_prior | DOUBLE | derived | budget in the previous fiscal year for the same keys |
| budget_yoy | DOUBLE | derived | Change in budget from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero) |
| stage_pair | VARCHAR | derived | Stages compared by the change, e.g. 'Actual vs Actual' or 'Working budget vs Actual' |

**mart.totals_by_fy** (20 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| total_payments | DOUBLE | derived | All payments in the fiscal year |
| payment_records | BIGINT | derived | Payment rows in the fiscal year |
| agencies | BIGINT | derived | Agencies paying the vendor (or with payments in the year) |
| vendors | BIGINT | derived | Distinct payees in the year |
| total_payments_prior | DOUBLE | derived | All payments in the previous fiscal year |
| total_payments_yoy | DOUBLE | derived | Change in total payments from the previous fiscal year (share) |

**mart.vendor_agency_year** (387,361 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | VARCHAR | derived | Company name after grouping payee names |
| payee_type | VARCHAR | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| partial_year | BOOLEAN | derived | True for the latest payments year while it is still incomplete |
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| paid | DOUBLE | derived | Payments in dollars |
| payments | BIGINT | derived | Payment rows in the vendor, agency and year |
| payee_names | BIGINT | derived | Distinct payee names grouped into the vendor |

**mart.vendor_families** (130 rows)

| column | type | origin | definition |
|---|---|---|---|
| family | VARCHAR | reference | Company that several payee names belong to |
| payee_names | BIGINT | derived | Distinct payee names grouped into the vendor |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |
| agencies | BIGINT | derived | Agencies paying the vendor (or with payments in the year) |

**mart.vendor_master** (56,590 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | VARCHAR | derived | Company name after grouping payee names |
| payee_type | VARCHAR | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| type_basis | VARCHAR | derived | How the payee type was assigned: name rule, grants data nonprofit = Y, or default |
| payee_names | BIGINT | derived | Distinct payee names grouped into the vendor |
| focus_area | VARCHAR | derived | One of GMI's six focus areas assigned by reference/focus_area_rules.csv; empty when none |
| first_fy | INTEGER | derived | First fiscal year the code appears |
| last_fy | INTEGER | derived | Last fiscal year the code appears |
| agencies_all_years | BIGINT | derived | Agencies that paid the vendor in any year |
| agencies_last_full_year | BIGINT | derived | Agencies that paid the vendor in the latest full payments year |
| functions | BIGINT | derived | Budget functions the vendor is paid from (via the paying agencies) |
| main_function | VARCHAR | derived | Function with the most payments to the vendor, all years |
| last_full_year | INTEGER | derived | Latest fiscal year of payments that is complete |
| paid_last_full_year | DOUBLE | derived | Payments to the vendor in last_full_year |
| paid_prior_year | DOUBLE | derived | Payments to the vendor in the year before last_full_year |
| paid_all_years | DOUBLE | derived | Payments to the vendor, all years |

**mart.vendor_type** (56,590 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | VARCHAR | derived | Company name after grouping payee names |
| payee_type | VARCHAR | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| type_basis | VARCHAR | derived | How the payee type was assigned: name rule, grants data nonprofit = Y, or default |
| payee_names | BIGINT | derived | Distinct payee names grouped into the vendor |
| focus_area | VARCHAR | derived | One of GMI's six focus areas assigned by reference/focus_area_rules.csv; empty when none |

**ops.check_result** (50 rows)

| column | type | origin | definition |
|---|---|---|---|
| run_id | VARCHAR | ops | Pipeline run identifier, UTC timestamp YYYYMMDDTHHMMSSZ |
| layer | VARCHAR | ops | Database layer the check ran on (raw, core, ref, mart) |
| check | VARCHAR | ops | Check description |
| severity | VARCHAR | ops | Stop (blocks the run) or Warn |
| result | VARCHAR | ops | pass, warn or fail |
| detail | VARCHAR | ops | Numbers behind the check result |

**ops.enrichment** (4 rows)

| column | type | origin | definition |
|---|---|---|---|
| run_id | VARCHAR | ops | Pipeline run identifier, UTC timestamp YYYYMMDDTHHMMSSZ |
| source | VARCHAR | ops | Source name or URL the data came from |
| status | VARCHAR | ops | Run or source status |
| rows | BIGINT | ops | Row count |
| detail | VARCHAR | ops | Numbers behind the check result |

**ops.portal_year_total** (70 rows)

| column | type | origin | definition |
|---|---|---|---|
| run_id | VARCHAR | ops | Pipeline run identifier, UTC timestamp YYYYMMDDTHHMMSSZ |
| dataset | VARCHAR | ops | Short name of the source dataset |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| total | DOUBLE | ops | Portal's own sum for the year |
| rows | BIGINT | ops | Row count |

**ops.run_log** (1 rows)

| column | type | origin | definition |
|---|---|---|---|
| run_id | VARCHAR | ops | Pipeline run identifier, UTC timestamp YYYYMMDDTHHMMSSZ |
| built_utc | VARCHAR | ops | When the database was built (UTC) |
| checks | INTEGER | ops | Number of checks run |
| passed | INTEGER | ops | Checks passed |
| warnings | INTEGER | ops | Checks that warned |
| failed | INTEGER | ops | Checks that failed |

**ops.source_snapshot** (5 rows)

| column | type | origin | definition |
|---|---|---|---|
| run_id | VARCHAR | ops | Pipeline run identifier, UTC timestamp YYYYMMDDTHHMMSSZ |
| dataset | VARCHAR | ops | Short name of the source dataset |
| dataset_id | VARCHAR | ops | Portal four-by-four identifier |
| rows_downloaded | BIGINT | ops | Rows in the downloaded file |
| portal_count | BIGINT | ops | Rows the portal reported with count(*) |
| rows_updated_at | BIGINT | ops | Portal rowsUpdatedAt (Unix seconds) used by the freshness check |
| source | VARCHAR | ops | Source name or URL the data came from |
| heal_attempts | INTEGER | ops | Re-downloads needed to match the portal count |

**raw.budget** (741,957 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | VARCHAR | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name | VARCHAR | portal | Agency name as published; in core the code suffix the portal adds in some years is removed |
| unit_code | VARCHAR | portal | Budget unit code within an agency |
| unit_name | VARCHAR | portal | Budget unit name |
| program_code | VARCHAR | portal | Budget program code, two digits in core |
| program_name | VARCHAR | portal | Budget program name |
| subprogram_code | VARCHAR | portal | Budget subprogram code |
| subprogram_name | VARCHAR | portal | Budget subprogram name |
| object_code | VARCHAR | portal | Comptroller object code, two digits (for example 08 Contractual services) |
| object_name | VARCHAR | portal | Comptroller object name |
| comptroller_subobject_code | VARCHAR | portal | Comptroller sub-object (detailed spending) code; renamed subobject_code in core |
| comptroller_subobject_name | VARCHAR | portal | Comptroller sub-object name; renamed subobject_name in core |
| agency_subobject_code | VARCHAR | portal | Agency-specific spending code; not used (Comptroller sub-object is used) |
| agency_subobject_name | VARCHAR | portal | Agency-specific spending code name; not used |
| fund_type_name | VARCHAR | portal | Fund type name as published |
| budget | VARCHAR | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| type | VARCHAR | portal | Budget stage label published by the portal; out of date for recent years so ref.dim_stage is used instead |
| organization_code | VARCHAR | portal | Portal's combined agency-unit-program code |
| organization_sub_code | VARCHAR | portal | Portal's combined code including subprogram |
| description | VARCHAR | portal | Portal description column; not used |
| category | VARCHAR | portal | Budget function code (renamed function_code in core) |
| category_title | VARCHAR | portal | Budget function title (renamed function_name in core) |
| _run_id | VARCHAR | ops | Extract run that produced the row |

**raw.cpi** (236 rows)

| column | type | origin | definition |
|---|---|---|---|
| year | INTEGER | source | Calendar year |
| month | INTEGER | source | Calendar month |
| cpi | DOUBLE | source | CPI-U, U.S. city average, all items, not seasonally adjusted (BLS CUUR0000SA0 / FRED CPIAUCNS) |
| _run_id | VARCHAR | ops | Extract run that produced the row |

**raw.federal_awards** (20 rows)

| column | type | origin | definition |
|---|---|---|---|
| federal_fy | BIGINT | source | Federal fiscal year (October to September) from USAspending |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| partial | BOOLEAN | derived | True when the year is not finished |
| reporting_incomplete | BOOLEAN | derived | True when a federal-award year is under 60% of the prior year (reporting lag) |
| _run_id | VARCHAR | ops | Extract run that produced the row |

**raw.fte** (6,026 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| unit_code | VARCHAR | portal | Budget unit code within an agency |
| program_code | VARCHAR | portal | Budget program code, two digits in core |
| count | VARCHAR | portal | Budgeted full-time-equivalent positions (renamed fte in core) |
| fiscal_year | VARCHAR | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| organization_code | VARCHAR | portal | Portal's combined agency-unit-program code |
| agency_name | VARCHAR | portal | Agency name as published; in core the code suffix the portal adds in some years is removed |
| unit_name | VARCHAR | portal | Budget unit name |
| program_name | VARCHAR | portal | Budget program name |
| _run_id | VARCHAR | ops | Extract run that produced the row |

**raw.fund** (26,178 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | VARCHAR | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name | VARCHAR | portal | Agency name as published; in core the code suffix the portal adds in some years is removed |
| unit_code | VARCHAR | portal | Budget unit code within an agency |
| unit_name | VARCHAR | portal | Budget unit name |
| program_code | VARCHAR | portal | Budget program code, two digits in core |
| program_name | VARCHAR | portal | Budget program name |
| fund_type_name | VARCHAR | portal | Fund type name as published |
| fund_source_code | VARCHAR | portal | Fund source code within a fund type |
| fund_source_name | VARCHAR | portal | Fund source name |
| budget | VARCHAR | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| organization_code | VARCHAR | portal | Portal's combined agency-unit-program code |
| description | VARCHAR | portal | Portal description column; not used |
| category | VARCHAR | portal | Budget function code (renamed function_code in core) |
| category_title | VARCHAR | portal | Budget function title (renamed function_name in core) |
| _run_id | VARCHAR | ops | Extract run that produced the row |

**raw.grants** (23,085 rows)

| column | type | origin | definition |
|---|---|---|---|
| grantor | VARCHAR | portal | State agency and program awarding the grant or loan |
| grantee | VARCHAR | portal | Recipient of the grant or loan |
| zipcode | VARCHAR | portal | Grantee ZIP code as published |
| fiscalyear | VARCHAR | portal | Fiscal year in the grants dataset (renamed fiscal_year in core) |
| amount | VARCHAR | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| description | VARCHAR | portal | Grant or loan purpose as written by the grantor |
| category | VARCHAR | portal | Grant or Loan |
| fiscalperiod | VARCHAR | portal | Accounting period in the grants dataset; not used |
| date | VARCHAR | portal | Portal date column; a placeholder (fiscal year end) rather than the payment or award date; not used |
| nonprofit | VARCHAR | portal | Y when the portal marks the grantee as a non-profit |
| _run_id | VARCHAR | ops | Extract run that produced the row |

**raw.mfr_index** (111 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | BIGINT | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_file | VARCHAR | source | File name of an agency's Managing for Results plan PDF |
| url | VARCHAR | source | Link to the source document |
| bytes | BIGINT | source | File size in bytes |
| last_modified | VARCHAR | source | Last-Modified header the source server returned |
| is_pdf | BOOLEAN | derived | True when the downloaded file is a PDF |
| _run_id | VARCHAR | ops | Extract run that produced the row |

**raw.payments** (411,231 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | VARCHAR | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_name | VARCHAR | portal | Agency name as published; in core the code suffix the portal adds in some years is removed |
| vendor_name | VARCHAR | portal | Payee name as published; includes businesses and individuals |
| vendor_zip | VARCHAR | portal | Payee ZIP code as published |
| amount | VARCHAR | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| fiscal_period | VARCHAR | portal | Accounting period; the portal fills it with a placeholder value so it is not used |
| date | VARCHAR | portal | Portal date column; a placeholder (fiscal year end) rather than the payment or award date; not used |
| category | VARCHAR | portal | Payment category as published by the portal |
| _run_id | VARCHAR | ops | Extract run that produced the row |

**raw.population** (16 rows)

| column | type | origin | definition |
|---|---|---|---|
| year | BIGINT | source | Calendar year |
| population | BIGINT | source | Maryland resident population (Census Population Estimates) |
| vintage | BIGINT | source | Census estimate vintage (release year) |
| _run_id | VARCHAR | ops | Extract run that produced the row |

**ref.baseline_quality** (7 rows)

| column | type | origin | definition |
|---|---|---|---|
| measure | VARCHAR | reference | Name of the quality measure |
| value | VARCHAR | reference | Baseline value recorded from the legacy dashboard |
| source | VARCHAR | reference | Where the reference value is documented |

**ref.budget_stage** (11 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | VARCHAR | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| source | VARCHAR | reference | Where the reference value is documented |

**ref.column_dictionary** (282 rows)

| column | type | origin | definition |
|---|---|---|---|
| column | VARCHAR | reference | Column name being defined |
| applies_to | VARCHAR | reference | Tables the definition applies to (comma-separated, wildcards allowed); blank for all |
| origin | VARCHAR | reference | Where the column comes from: portal, source, reference, derived or ops |
| definition | VARCHAR | reference | What the column means |

**ref.controllable_rule** (17 rows)

| column | type | origin | definition |
|---|---|---|---|
| rule | VARCHAR | reference | Name of the mapping or scope rule |
| value | VARCHAR | reference | The code or pattern the rule matches |
| note | VARCHAR | reference | Explanation of the rule or row |

**ref.dim_agency** (82 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name | VARCHAR | portal | Agency name as published; in core the code suffix the portal adds in some years is removed |
| names_used | BIGINT | derived | Distinct agency names seen for the code |
| first_fy | INTEGER | derived | First fiscal year the code appears |
| last_fy | INTEGER | derived | Last fiscal year the code appears |

**ref.dim_function** (12 rows)

| column | type | origin | definition |
|---|---|---|---|
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| min_code | INTEGER | derived | Lowest function code with the title |
| max_code | INTEGER | derived | Highest function code with the title |
| codes | BIGINT | derived | Function codes sharing the title |

**ref.dim_fund_type** (8 rows)

| column | type | origin | definition |
|---|---|---|---|
| fund_type | VARCHAR | derived | Fund type (General, Special, Federal, Reimbursable and so on) |

**ref.dim_object** (14 rows)

| column | type | origin | definition |
|---|---|---|---|
| object_code | VARCHAR | portal | Comptroller object code, two digits (for example 08 Contractual services) |
| object_name | VARCHAR | portal | Comptroller object name |

**ref.dim_stage** (11 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| source | VARCHAR | reference | Where the reference value is documented |

**ref.dim_subobject** (377 rows)

| column | type | origin | definition |
|---|---|---|---|
| subobject_code | VARCHAR | derived | Comptroller sub-object code without leading zeros |
| subobject_name | VARCHAR | derived | Comptroller sub-object name |
| object_code | VARCHAR | portal | Comptroller object code, two digits (for example 08 Contractual services) |

**ref.focus_area_rule** (7 rows)

| column | type | origin | definition |
|---|---|---|---|
| area | VARCHAR | derived | One of GMI's six focus areas |
| rule | VARCHAR | reference | Name of the mapping or scope rule |
| value | VARCHAR | reference | The code or pattern the rule matches |
| note | VARCHAR | reference | Explanation of the rule or row |

**ref.function_exceptions** (8 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| note | VARCHAR | reference | Explanation of the rule or row |

**ref.gmi_reported_savings** (18 rows)

| column | type | origin | definition |
|---|---|---|---|
| saving_id | VARCHAR | reference | Reported saving identifier (S01-S18) |
| workstream | VARCHAR | reference | GMI workstream the saving belongs to |
| item | VARCHAR | reference | Saving as GMI describes it |
| reported_low | VARCHAR | source | Low end of the reported saving in dollars (GMI Final Report) |
| reported_high | VARCHAR | source | High end of the reported saving in dollars (GMI Final Report) |
| type | VARCHAR | reference | Kind of saving GMI reported: year over year, one-time, cost avoidance |
| status | VARCHAR | reference | Status GMI gave the item |
| count | VARCHAR | reference | Number of contracts or items GMI reported in the saving (text) |
| payment_check | VARCHAR | reference | Payment check specification |
| note | VARCHAR | reference | Explanation of the rule or row |
| source | VARCHAR | reference | Citation for the reported saving |
| source_url | VARCHAR | source | Link to the citation |
| source_page | VARCHAR | source | Page of the citation |
| source_quote | VARCHAR | source | Verbatim quote supporting the figure |

**ref.map_focus_area** (96 rows)

| column | type | origin | definition |
|---|---|---|---|
| area | VARCHAR | derived | One of GMI's six focus areas |
| subobject_code | VARCHAR | derived | Comptroller sub-object code without leading zeros |
| subobject_name | VARCHAR | derived | Comptroller sub-object name |

**ref.map_mfr_agency** (111 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_file | VARCHAR | source | File name of an agency's Managing for Results plan PDF |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| match | VARCHAR | derived | How the plan file was matched to an agency |

**ref.map_nonprofit** (996 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor_key | VARCHAR | derived | Normalized payee name (suffixes and punctuation removed) |
| grantee | VARCHAR | portal | Recipient of the grant or loan |
| grants | BIGINT | derived | Grant and loan rows for the grantee |
| flagged | BIGINT | derived | Rows the grants dataset flags nonprofit = Y |
| nonprofit_share | DOUBLE | derived | flagged divided by grants; 0.5 or more makes the payee a Non-profit |
| granted | DOUBLE | derived | Dollars granted or lent to the grantee, all years |

**ref.map_payee_vendor** (61,798 rows)

| column | type | origin | definition |
|---|---|---|---|
| payee | VARCHAR | derived | Payee name as published |
| vendor_key | VARCHAR | derived | Normalized payee name (suffixes and punctuation removed) |
| vendor | VARCHAR | derived | Company name after grouping payee names |
| rule | VARCHAR | reference | Name of the mapping or scope rule |
| is_government | BOOLEAN | derived | True when the payee is a government body (excluded from vendor analysis) |
| payee_area | VARCHAR | derived | Focus area the payee is assigned to by reference/payee_focus_area.csv |

**ref.map_payment_agency** (145 rows)

| column | type | origin | definition |
|---|---|---|---|
| payment_agency_name | VARCHAR | derived | Agency name as it appears in payments |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| matched_by | VARCHAR | derived | Rule that mapped the payment agency name to a code |
| in_budget | BOOLEAN | derived | True when the agency code exists in the budget |

**ref.mfr_agency_map** (11 rows)

| column | type | origin | definition |
|---|---|---|---|
| file_pattern | VARCHAR | reference | Pattern matching a Managing for Results plan file name |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| note | VARCHAR | reference | Explanation of the rule or row |

**ref.payee_area_exclusions** (3 rows)

| column | type | origin | definition |
|---|---|---|---|
| area | VARCHAR | derived | One of GMI's six focus areas |
| agency_name_pattern | VARCHAR | reference | Regular expression on the paying agency name; blank for any agency |
| payee_pattern | VARCHAR | reference | Regular expression matching payee names |
| note | VARCHAR | reference | Explanation of the rule or row |

**ref.payee_focus_area** (6 rows)

| column | type | origin | definition |
|---|---|---|---|
| area | VARCHAR | derived | One of GMI's six focus areas |
| payee_pattern | VARCHAR | reference | Regular expression matching payee names |

**ref.payee_type_rule** (7 rows)

| column | type | origin | definition |
|---|---|---|---|
| priority | VARCHAR | reference | Order the payee type rules apply in; the lowest matching priority wins across a vendor's names |
| payee_type | VARCHAR | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| pattern | VARCHAR | reference | Regular expression the rule applies |
| note | VARCHAR | reference | Explanation of the rule or row |

**ref.payment_agency_decisions** (4 rows)

| column | type | origin | definition |
|---|---|---|---|
| payment_agency_name | VARCHAR | derived | Agency name as it appears in payments |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| decision | VARCHAR | reference | Mapping decision (pending, mapped, excluded) |
| decided_by | VARCHAR | reference | Who made the decision |
| date | VARCHAR | portal | Portal date column; a placeholder (fiscal year end) rather than the payment or award date; not used |

**ref.payment_agency_rule** (21 rows)

| column | type | origin | definition |
|---|---|---|---|
| rule | VARCHAR | reference | Name of the mapping or scope rule |
| payment_name_pattern | VARCHAR | reference | Regular expression matching payment agency names |
| target | VARCHAR | reference | Agency code the rule maps to |
| note | VARCHAR | reference | Explanation of the rule or row |

**ref.vendor_families** (33 rows)

| column | type | origin | definition |
|---|---|---|---|
| family | VARCHAR | reference | Company that several payee names belong to |
| payee_pattern | VARCHAR | reference | Regular expression matching payee names |

**ref.vendor_normalization** (4 rows)

| column | type | origin | definition |
|---|---|---|---|
| step | VARCHAR | reference | Order the normalization step runs in |
| pattern | VARCHAR | reference | Regular expression the rule applies |
| note | VARCHAR | reference | Explanation of the rule or row |
<!-- /gen:warehouse -->

### 11.3 Dashboard datasets

<!-- gen:dashboard -->
**agency_master** (86 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | text | derived | Agency name shown on the dashboard |
| in_budget | number | derived | True when the agency code exists in the budget |
| payment_names | number | derived | Payment agency names mapped to the code |
| how_matched | text | derived | How the payment names were matched to the code |

**d_agency** (82 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | text | derived | Agency name shown on the dashboard |

**d_bid_list** (30 rows)

| column | type | origin | definition |
|---|---|---|---|
| rank | number | derived | Rank by FY2026 payments |
| vendor | text | derived | Company name after grouping payee names |
| fy2025 | number | derived | Payments in FY2025 |
| fy2026 | number | derived | Payments in FY2026 |
| agencies | number | derived | Agencies paying the vendor (or with payments in the year) |
| low | number | derived | Low end of the estimated saving; uses a screening assumption (see Assumptions register) |
| high | number | derived | High end of the estimated saving; uses a screening assumption (see Assumptions register) |
| top_agencies | text | derived | Three agencies paying the vendor most in FY2026 |

**d_forecast_model** (7 rows)

| column | type | origin | definition |
|---|---|---|---|
| area | text | derived | One of GMI's six focus areas |
| method | text | derived | Forecast model chosen by the backtest |
| growth | number | derived | Annual growth rate of the chosen model |
| backtest_mape | number | derived | Mean absolute percentage error of the chosen model (fit FY2017-2022; scored FY2023-2025) |
| trend_mape | number | derived | Backtest error of the log-linear trend model |
| naive_mape | number | derived | Backtest error of the naive (last actual) model |
| drift_mape | number | derived | Backtest error of the drift model |
| baseline_fy2025 | number | derived | FY2025 actual spending in the area |
| gmi_recurring | number | source | Recurring savings GMI reported for the area |
| gmi_rate | number | derived | gmi_recurring divided by baseline_fy2025 |
| gmi_note | text | source | Which reported items make up gmi_recurring |
| gf_share | number | derived | General Fund share of the area's FY2025 spending |

**d_master_quality** (5 rows)

| column | type | origin | definition |
|---|---|---|---|
| measure | text | reference | Name of the quality measure |
| value | text | derived | Measured value |
| ok | number | derived | True when the measure meets its target |

**d_opps** (453 rows)

| column | type | origin | definition |
|---|---|---|---|
| opp_id | text | derived | Opportunity identifier |
| detector | text | derived | Screening rule that found the opportunity |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | text | derived | Agency name shown on the dashboard |
| area | text | derived | One of GMI's six focus areas |
| spending_code | text | derived | Comptroller sub-object name (with code) shown on the dashboard |
| baseline | number | derived | Spending the screening percentage is applied to |
| low | number | derived | Low end of the estimated saving; uses a screening assumption (see Assumptions register) |
| high | number | derived | High end of the estimated saving; uses a screening assumption (see Assumptions register) |
| evidence | text | derived | Plain-language reason the detector flagged the row |
| likely | number | derived | Midpoint of low and high |

**d_plan50** (28 rows)

| column | type | origin | definition |
|---|---|---|---|
| step | number | derived | Order of the step in the path to $50M |
| action | text | derived | Action in the path to $50M |
| basis | text | derived | How the step's saving is calculated |
| saving | number | derived | Annual saving of the step in dollars |
| tab | text | derived | Dashboard tab the row links to |
| cumulative | number | derived | Running total of savings |

**d_rec_status** (6 rows)

| column | type | origin | definition |
|---|---|---|---|
| rec | number | derived | Recommendation number (1-6) |
| title | text | derived | Recommendation title |
| status | text | derived | Status of the recommendation |
| progress | text | derived | Key number showing progress |
| tab | text | derived | Dashboard tab the row links to |
| previous | text | ops | Progress text in the previous run |

**d_savings** (18 rows)

| column | type | origin | definition |
|---|---|---|---|
| saving_id | text | reference | Reported saving identifier (S01-S18) |
| workstream | text | reference | GMI workstream the saving belongs to |
| item | text | reference | Saving as GMI describes it |
| reported_low | number | source | Low end of the reported saving in dollars (GMI Final Report) |
| reported_high | number | source | High end of the reported saving in dollars (GMI Final Report) |
| type | text | reference | Kind of saving GMI reported: year over year, one-time, cost avoidance |
| status | text | reference | Status GMI gave the item |
| count | text | reference | Number of contracts or items GMI reported in the saving (text) |
| check_id | text | derived | Reported saving whose payments are checked |
| check_note | text | reference | How the payment check is defined |
| source | text | reference | Citation for the reported saving |
| source_url | text | source | Link to the citation |
| source_page | text | source | Page of the citation |
| source_quote | text | source | Verbatim quote supporting the figure |

**d_savings_status** (12 rows)

| column | type | origin | definition |
|---|---|---|---|
| check_id | text | derived | Reported saving whose payments are checked |
| item | text | reference | Saving as GMI describes it |
| reported | number | source | Reported saving midpoint in dollars |
| before | number | derived | Matching payments in FY2025 |
| after | number | derived | Matching payments in FY2026 |
| status | text | derived | Whether the reported saving is seen in payments (Seen, Partly seen, Not seen yet, Payments fell, Payments did not fall) |
| previous_status | text | ops | Status in the previous run |
| changed | number | ops | True when the status changed since the previous run |

**d_vendor_moves** (40 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | text | derived | Company name after grouping payee names |
| fy2024 | number | derived | Payments in FY2024 |
| fy2025 | number | derived | Payments in FY2025 |
| fy2026 | number | derived | Payments in FY2026 |
| change | number | derived | FY2026 minus FY2025 payments |
| agencies | number | derived | Agencies paying the vendor (or with payments in the year) |

**d_vendor_names** (267 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | text | derived | Company name after grouping payee names |
| payee_name | text | derived | One payee name grouped into the vendor |
| fy2026 | number | derived | Payments in FY2026 |

**d_vendors** (3,640 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | text | derived | Company name after grouping payee names |
| payee_type | text | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| main_function | text | derived | Budget function with the most payments to the vendor, all years |
| focus_area | text | derived | One of GMI's six focus areas assigned by reference/focus_area_rules.csv; empty when none |
| payee_names | number | derived | Payee names grouped into the vendor |
| fy2022 | number | derived | Payments in FY2022 |
| fy2023 | number | derived | Payments in FY2023 |
| fy2024 | number | derived | Payments in FY2024 |
| fy2025 | number | derived | Payments in FY2025 |
| fy2026 | number | derived | Payments in FY2026 |
| agencies_fy2025 | number | derived | Agencies that paid the vendor in FY2025 |
| agencies_fy2026 | number | derived | Agencies that paid the vendor in FY2026 |

**f_agency** (795 rows)

| column | type | origin | definition |
|---|---|---|---|
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | text | derived | Agency name shown on the dashboard |
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| operating_spending | number | derived | Operating budget (all funds) for the agency and year |
| controllable | number | derived | Controllable purchases: contractual services, supplies, equipment, rent and similar spending agencies can renegotiate, per reference/controllable_rules.csv |
| fte | number | derived | Budgeted full-time-equivalent positions |
| payments | number | derived | Payments made by the agency in the year |

**f_area** (6,388 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| area | text | derived | One of GMI's six focus areas |
| spend | number | derived | Dollars spent (budget actuals or payments) |
| payee_spend | number | derived | Payments to payees assigned to the focus area |

**f_code** (14,744 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| area | text | derived | One of GMI's six focus areas |
| code | number | derived | Comptroller sub-object code |
| spending_code | text | derived | Comptroller sub-object name (with code) shown on the dashboard |
| spend | number | derived | Dollars spent (budget actuals or payments) |

**f_forecast** (105 rows)

| column | type | origin | definition |
|---|---|---|---|
| area | text | derived | One of GMI's six focus areas |
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| kind | text | derived | Actual, forecast or plan |
| value | number | derived | Actual or forecast spending in dollars |
| p10 | number | derived | 10th percentile of the bootstrap forecast |
| p50 | number | derived | Median of the bootstrap forecast |
| p90 | number | derived | 90th percentile of the bootstrap forecast |
| plan | number | derived | Spending after GMI's reported savings rate |

**f_function** (795 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| category_title | text | portal | Budget function title (renamed function_name in core) |
| budget | number | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**f_fund** (1,919 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fund_type_name | text | portal | Fund type name as published |
| budget | number | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**f_object** (7,817 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| object_name | text | portal | Comptroller object name |
| budget | number | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| controllable | number | derived | Controllable purchases: contractual services, supplies, equipment, rent and similar spending agencies can renegotiate, per reference/controllable_rules.csv |

**f_payee_type** (5,629 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| payee_type | text | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| function_name | text | derived | Budget function title (from the portal's category_title) |
| paid | number | derived | Payments in dollars |
| vendors | number | derived | Distinct payees in the year |

**f_savings_check** (1,400 rows)

| column | type | origin | definition |
|---|---|---|---|
| check_id | text | derived | Reported saving whose payments are checked |
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| paid | number | derived | Payments in dollars |

**f_scope** (2,484 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| scope | text | derived | Spending scope bucket on the dashboard (controllable purchases or staff/grants/capital and so on) |
| budget | number | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**f_vendor** (4,940 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| area | text | derived | One of GMI's six focus areas |
| vendor | text | derived | Company name after grouping payee names |
| spend | number | derived | Dollars spent (budget actuals or payments) |

**f_vendor_detail** (6,292 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | text | derived | Company name after grouping payee names |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| paid | number | derived | Payments in dollars |

**f_vendor_pay** (30,845 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | text | derived | Company name after grouping payee names |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| paid | number | derived | Payments in dollars |

**f_vendor_year** (19 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| vendors | number | derived | Distinct payees in the year |
| paid_non_government | number | derived | Payments to non-government payees in the year |
| top10_share | number | derived | Share of non-government payments held by the 10 largest vendors that year |
| top100_share | number | derived | Share of non-government payments held by the 100 largest vendors that year |
| vendors_1m | number | derived | Non-government vendors paid $1M or more that year |

**measures** (14 rows)

| column | type | origin | definition |
|---|---|---|---|
| table | text | derived | Dashboard table the measure belongs to |
| measure | text | derived | Column name of the dashboard measure |
| definition | text | derived | What the dashboard measure means |
| grouped_by | text | derived | Grain the measure is grouped by |
| higher_is | text | derived | Whether a higher value is better, worse or neutral |

**pipeline_runs** (35 rows)

| column | type | origin | definition |
|---|---|---|---|
| run_id | text | ops | Pipeline run identifier, UTC timestamp YYYYMMDDTHHMMSSZ |
| started_utc | text | ops | When the run started (UTC) |
| seconds | number | ops | Run duration in seconds |
| status | text | ops | Run or source status |
| published | number | ops | True when the run's outputs were published |
| checks | number | ops | Number of checks run |
| passed | number | ops | Checks passed |
| warnings | number | ops | Checks that warned |
| failed | number | ops | Checks that failed |
| repairs | number | ops | Datasets re-downloaded by self-healing |
| payment_rows | number | ops | Payment rows in the run |
| budget_rows | number | ops | Budget rows in the run |
| mode | text | ops | Run mode (full, freshness reuse, test fault) |

**run_checks** (93 rows)

| column | type | origin | definition |
|---|---|---|---|
| run_id | text | ops | Pipeline run identifier, UTC timestamp YYYYMMDDTHHMMSSZ |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| check | text | ops | Check description |
| status | text | ops | pass, warn or fail |
| detail | text | ops | Numbers behind the check result |

**sources** (5 rows)

| column | type | origin | definition |
|---|---|---|---|
| source | text | derived | Short name of the source dataset |
| dataset_id | text | ops | Portal four-by-four identifier |
| title | text | derived | Dataset title used on the dashboard |
| use | text | derived | What the dataset contributes to the tracker |
| portal_name | text | ops | Dataset title as the portal publishes it |
| portal_updated | text | ops | Date the portal data last changed |
| rows_portal | number | ops | Rows the portal reported |
| rows_downloaded | number | ops | Rows in the downloaded file |
| years | text | derived | Fiscal years used |
| reconciled | number | ops | True when downloaded rows equal the portal's count |

**stage_evidence** (4 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| file_label | text | portal | Stage label the portal file assigned to the year |
| official_stage | text | reference | Stage DBM's budget books assign to the year |
| evidence | text | source | Where in DBM's budget books the stage is confirmed |
| evidence_url | text | source | Link to the evidence document |
| programs_compared | number | derived | Programs compared between the portal file and DBM's books |
| programs_exact | number | derived | Programs whose totals match DBM's books exactly |
| file_total | number | derived | Portal file total for the year |
| dbm_actual_total | number | source | Actual total printed in DBM's budget books |
| note | text | reference | Explanation of the rule or row |

**totals_by_fy** (19 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| total_payments | number | derived | All payments in the fiscal year |
| payment_records | number | derived | Payment rows in the fiscal year |
| agencies | number | derived | Agencies paying the vendor (or with payments in the year) |
| vendors | number | derived | Distinct payees in the year |
| total_payments_prior | number | derived | All payments in the previous fiscal year |
| total_payments_yoy | number | derived | Change in total payments from the previous fiscal year (share) |

**vendor_families** (130 rows)

| column | type | origin | definition |
|---|---|---|---|
| family | text | reference | Company that several payee names belong to |
| payee_names | number | derived | Payee names grouped into the company |
| spend | number | derived | Dollars spent (budget actuals or payments) |
| agencies | number | derived | Agencies paying the vendor (or with payments in the year) |
<!-- /gen:dashboard -->

## 12. Coverage and drift

<!-- gen:coverage -->
878 of 878 columns documented (65 source, 584 warehouse, 229 dashboard).
<!-- /gen:coverage -->

**Source schema changes since the last snapshot:**

<!-- gen:drift -->
No change in source schemas since the last snapshot.
<!-- /gen:drift -->

To update: add or edit a definition in `reference/column_dictionary.csv` (column, the tables it applies to or blank for all, origin, definition), then run `make docs`. `make docs-strict` fails on any undocumented column or schema change.
