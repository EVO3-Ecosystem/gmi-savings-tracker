# Data governance — GMI Savings Tracker

<!-- gen:stamp -->
_Generated 2026-11-10T08:04Z by `python -m src.pipeline.governance`. Source schemas from the Discovery API, read Nov 10, 2026._
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
| highered | [4mca-332u](https://opendata.maryland.gov/d/4mca-332u) | Maryland Operating Budget: CUR and CR | Maryland Department of Budget Management | Maryland Department of Information Technology | Public Domain | Annually | FY2017-FY2026 | 2026-08-10 | 20 |
| payments | [7syw-q4cy](https://opendata.maryland.gov/d/7syw-q4cy) | State of Maryland Payments Data: FY2008 to FY2024 | Department of Budget and Management (DBM) | Maryland Department of Information Technology | Public Domain | Monthly | July 1, 2007 - present | 2026-11-09 | 8 |
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
| Payments | `date` and `fiscal_period` are placeholders | Distinct values by fiscal year, Nov 10, 2026: `fiscal_period` = 1 on every row FY2008-FY2027; one `date` (Jan 1 of the year) per year except FY2008, FY2009, FY2012 (one row each) and FY2022 | Used only as a record date by the payment screen; monthly analysis is not possible (section 13) |
| Payments | FY2022 published twice for MDTA (J11) and Maryland Environmental Service (U10): 539 rows ($874,477,234.00) dated Jan 1, 2023 besides the 539 dated Jan 1, 2022; the State's vendorpayments.maryland.gov FY2022 total counts both | SoQL queries and the site total, Nov 10, 2026 (`docs/reconciliation/crosschecks_2026-11-10.csv`) | Kept as published (totals tie to the State site); flagged in `mart.d_source_issues`, kept out of the payment-screen leads; question for the Comptroller (section 13) |
| Grants (absk-avps) | `fiscalperiod` and `date` are placeholders | `fiscalperiod` = 1 and `date` = June 30 of the year on every row, FY2009-FY2025, Nov 10, 2026 | Not used |
| Payments | Agency names, not codes | Schema has `agency_name` only | `ref.map_payment_agency` (rules + decisions) |
| Payments | Latest year is partial | Monthly updates (portal metadata) | `partial_year` flag |
| Grants (absk-avps) | Description says "$50,000 or more", but smaller rows exist | 1,726 of 23,085 rows are under $50,000 | Description corrected; no filter applied |
| Grants (absk-avps) | Grantor is free text "Agency/Program" with no agency code: 1,944 spellings, mixed case (WMATA grants appear under Transportation in at least five forms) | Distinct grantor values, Nov 5, 2026 | Listed as published in `mart.f_grants`; grouping grantors into agencies and programs is a next-phase step (`docs/roadmap.md`) |
| Grants vs payments | Grants are likely paid out through the payments data, so the two overlap | 13-75% of grant dollars a year go to grantees also paid that year (FY2017-FY2025, exact name match, a lower bound) | `mart.f_overlap`; grants shown as part of payments, never added to them |
| Budget vs payments | Each budget year has one stage (actuals replace the appropriation), and payments leave out payroll but include capital and pass-through money | `ref.budget_stage`; payments are 66-78% of the budget | `mart.f_budget_vs_pay` keeps them side by side with the stage; no budget-vs-actual variance until original appropriations are sourced |
| Budget (yu65-jmmv) | `type` (stage) column is out of date | Compared with DBM budget books | `ref.budget_stage` from mtp.maryland.gov and the budget books |
| Funding source (gy87-e27x), FTE (x8qy-486w) | Descriptions still say FY2026 is the Governor's Allowance; data runs to FY2027 | Portal description vs data | Same stage table as the budget |
| Budget | Code spellings vary ("0930"/"930", "1"/"01"); function codes 10–12 have more than one title; A15's name carries ":A15" in FY2026–FY2027 | Phase 2 checks | Normalized in `core` |
| All five | 50,000-row pages drop without an app token | Phase 1 runs | 20,000-row pages, retries, self-healing re-download |
| Budget (yu65-jmmv) vs higher education (4mca-332u) | The operating budget dataset leaves out public higher education: R13 Morgan State, R14 St. Mary's College, R30 University System of Maryland and R95 Baltimore City Community College are published separately as CUR and CR funds | Checked Nov 4, 2026 (no rows for the four agencies in yu65-jmmv); stop check on every build since Nov 9, 2026 | `raw.highered` / `core.fact_budget_highered` with `source_dataset`; added only in `mart.d_all_funds`, labeled "including public higher education"; out of every GMI savings baseline (below) |

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

**Public higher education and GMI savings baselines (Nov 9, 2026).** The four higher-education agencies (4mca-332u) are kept out of every savings baseline: the budget detectors never see them (they are not in yu65-jmmv), and `config/assumptions.yaml` (`gmi_baseline_exclusions`, `savings.vendor_moves.excluded_agency_codes`) drops their payments (only R95 appears in the payments data, about $16M of private payments a year) from the payment detectors, the bid list and the vendor moves. A stop check on every build confirms it. Their budget appears only in the all-funds total labeled "including public higher education" (`mart.d_all_funds`, `d_all_funds.csv`). The reason given in the roadmap, that these institutions buy under their own procurement authority outside the executive-branch procurement GMI works through, **rests on statute citations that have not been verified**; no citation is published until it is checked against the Annotated Code of Maryland (State Finance and Procurement Article) and the institutions' own procurement policies.

**Deferred (Nov 9, 2026):** `mart.payment_area` holds one row per payment, so `mart.payment_line` would be the accurate name (roadmap gap 10). The rename is deferred: eight marts and three models read it by name. `core.fact_fund` now keeps unit and program (the other half of gap 10).

Portal views reproduced as marts: where it's going (`mart.f_program`, budget by agency, unit and program), how it's funded (`mart.f_fund_source`, budget by named fund source), grants and loans as listed (`mart.f_grants`), and the overlap evidence that ties them to payments (`mart.f_budget_vs_pay`, `mart.f_overlap`). Real and per-resident dollars: `mart.d_deflator` (`d_deflator.csv`: CPI-U fiscal-year average, the factor from nominal to FY2026 dollars, and Maryland's July 1 population; FY2026 averages 11 months because BLS published no October 2025 CPI). Detector backtest: `mart.d_detector_backtest` (`docs/models/opportunities.md`).

## 7. Citations

- Every reported saving has a source, URL, page and verbatim quote in `reference/gmi_reported_savings.csv`. The run fails if any is missing ("Every reported savings item cites its source and page").
- A figure the sources don't publish is not filled in. For example, GMI names four contract types under the $18M but no vendors and no split, so the tracker checks payment categories and labels each match as a best match.
- Cost avoidance (DGS $326.3M) is kept apart from recurring yearly savings.
- **Needs verification before publishing:** the procurement-statute citations for leaving public higher education out of GMI's scope (section 6). The pipeline publishes none.

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
| Small-procurement threshold (split screen) | $50,000 before Oct 1, 2023; $100,000 from then (Md. Code SF&P 13-109(a)(1); Ch. 161 of 2023, HB 543; accessed Nov 10, 2026) | Payment screen (split rule; not measurable on annual records) | `config/assumptions.yaml payment_screen.small_procurement_*` |
| Payment screen windows and floor | duplicates: exact amount, $1,000+, record dates within 7 days; splits: 14 days | Payment screen | `sql/mart/47_v_payment_screen_rows.sql` |
| Payment recovery confirmation rate | Derived: confirmed / reviewed leads (Wilson 95% interval for low / high). Not measurable from the data (no lead can be confirmed without payment records), so NULL and the lever is 0, labeled "not measurable without payment records"; the 2% / 5% / 10% placeholders are retired | Calculator lever "Payment recovery review (leads)" | `sql/mart/49_d_payment_screen_summary.sql`, `config/assumptions.yaml payment_screen.lever` |
| Payment lead confidence | Points rule fixed before scoring: round amount, one or several paying units, same amount in another year, under $5,000, non-profit payee | Payment screen `confidence` | `config/assumptions.yaml payment_screen.confidence` |

Not assumptions, and sourced: the default savings rates (GMI's reported recurring savings ÷ FY2025 spending), and the fee (20% of savings, $15M cap; WYPR).

## 8a. Data requests

What the published data cannot answer, and what to ask for. Each request names the analysis it unlocks.

| To | Request | Why (evidence) | Unlocks |
|---|---|---|---|
| Comptroller of Maryland (General Accounting Division / open-data team for 7syw-q4cy and vendorpayments.maryland.gov) | **Payment-level dated records**: one row per payment (or invoice) with payment date, document or invoice number, paying unit code, payee ID, amount; FY2022 onward | `fiscal_period` is 1 and `date` is one Jan 1 per year on every row (Nov 10, 2026 test), so the published rows are annual totals by agency, payee name and ZIP | The duplicate rule's 7-day window and the split rule's 14-day window as designed (`docs/models/payment_screen.md`); monthly spending trends; a measured confirmation rate for the Calculator's payment-recovery lever |
| Same | Which FY2022 block is current for MDTA (J11) and Maryland Environmental Service (U10): rows dated Jan 1, 2022 or Jan 1, 2023 ($874,477,234.00) | Both are published under FY2022 and both are in the State site's FY2022 total (`mart.d_source_issues`) | A correct FY2022 payments total for both agencies (MDTA shows $1.50B against $0.80B in FY2023) |
| Same | For the leads in `docs/reviews/payment_screen_review_sheet.csv`: the invoices or grant agreements behind each pair | The data alone cannot tell one payment booked by two units from two payments | Turns `needs_records` into a decision; the first measured confirmation rate |

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
- Payee-name history: `data/payee_name_seen.csv`, loaded as `ops.payee_name_seen` (one row per payee name: first and last extract run and date seen). Only a build whose stop checks all pass writes it; a rerun of the same extract run moves `last_seen` and adds nothing; a failed build writes nothing. The warn check "New payee names since the last build" lists names no passing build of an earlier extract run has seen (it replaced `data/payee_names.txt`, which every build overwrote, failed or not).
- Rules, citations and this document: versioned in git.
- Source schema snapshots: `docs/schemas/catalog_snapshot.json`; changes go to `docs/schemas/drift_history.csv`.

## 11. Schemas

Also saved as CSV in `docs/schemas/` (`source_columns.csv`, `warehouse_columns.csv`, `dashboard_columns.csv`). Origin: **portal** = as published; **source** = other external source; **reference** = from `reference/*.csv`; **derived** = computed by the pipeline; **ops** = run metadata.

### 11.1 Source datasets (as published)

<!-- gen:sources -->
**budget** (yu65-jmmv, 23 columns)

| field_name | display_name | datatype | portal_description | definition |
|---|---|---|---|---|
| category_title | Category Title | Text | (none) | Budget function title (renamed function_name in core) |
| agency_subobject_code | Agency Subobject Code | Text | (none) | Agency-specific spending code; not used (Comptroller sub-object is used) |
| fiscal_year | Fiscal Year | Number | (none) | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| program_code | Program Code | Text | (none) | Budget program code, two digits in core |
| agency_code | Agency Code | Text | (none) | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name | Agency Name | Text | (none) | Agency name as published; in core the code suffix the portal adds in some years is removed |
| unit_code | Unit Code | Text | (none) | Budget unit code within an agency |
| unit_name | Unit Name | Text | (none) | Budget unit name |
| description | Description | Text | (none) | Portal description column; not used |
| program_name | Program Name | Text | (none) | Budget program name |
| subprogram_code | Subprogram Code | Text | (none) | Budget subprogram code |
| comptroller_subobject_name | Comptroller Subobject Name | Text | (none) | Comptroller sub-object name; renamed subobject_name in core |
| subprogram_name | Subprogram Name | Text | (none) | Budget subprogram name |
| object_name | Object Name | Text | (none) | Comptroller object name |
| object_code | Object Code | Text | (none) | Comptroller object code, two digits (for example 08 Contractual services) |
| agency_subobject_name | Agency Subobject Name | Text | (none) | Agency-specific spending code name; not used |
| fund_type_name | Fund Type Name | Text | (none) | Fund type name as published |
| budget | Budget | Number | (none) | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| type | Type | Text | (none) | Budget stage label published by the portal; out of date for recent years so ref.dim_stage is used instead |
| organization_code | Organization Code | Text | (none) | Portal's combined agency-unit-program code |
| comptroller_subobject_code | Comptroller Subobject Code | Text | (none) | Comptroller sub-object (detailed spending) code; renamed subobject_code in core |
| organization_sub_code | Organization Sub Code | Text | (none) | Portal's combined code including subprogram |
| category | Category | Number | (none) | Budget function code (renamed function_code in core) |

**fte** (x8qy-486w, 9 columns)

| field_name | display_name | datatype | portal_description | definition |
|---|---|---|---|---|
| agency_name | Agency Name | Text | (none) | Agency name as published; in core the code suffix the portal adds in some years is removed |
| fiscal_year | Fiscal Year | Number | (none) | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| count | Count | Number | (none) | Budgeted full-time-equivalent positions (renamed fte in core) |
| program_code | Program Code | Text | (none) | Budget program code, two digits in core |
| unit_code | Unit Code | Text | (none) | Budget unit code within an agency |
| agency_code | Agency Code | Text | (none) | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| organization_code | Organization Code | Text | (none) | Portal's combined agency-unit-program code |
| program_name | Program Name | Text | (none) | Budget program name |
| unit_name | Unit Name | Text | (none) | Budget unit name |

**fund** (gy87-e27x, 15 columns)

| field_name | display_name | datatype | portal_description | definition |
|---|---|---|---|---|
| unit_code | Unit Code | Text | (none) | Budget unit code within an agency |
| agency_name | Agency Name | Text | (none) | Agency name as published; in core the code suffix the portal adds in some years is removed |
| agency_code | Agency Code | Text | (none) | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| category | Category | Number | (none) | Budget function code (renamed function_code in core) |
| fiscal_year | Fiscal Year | Number | (none) | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| description | Description | Text | (none) | Portal description column; not used |
| fund_source_name | Fund Source Name | Text | (none) | Fund source name |
| fund_source_code | Fund Source Code | Text | (none) | Fund source code within a fund type |
| fund_type_name | Fund Type Name | Text | (none) | Fund type name as published |
| program_name | Program Name | Text | (none) | Budget program name |
| program_code | Program Code | Text | (none) | Budget program code, two digits in core |
| unit_name | Unit Name | Text | (none) | Budget unit name |
| category_title | Category Title | Text | (none) | Budget function title (renamed function_name in core) |
| organization_code | Organization Code | Text | (none) | Portal's combined agency-unit-program code |
| budget | Budget | Number | (none) | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**grants** (absk-avps, 10 columns)

| field_name | display_name | datatype | portal_description | definition |
|---|---|---|---|---|
| nonprofit | Nonprofit | Text | Whether or not the grantee is a non-profit (503C) entity.  | Y when the portal marks the grantee as a non-profit |
| date | Date | Calendar date | (none) | Portal date column; a placeholder (fiscal year end) rather than the payment or award date; not used |
| fiscalperiod | Fiscal Period | Number | (none) | Accounting period in the grants dataset; not used |
| category | Category | Text | (none) | Grant or Loan |
| description | Description | Text | (none) | Grant or loan purpose as written by the grantor |
| amount | Amount | Number | (none) | Dollars paid, awarded or reported on the row; nominal dollars |
| fiscalyear | Fiscal Year | Number | (none) | Fiscal year in the grants dataset (renamed fiscal_year in core) |
| zipcode | Zip Code | Text | (none) | Grantee ZIP code as published |
| grantee | Grantee | Text | (none) | Recipient of the grant or loan |
| grantor | Grantor | Text | (none) | State agency and program awarding the grant or loan |

**highered** (4mca-332u, 20 columns)

| field_name | display_name | datatype | portal_description | definition |
|---|---|---|---|---|
| program_name | Program Name | Text | (none) | Budget program name |
| category_title | Category Title | Text | (none) | Budget function title (renamed function_name in core) |
| organization_code | Organization Code | Text | (none) | Portal's combined agency-unit-program code |
| budget | Budget | Number | (none) | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| fund_type_name | Fund Type Name | Text | (none) | Fund type name as published |
| agency_subobject_name | Agency Subobject Name | Text | (none) | Agency-specific spending code name; not used |
| agency_subobject_code | Agency Subobject Code | Text | (none) | Agency-specific spending code; not used (Comptroller sub-object is used) |
| comptroller_subobject_name | Comptroller Subobject Name | Text | (none) | Comptroller sub-object name; renamed subobject_name in core |
| comptroller_subobject_code | Comptroller Subobject Code | Text | (none) | Comptroller sub-object (detailed spending) code; renamed subobject_code in core |
| object_name | Object Name | Text | (none) | Comptroller object name |
| object_code | Object Code | Text | (none) | Comptroller object code, two digits (for example 08 Contractual services) |
| subprogram_name | Subprogram Name | Text | (none) | Budget subprogram name |
| subprogram_code | Subprogram Code | Text | (none) | Budget subprogram code |
| program_code | Program Code | Text | (none) | Budget program code, two digits in core |
| unit_name | Unit Name | Text | (none) | Budget unit name |
| unit_code | Unit Code | Text | (none) | Budget unit code within an agency |
| agency_name | Agency Name | Text | (none) | Agency name as published; in core the code suffix the portal adds in some years is removed |
| agency_code | Agency Code | Text | (none) | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fiscal_year | Fiscal Year | Number | (none) | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| category | Category | Number | (none) | Budget function code (renamed function_code in core) |

**payments** (7syw-q4cy, 8 columns)

| field_name | display_name | datatype | portal_description | definition |
|---|---|---|---|---|
| vendor_name | Vendor Name | Text | (none) | Payee name as published; includes businesses and individuals |
| agency_name | Agency Name | Text | (none) | Agency name as published; in core the code suffix the portal adds in some years is removed |
| fiscal_year | Fiscal Year | Number | (none) | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| category | Category | Text | (none) | Payment category as published by the portal |
| date | Date | Calendar date | (none) | Portal date column; a placeholder (fiscal year end) rather than the payment or award date; not used |
| fiscal_period | Fiscal Period | Number | (none) | Accounting period; the portal fills it with a placeholder value so it is not used |
| amount | Amount | Number | (none) | Dollars paid, awarded or reported on the row; nominal dollars |
| vendor_zip | Vendor Zip | Text | (none) | Payee ZIP code as published |
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

**core.fact_budget_all_funds** (826,403 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name | VARCHAR | portal | Agency name as published; in core the code suffix the portal adds in some years is removed |
| unit_code | VARCHAR | portal | Budget unit code within an agency |
| unit_name | VARCHAR | portal | Budget unit name |
| program_code | VARCHAR | portal | Budget program code, two digits in core |
| program_name | VARCHAR | portal | Budget program name |
| object_code | VARCHAR | portal | Comptroller object code, two digits (for example 08 Contractual services) |
| object_name | VARCHAR | portal | Comptroller object name |
| subobject_code | VARCHAR | derived | Comptroller sub-object code without leading zeros |
| subobject_name | VARCHAR | derived | Comptroller sub-object name |
| fund_type | VARCHAR | derived | Fund type (General, Special, Federal, Reimbursable and so on) |
| function_code | INTEGER | derived | Budget function code (from the portal's category) |
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| source_dataset | VARCHAR | derived | Portal dataset the row comes from: yu65-jmmv (operating budget) or 4mca-332u (public higher education, CUR and CR funds) |

**core.fact_budget_highered** (84,446 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name | VARCHAR | portal | Agency name as published; in core the code suffix the portal adds in some years is removed |
| unit_code | VARCHAR | portal | Budget unit code within an agency |
| unit_name | VARCHAR | portal | Budget unit name |
| program_code | VARCHAR | portal | Budget program code, two digits in core |
| program_name | VARCHAR | portal | Budget program name |
| object_code | VARCHAR | portal | Comptroller object code, two digits (for example 08 Contractual services) |
| object_name | VARCHAR | portal | Comptroller object name |
| subobject_code | VARCHAR | derived | Comptroller sub-object code without leading zeros |
| subobject_name | VARCHAR | derived | Comptroller sub-object name |
| fund_type | VARCHAR | derived | Fund type (General, Special, Federal, Reimbursable and so on) |
| function_code | INTEGER | derived | Budget function code (from the portal's category) |
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| source_dataset | VARCHAR | derived | Portal dataset the row comes from: yu65-jmmv (operating budget) or 4mca-332u (public higher education, CUR and CR funds) |

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
| unit_code | VARCHAR | portal | Budget unit code within an agency |
| unit_name | VARCHAR | portal | Budget unit name |
| program_code | VARCHAR | portal | Budget program code, two digits in core |
| program_name | VARCHAR | portal | Budget program name |

**core.fact_grant** (23,085 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| grantor | VARCHAR | portal | State agency and program awarding the grant or loan |
| grantee | VARCHAR | portal | Recipient of the grant or loan |
| category | VARCHAR | portal | Grant or Loan |
| nonprofit | VARCHAR | portal | Y when the portal marks the grantee as a non-profit |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| description | VARCHAR | portal | Grant or loan program description as the grantor published it (free text, as listed) |
| zipcode | VARCHAR | portal | Grantee ZIP code as published |

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
| record_date | DATE | portal | The portal's date column as a date: a record date (Jan 1 of a year, sometimes of the next year), not the payment date; used only by the payment screen's windows |

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
| record_date | DATE | portal | The portal's date column as a date: a record date (Jan 1 of a year, sometimes of the next year), not the payment date; used only by the payment screen's windows |
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

**mart.d_all_funds** (11 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| operating_budget | DOUBLE | derived | Operating budget, all funds, from the operating budget dataset (yu65-jmmv) only: the figure every other budget view uses; nominal dollars |
| public_higher_education | DOUBLE | derived | Operating budget of R13 Morgan State, R14 St. Mary's College, R30 University System of Maryland and R95 Baltimore City Community College (4mca-332u, CUR and CR funds), which yu65-jmmv leaves out; nominal dollars |
| all_funds_including_higher_education | DOUBLE | derived | Operating budget plus public higher education: the all-funds total including public higher education, a separate labeled figure that no GMI savings baseline uses |
| label | VARCHAR | derived | How the all-funds figure must be labeled wherever it is shown |
| source_datasets | VARCHAR | derived | Portal datasets summed in the row |

**mart.d_area_top** (175 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| area | VARCHAR | derived | One of GMI's six focus areas |
| vendor | VARCHAR | derived | Company name after grouping payee names |
| agencies | BIGINT | derived | Agencies paying the vendor (or with payments in the year) |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |
| rank | BIGINT | derived | Rank of the vendor within its area and year by spend |

**mart.d_bid_list** (30 rows)

| column | type | origin | definition |
|---|---|---|---|
| rank | BIGINT | derived | Rank by FY2026 payments |
| vendor | VARCHAR | derived | Company name after grouping payee names |
| fy2025 | DOUBLE | derived | Payments in FY2025 |
| fy2026 | DOUBLE | derived | Payments in FY2026 |
| agencies | DOUBLE | derived | Agencies paying the vendor (or with payments in the year) |
| low | DOUBLE | derived | Low end of the estimated saving; uses a screening assumption (see Assumptions register) |
| high | DOUBLE | derived | High end of the estimated saving; uses a screening assumption (see Assumptions register) |
| top_agencies | VARCHAR | derived | Three agencies paying the vendor most in FY2026 |

**mart.d_deflator** (20 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| cpi_index | DOUBLE | source | Average of the monthly CPI-U (U.S. city average, all items, not seasonally adjusted, BLS CUUR0000SA0) over the Maryland fiscal year (July-June) |
| cpi_months | BIGINT | source | Months of CPI in the fiscal-year average (12 = complete; fewer = partial year) |
| factor | VARCHAR | derived | Multiplier from nominal dollars of the fiscal year to FY2026 dollars: FY2026 CPI average / that year's CPI average (six-decimal text so the export keeps the precision); real dollars = nominal x factor |
| population | BIGINT | source | Maryland resident population on July 1 at the start of the fiscal year (Census Population Estimates); per-resident dollars = dollars / population |
| source | VARCHAR | source | Where cpi_index and population come from, with the CPI months averaged and the population vintage |

**mart.d_detector_backtest** (24 rows)

| column | type | origin | definition |
|---|---|---|---|
| detector | VARCHAR | derived | Opportunity detector rerun as of an earlier year (Peer gap, Growth above trend, Tail spend, Leverage) |
| as_of_fy | BIGINT | derived | Fiscal year the detector was rerun as of, using only data up to that year |
| next_fy | BIGINT | derived | The following fiscal year, in which the as-of year's units are followed |
| cohort | VARCHAR | derived | Flagged = the detector's own flags in the as-of year; Not flagged = units that passed its size and comparability filters but were not flagged |
| units | BIGINT | derived | Units in the cohort: agency and spending code (Peer gap, Growth), focus area (Tail spend) or private vendor (Leverage) |
| flagged_next | BIGINT | derived | Units of the cohort flagged again by the same detector rerun as of the next year |
| flagged_next_share | DOUBLE | derived | flagged_next / units: the persistence rate for the Flagged cohort, the rate of new flags for Not flagged |
| spend_as_of | DOUBLE | derived | Cohort spending in the as-of year: controllable actual budget (budget detectors) or private payments (payment detectors; for Tail spend the vendors outside the ten largest); nominal dollars |
| spend_next | DOUBLE | derived | The same units' spending in the next year, measured the same way; nominal dollars |
| pooled_change | DOUBLE | derived | spend_next / spend_as_of - 1 over the cohort (blank when spend_as_of is zero); descriptive, not a saving |
| median_change | DOUBLE | derived | Median of the per-unit change from the as-of year to the next, over units with spending in the as-of year |
| units_zero_next | BIGINT | derived | Units with no spending in the next year (dropped or re-coded lines) |

**mart.d_families** (1,257 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| family | VARCHAR | reference | Company that several payee names belong to |
| payee_name | VARCHAR | derived | One payee name grouped into the vendor |
| agencies | BIGINT | derived | Agencies paying the vendor (or with payments in the year) |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |

**mart.d_forecast_backtest** (392 rows)

| column | type | origin | definition |
|---|---|---|---|
| area | VARCHAR | derived | One of GMI's six focus areas |
| method | VARCHAR | derived | Forecast model scored: log-linear trend, naive (last actual), drift (average yearly growth) or the equal-weight combination of those three (scored only, never kept) |
| origin_fy | BIGINT | derived | Last fiscal year of actual spending the model was allowed to see (the forecast origin) |
| horizon | BIGINT | derived | Years ahead of the origin that the forecast looks (1 to 3) |
| forecast_fy | BIGINT | derived | Fiscal year being forecast: origin plus horizon, up to FY2027 (years after the last actual are scored against the State's plan) |
| target | VARCHAR | derived | What the forecast is scored against: actual (spending up to the last actual year) or plan (the State's own budget figure for FY2026 and FY2027, which is not an outcome) |
| outcome | DOUBLE | derived | Dollars the forecast is scored against: actual spending, or the State's plan when target is plan |
| forecast | DOUBLE | derived | The model's forecast for that year, in dollars, using only actual years up to the origin (never the plan) |
| abs_error | DOUBLE | derived | Absolute forecast error in dollars |
| ape | DOUBLE | derived | Absolute percentage error: absolute error divided by the outcome |
| mase | DOUBLE | derived | Mean absolute scaled error: absolute error divided by the mean one-step naive error inside the origin's own training years; above 1 is worse than the naive baseline's in-sample error |
| p10 | DOUBLE | derived | 10th percentile of the bootstrap range simulated at that origin, in dollars |
| p50 | DOUBLE | derived | Median of the bootstrap range simulated at that origin, in dollars |
| p90 | DOUBLE | derived | 90th percentile of the bootstrap range simulated at that origin, in dollars |
| covered | BOOLEAN | derived | True when the outcome fell inside the p10 to p90 range (a range meant to cover 80%) |
| interval_score | DOUBLE | derived | Interval score of the p10 to p90 range in dollars (Gneiting and Raftery 2007): its width plus 10 times how far the outcome fell outside it; lower is better |

**mart.d_forecast_calibration** (8 rows)

| column | type | origin | definition |
|---|---|---|---|
| area | VARCHAR | derived | One of GMI's six focus areas |
| method | VARCHAR | derived | The area's chosen forecast model (the kept model of each area for the All areas row) |
| scored | BIGINT | derived | Rolling-backtest forecasts of actual spending scored for the area's chosen model |
| covered_share | DOUBLE | derived | Share of those forecasts whose actual spending fell inside the published p10 to p90 range |
| nominal | DOUBLE | derived | The share the range is meant to cover (0.8 for p10 to p90) |
| widen_by | DOUBLE | derived | Pooled factor by which the ranges would have needed to be wider (around the median, on the log scale) to cover the nominal share in the backtest; 1 is calibrated; measured in-sample on few points, so a size of the problem, not a validated correction |

**mart.d_forecast_model** (7 rows)

| column | type | origin | definition |
|---|---|---|---|
| area | VARCHAR | derived | One of GMI's six focus areas |
| method | VARCHAR | derived | Forecast model chosen by the backtest |
| growth | DOUBLE | derived | Annual growth rate of the chosen model |
| backtest_mape | DOUBLE | derived | Mean absolute percentage error of the chosen model (fit FY2017-2022; scored FY2023-2025) |
| trend_mape | DOUBLE | derived | Backtest error of the log-linear trend model |
| naive_mape | DOUBLE | derived | Backtest error of the naive (last actual) model |
| drift_mape | DOUBLE | derived | Backtest error of the drift model |
| baseline_fy2025 | DOUBLE | derived | FY2025 actual spending in the area |
| gmi_recurring | DOUBLE | source | Recurring savings GMI reported for the area |
| gmi_rate | DOUBLE | derived | gmi_recurring divided by baseline_fy2025 |
| gmi_note | VARCHAR | source | Which reported items make up gmi_recurring |
| gf_share | DOUBLE | derived | General Fund share of the area's FY2025 spending |

**mart.d_master_quality** (5 rows)

| column | type | origin | definition |
|---|---|---|---|
| measure | VARCHAR | reference | Name of the quality measure |
| value | VARCHAR | derived | Measured value |
| ok | BIGINT | derived | True when the measure meets its target |

**mart.d_multi** (216 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| vendor | VARCHAR | derived | Company name after grouping payee names |
| area | VARCHAR | derived | One of GMI's six focus areas |
| agencies | BIGINT | derived | Agencies paying the vendor (or with payments in the year) |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |
| payee_names | BIGINT | derived | Payee names grouped into the vendor |
| agency_codes | VARCHAR | derived | Budget agency codes that paid the vendor that year (comma-separated) |
| agencies_prior | BIGINT | derived | Agencies that paid the vendor the year before |
| spend_prior | DOUBLE | derived | Spend with the vendor the year before |

**mart.d_multi_basis** (10 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| basis | VARCHAR | derived | Counting basis: company and budget agency (this dashboard) or payee name and payment account (Maryland Spend Lens) |
| vendors | BIGINT | derived | Distinct payees in the year |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |

**mart.d_opps** (396 rows)

| column | type | origin | definition |
|---|---|---|---|
| opp_id | VARCHAR | derived | Opportunity identifier |
| detector | VARCHAR | derived | Screening rule that found the opportunity |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | VARCHAR | derived | Agency name shown on the dashboard |
| area | VARCHAR | derived | One of GMI's six focus areas |
| spending_code | VARCHAR | derived | Comptroller sub-object name (with code) shown on the dashboard |
| baseline | DOUBLE | derived | Spending the screening percentage is applied to |
| low | DOUBLE | derived | Low end of the estimated saving; uses a screening assumption (see Assumptions register) |
| high | DOUBLE | derived | High end of the estimated saving; uses a screening assumption (see Assumptions register) |
| evidence | VARCHAR | derived | Plain-language reason the detector flagged the row |
| likely | DOUBLE | derived | Midpoint of low and high |

**mart.d_payment_screen** (8 rows)

| column | type | origin | definition |
|---|---|---|---|
| group_id | VARCHAR | derived | Identifier of a flagged group of payment records (hash of the rule and its grouping keys) |
| rule | VARCHAR | reference | Name of the mapping or scope rule |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | VARCHAR | derived | Agency name shown on the dashboard |
| agency_raw | VARCHAR | portal | Paying agency name as published (most common name in the group); agency is the pipeline's cleaned name (agency_master) |
| vendor | VARCHAR | derived | Company name after grouping payee names |
| payee_type | VARCHAR | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| first_date | DATE | derived | Earliest record date in the group |
| last_date | DATE | derived | Latest record date in the group |
| n | BIGINT | derived | Number of payment records in the group |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| total_amount | DOUBLE | derived | Dollars of all records in the group(s) |
| review_amount | DOUBLE | derived | Dollars a review could recover if confirmed: every copy after the first for duplicates and repeated lines; 0 for split purchases (a compliance lead) |
| payee_names | BIGINT | derived | Distinct payee names (as paid) in the group |
| zips | BIGINT | derived | Distinct payee ZIP codes in the group |
| also_flagged_under | VARCHAR | derived | Other screen rules that flag the same agency, vendor and year (records are never in two groups; this labels the overlap) |
| date_grain | VARCHAR | derived | Grain of the payments' dates in the screened years: annual (record dates, one row per agency, payee and year) or payment (payment-level dates) |
| confidence_score | INTEGER | derived | Confidence points from rules fixed before measuring (config payment_screen.confidence): +1 not a round amount, -1 a multiple of $1,000, +1 one paying unit, -1 several paying units, -1 same amount in another year, -1 under $5,000, -1 non-profit payee |
| confidence | VARCHAR | derived | Confidence that the lead is a real duplicate: high (score >= 1), medium (0) or low (<= -1); low for split purchases |
| review_status | VARCHAR | derived | Evidence review from the data alone: unreviewed, confirmed_duplicate_in_source (records identical in every published field), likely_legitimate (a pattern of equal payments from several units) or needs_records; never a confirmed overpayment |
| review_note | VARCHAR | derived | One-line evidence note behind review_status (paying units, ZIPs, the vendor's other payments by the agency, equal payments from other units) |

**mart.d_payment_screen_summary** (15 rows)

| column | type | origin | definition |
|---|---|---|---|
| rule | VARCHAR | reference | Name of the mapping or scope rule |
| rule_order | INTEGER | derived | Display order of the rule |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| groups | BIGINT | derived | Number of flagged groups |
| records | HUGEINT | derived | Number of payment records in the flagged groups |
| total_amount | DOUBLE | derived | Dollars of all records in the group(s) |
| review_amount | DOUBLE | derived | Dollars a review could recover if confirmed: every copy after the first for duplicates and repeated lines; 0 for split purchases (a compliance lead) |
| date_grain | VARCHAR | derived | Grain of the payments' dates in the screened years: annual (record dates, one row per agency, payee and year) or payment (payment-level dates) |
| status | VARCHAR | derived | Whether the rule can be measured at the data's date grain: Measured, Not measurable (split rule on annual records) or Not applied |
| lever_fy | INTEGER | reference | Payments year whose flagged review dollars the Calculator lever uses (config/assumptions.yaml payment_screen.lever.fy) |
| lever_rate_low | DOUBLE | derived | Calculator lever rate, low case: lower Wilson bound of the measured confirmation rate; 0 when not measurable (rate_basis) |
| lever_rate_likely | DOUBLE | derived | Calculator lever rate, likely case: the measured confirmation rate; 0 when not measurable (rate_basis) |
| lever_rate_high | DOUBLE | derived | Calculator lever rate, high case: upper Wilson bound of the measured confirmation rate; 0 when not measurable (rate_basis) |
| measured_confirmation_rate | DOUBLE | derived | Share of reviewed leads confirmed by the evidence review; blank when the review confirms none (not measurable without payment records) |
| rate_basis | VARCHAR | derived | How the confirmation rate and the lever rates were set: the measured share with its Wilson interval, or 'not measurable without payment records' (lever 0) |
| reviewed_leads | BIGINT | derived | Payment leads the evidence review reached a status for (not unreviewed) |
| confirmed_leads | BIGINT | derived | Payment leads the evidence review marked confirmed_duplicate_in_source |

**mart.d_plan50** (28 rows)

| column | type | origin | definition |
|---|---|---|---|
| step | BIGINT | derived | Order of the step in the path to $50M |
| action | VARCHAR | derived | Action in the path to $50M |
| basis | VARCHAR | derived | How the step's saving is calculated |
| saving | DOUBLE | derived | Annual saving of the step in dollars |
| low | DOUBLE | derived | Low end of the estimated saving; uses a screening assumption (see Assumptions register) |
| high | DOUBLE | derived | High end of the estimated saving; uses a screening assumption (see Assumptions register) |
| tab | VARCHAR | derived | Dashboard tab the row links to |
| cumulative | DOUBLE | derived | Running total of savings |

**mart.d_rec_status** (6 rows)

| column | type | origin | definition |
|---|---|---|---|
| rec | BIGINT | derived | Recommendation number (1-6) |
| title | VARCHAR | derived | Recommendation title |
| status | VARCHAR | derived | Status of the recommendation |
| progress | VARCHAR | derived | Key number showing progress |
| tab | VARCHAR | derived | Dashboard tab the row links to |
| previous | VARCHAR | ops | Progress text in the previous run |

**mart.d_savings** (18 rows)

| column | type | origin | definition |
|---|---|---|---|
| saving_id | VARCHAR | reference | Reported saving identifier (S01-S18) |
| workstream | VARCHAR | reference | GMI workstream the saving belongs to |
| item | VARCHAR | reference | Saving as GMI describes it |
| reported_low | DOUBLE | source | Low end of the reported saving in dollars (GMI Final Report) |
| reported_high | DOUBLE | source | High end of the reported saving in dollars (GMI Final Report) |
| type | VARCHAR | reference | Kind of saving GMI reported: year over year, one-time, cost avoidance |
| status | VARCHAR | reference | Status GMI gave the item |
| count | VARCHAR | reference | Number of contracts or items GMI reported in the saving (text) |
| check_id | VARCHAR | derived | Reported saving whose payments are checked |
| check_note | VARCHAR | reference | How the payment check is defined |
| source | VARCHAR | reference | Citation for the reported saving |
| source_url | VARCHAR | source | Link to the citation |
| source_page | VARCHAR | source | Page of the citation |
| source_quote | VARCHAR | source | Verbatim quote supporting the figure |

**mart.d_savings_status** (12 rows)

| column | type | origin | definition |
|---|---|---|---|
| check_id | VARCHAR | derived | Reported saving whose payments are checked |
| item | VARCHAR | reference | Saving as GMI describes it |
| reported | DOUBLE | source | Reported saving midpoint in dollars |
| before | DOUBLE | derived | Matching payments in FY2025 |
| after | DOUBLE | derived | Matching payments in FY2026 |
| status | VARCHAR | derived | Whether the reported saving is seen in payments (Seen, Partly seen, Not seen yet, Payments fell, Payments did not fall) |
| previous_status | VARCHAR | ops | Status in the previous run |
| changed | BOOLEAN | ops | True when the status changed since the previous run |

**mart.d_source_issues** (2 rows)

| column | type | origin | definition |
|---|---|---|---|
| issue_id | VARCHAR | derived | Source issue identifier: 'SRC-<fiscal year>-<agency code>' |
| issue | VARCHAR | derived | Short description of the data-publication issue |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | VARCHAR | derived | Agency name shown on the dashboard |
| agency_raw | VARCHAR | portal | Paying agency name as published (most common name in the group); agency is the pipeline's cleaned name (agency_master) |
| records | BIGINT | derived | Records in the second (off-year dated) block of the agency's fiscal year |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| identical_records | HUGEINT | derived | Records of the second block equal to a first-block record in payee name, ZIP and amount (matched one to one) |
| identical_amount | DOUBLE | derived | Dollars of the identical records |
| screen_groups | BIGINT | derived | Payment-screen groups moved here from the leads (repeated annual lines inside this issue) |
| screen_records | HUGEINT | derived | Payment records in those groups |
| screen_review_amount | DOUBLE | derived | Review dollars those groups carried as leads before they were recognised as a publication issue (every copy after the first) |
| evidence | VARCHAR | derived | The numbers behind the issue: both blocks' records and dollars, identical records, screen groups |
| verified_against | VARCHAR | reference | Where the issue was checked at the source (config source_issues); blank when not yet verified |
| verified_on | DATE | reference | Date the issue was checked at the source (docs/reconciliation/crosschecks_2026-11-10.csv) |
| status | VARCHAR | reference | Whether the issue is confirmed in the published source and what to do next |

**mart.d_vendor_moves** (40 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | VARCHAR | derived | Company name after grouping payee names |
| fy2024 | DOUBLE | derived | Payments in FY2024 |
| fy2025 | DOUBLE | derived | Payments in FY2025 |
| fy2026 | DOUBLE | derived | Payments in FY2026 |
| change | DOUBLE | derived | FY2026 minus FY2025 payments |
| agencies | BIGINT | derived | Agencies paying the vendor (or with payments in the year) |

**mart.d_vendor_names** (267 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | VARCHAR | derived | Company name after grouping payee names |
| payee_name | VARCHAR | derived | One payee name grouped into the vendor |
| fy2026 | DOUBLE | derived | Payments in FY2026 |

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

**mart.f_area** (6,433 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| area | VARCHAR | derived | One of GMI's six focus areas |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |
| payee_spend | DOUBLE | derived | Payments to payees assigned to the focus area |

**mart.f_budget_vs_pay** (874 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| general_funds | DOUBLE | derived | Operating budget paid from the General Fund |
| special_funds | DOUBLE | derived | Operating budget paid from special funds (dedicated State revenue) |
| federal_funds | DOUBLE | derived | Operating budget paid from federal funds, including the ARRA and COVID federal fund types |
| payments | DOUBLE | derived | Payments to all payees in the year (vendor payments dataset, 7syw-q4cy) |
| paid_to_government | DOUBLE | derived | Payments to government payees (counties, cities, school systems, State and federal bodies) per reference/payee_type_rules.csv |
| paid_to_others | DOUBLE | derived | Payments to all other payees: businesses, non-profits, health care, education and financial institutions, utilities and individuals |
| partial_year | BOOLEAN | derived | True for the latest payments year while it is still being updated monthly |

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

**mart.f_concentration** (114 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| area | VARCHAR | derived | One of GMI's six focus areas |
| vendors | BIGINT | derived | Distinct payees in the year |
| spend | DOUBLE | derived | Dollars spent (budget actuals or payments) |
| top5_share | DOUBLE | derived | Share of the area's private-vendor spend held by its five largest vendors |
| hhi | DOUBLE | derived | Herfindahl-Hirschman Index: sum of squared percentage shares of spend (0-10,000; above 1,800 is highly concentrated under the 2023 DOJ/FTC Merger Guidelines) |

**mart.f_forecast** (105 rows)

| column | type | origin | definition |
|---|---|---|---|
| area | VARCHAR | derived | One of GMI's six focus areas |
| fiscal_year | BIGINT | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| kind | VARCHAR | derived | Actual, forecast or plan |
| value | DOUBLE | derived | Actual or forecast spending in dollars |
| p10 | DOUBLE | derived | 10th percentile of the bootstrap forecast |
| p50 | DOUBLE | derived | Median of the bootstrap forecast |
| p90 | DOUBLE | derived | 90th percentile of the bootstrap forecast |
| plan | DOUBLE | derived | Spending after GMI's reported savings rate |

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

**mart.f_fund_source** (10,617 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fund_type | VARCHAR | derived | Fund type (General, Special, Federal, Reimbursable and so on) |
| fund_source_code | VARCHAR | portal | Fund source code within a fund type |
| fund_source_name | VARCHAR | portal | Fund source name |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**mart.f_grants** (23,085 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| grantor | VARCHAR | portal | State agency and program awarding the grant or loan |
| grantee | VARCHAR | portal | Recipient of the grant or loan |
| description | VARCHAR | portal | Grant or loan program description as the grantor published it (free text, as listed) |
| category | VARCHAR | derived | Grant or Loan, from the dataset's category code (G/L) |
| nonprofit | VARCHAR | portal | Y when the portal marks the grantee as a non-profit |
| zipcode | VARCHAR | portal | Grantee ZIP code as published |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| in_payments | BOOLEAN | derived | True when the grantee is also a payee in the payments data that fiscal year (names compared without case, spaces or punctuation) |
| paid_same_fy | DOUBLE | derived | Payments to the grantee that fiscal year (all agencies) when in_payments is true |

**mart.f_object** (7,817 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| object_name | VARCHAR | portal | Comptroller object name |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| controllable | DOUBLE | derived | Controllable purchases: contractual services, supplies, equipment, rent and similar spending agencies can renegotiate, per reference/controllable_rules.csv |

**mart.f_overlap** (11 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| general_funds | DOUBLE | derived | Operating budget paid from the General Fund |
| special_funds | DOUBLE | derived | Operating budget paid from special funds (dedicated State revenue) |
| federal_funds | DOUBLE | derived | Operating budget paid from federal funds, including the ARRA and COVID federal fund types |
| payments | DOUBLE | derived | Payments to all payees in the year (vendor payments dataset, 7syw-q4cy) |
| paid_to_government | DOUBLE | derived | Payments to government payees (counties, cities, school systems, State and federal bodies) per reference/payee_type_rules.csv |
| paid_to_others | DOUBLE | derived | Payments to all other payees: businesses, non-profits, health care, education and financial institutions, utilities and individuals |
| partial_year | BOOLEAN | derived | True for the latest payments year while it is still being updated monthly |
| grants | DOUBLE | derived | Grants dataset rows with category Grant |
| loans | DOUBLE | derived | Grants dataset rows with category Loan |
| grants_and_loans | DOUBLE | derived | All grants dataset rows (grants and loans) |
| grants_in_payments | DOUBLE | derived | Grant and loan dollars whose grantee is also a payee in the payments data that year |
| grants_in_payments_share | DOUBLE | derived | Share of grant and loan dollars whose grantee is also a payee that year (name match; a lower bound on overlap) |
| grant_rows | BIGINT | derived | Rows in the grants dataset that year |
| grant_rows_in_payments | BIGINT | derived | Grant rows whose grantee is also a payee that year |
| payments_to_budget_share | DOUBLE | derived | Payments divided by the operating budget at its latest stage (a cross-check; the two measure different things) |

**mart.f_payee_type** (5,913 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| payee_type | VARCHAR | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| function_name | VARCHAR | derived | Budget function title (from the portal's category_title) |
| paid | DOUBLE | derived | Payments in dollars |
| vendors | BIGINT | derived | Distinct payees in the year |

**mart.f_program** (6,648 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| unit_name | VARCHAR | portal | Budget unit name |
| program_code | VARCHAR | portal | Budget program code, two digits in core |
| program_name | VARCHAR | portal | Budget program name |
| budget | DOUBLE | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**mart.f_savings_check** (1,625 rows)

| column | type | origin | definition |
|---|---|---|---|
| check_id | VARCHAR | derived | Reported saving whose payments are checked |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| paid | DOUBLE | derived | Payments in dollars |

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

**mart.f_vendor_detail** (7,260 rows)

| column | type | origin | definition |
|---|---|---|---|
| vendor | VARCHAR | derived | Company name after grouping payee names |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| paid | DOUBLE | derived | Payments in dollars |

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

**mart.measures** (14 rows)

| column | type | origin | definition |
|---|---|---|---|
| table | VARCHAR | derived | Dashboard table the measure belongs to |
| measure | VARCHAR | derived | Column name of the dashboard measure |
| definition | VARCHAR | derived | What the dashboard measure means |
| grouped_by | VARCHAR | derived | Grain the measure is grouped by |
| higher_is | VARCHAR | derived | Whether a higher value is better, worse or neutral |

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

**mart.pipeline_runs** (5 rows)

| column | type | origin | definition |
|---|---|---|---|
| run_id | VARCHAR | ops | Pipeline run identifier, UTC timestamp YYYYMMDDTHHMMSSZ |
| started_utc | VARCHAR | ops | When the run started (UTC) |
| seconds | DOUBLE | ops | Run duration in seconds |
| status | VARCHAR | ops | Run or source status |
| published | BIGINT | ops | True when the run's outputs were published |
| checks | DOUBLE | ops | Number of checks run |
| passed | DOUBLE | ops | Checks passed |
| warnings | DOUBLE | ops | Checks that warned |
| failed | DOUBLE | ops | Checks that failed |
| repairs | BIGINT | ops | Datasets re-downloaded by self-healing |
| payment_rows | BIGINT | ops | Payment rows in the run |
| budget_rows | BIGINT | ops | Budget rows in the run |
| mode | VARCHAR | ops | Run mode (full, freshness reuse, test fault) |

**mart.run_checks** (96 rows)

| column | type | origin | definition |
|---|---|---|---|
| run_id | VARCHAR | ops | Pipeline run identifier, UTC timestamp YYYYMMDDTHHMMSSZ |
| stage | VARCHAR | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| check | VARCHAR | ops | Check description |
| status | VARCHAR | ops | pass, warn or fail |
| detail | VARCHAR | ops | Numbers behind the check result |

**mart.sources** (6 rows)

| column | type | origin | definition |
|---|---|---|---|
| source | VARCHAR | derived | Short name of the source dataset |
| dataset_id | VARCHAR | ops | Portal four-by-four identifier |
| title | VARCHAR | derived | Dataset title used on the dashboard |
| use | VARCHAR | derived | What the dataset contributes to the tracker |
| portal_name | VARCHAR | ops | Dataset title as the portal publishes it |
| portal_updated | VARCHAR | ops | Date the portal data last changed |
| rows_portal | BIGINT | ops | Rows the portal reported |
| rows_downloaded | BIGINT | ops | Rows in the downloaded file |
| years | VARCHAR | derived | Fiscal years used |
| reconciled | BIGINT | ops | True when downloaded rows equal the portal's count |

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

**mart.stage_evidence** (4 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | BIGINT | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| file_label | VARCHAR | portal | Stage label the portal file assigned to the year |
| official_stage | VARCHAR | reference | Stage DBM's budget books assign to the year |
| evidence | VARCHAR | source | Where in DBM's budget books the stage is confirmed |
| evidence_url | VARCHAR | source | Link to the evidence document |
| programs_compared | DOUBLE | derived | Programs compared between the portal file and DBM's books |
| programs_exact | DOUBLE | derived | Programs whose totals match DBM's books exactly |
| file_total | BIGINT | derived | Portal file total for the year |
| dbm_actual_total | DOUBLE | source | Actual total printed in DBM's budget books |
| note | VARCHAR | reference | Explanation of the rule or row |

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

**mart.v_payment_screen_rows** (410 rows)

| column | type | origin | definition |
|---|---|---|---|
| group_id | VARCHAR | derived | Identifier of a flagged group of payment records (hash of the rule and its grouping keys) |
| rule | VARCHAR | derived | Payment screen rule: Possible duplicate, Repeated annual line or Possible split purchase (docs/models/payment_screen.md) |
| record_key | VARCHAR | derived | Identifier of one payment record (hash of its published fields plus a counter for identical records) |
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_key | VARCHAR | derived | Budget agency code of the payment; the agency name as paid when the payment is not matched to an agency |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency_name_as_paid | VARCHAR | derived | Agency name exactly as it appears in the payments dataset |
| agency_code_as_paid | VARCHAR | portal | Paying unit's code as published (the portal's category column, e.g. 602 = DGS capital), used to tell two paying units apart |
| vendor | VARCHAR | derived | Company name after grouping payee names |
| vendor_key | VARCHAR | derived | Normalized payee name the vendor grouping and the name rules are matched on (ref.map_payee_vendor) |
| payee_type | VARCHAR | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| vendor_name_as_paid | VARCHAR | derived | Payee name exactly as published in payments |
| vendor_zip | VARCHAR | portal | Payee ZIP code as published |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| record_date | DATE | portal | The portal's date column as a date: a record date (Jan 1 of a year, sometimes of the next year), not the payment date; used only by the payment screen's windows |
| date_grain | VARCHAR | derived | Grain of the payments' dates in the screened years: annual (record dates, one row per agency, payee and year) or payment (payment-level dates) |
| source_issue_id | VARCHAR | derived | Source issue the record's group belongs to ('SRC-<fiscal year>-<agency code>'), blank for payment leads; such groups go to d_source_issues, never to d_payment_screen |

**mart.v_purchase** (341,180 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | INTEGER | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | VARCHAR | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| vendor | VARCHAR | derived | Company name after grouping payee names |
| vendor_name | VARCHAR | portal | Payee name as published |
| area | VARCHAR | derived | Payee-name focus area, or 'Other goods & services' |
| amount | DOUBLE | portal | Dollars paid, awarded or reported on the row; nominal dollars |

**mart.vendor_agency_year** (387,339 rows)

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

**ops.check_coverage** (96 rows)

| column | type | origin | definition |
|---|---|---|---|
| check | VARCHAR | ops | Check description |
| layer | VARCHAR | ops | Database layer the check ran on (raw, core, ref, mart) |
| tables | VARCHAR | derived | Warehouse tables the check's queries read (recorded by src/pipeline/checks.py), space-separated |

**ops.check_result** (96 rows)

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

**ops.lineage** (268 rows)

| column | type | origin | definition |
|---|---|---|---|
| table_name | VARCHAR | derived | Warehouse table (schema.name) created by the build |
| depends_on | VARCHAR | derived | A table the build read to create table_name (named in its CREATE statement, or read by the Python model that built it) |

**ops.payee_name_seen** (61,798 rows)

| column | type | origin | definition |
|---|---|---|---|
| payee_name | VARCHAR | ops | Payee name exactly as paid (ref.map_payee_vendor.payee), one row per name ever seen by a passing build |
| first_seen_run_id | VARCHAR | ops | Extract run of the first build that passed its stop checks and saw this payee name |
| first_seen_date | VARCHAR | ops | UTC date of that extract run (YYYY-MM-DD) |
| last_seen_run_id | VARCHAR | ops | Extract run of the latest passing build that saw this payee name |
| last_seen_date | VARCHAR | ops | UTC date of that extract run (YYYY-MM-DD) |

**ops.portal_year_total** (81 rows)

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

**ops.source_snapshot** (6 rows)

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

**raw.highered** (84,446 rows)

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
| organization_code | VARCHAR | portal | Portal's combined agency-unit-program code |
| category | VARCHAR | portal | Budget function code (renamed function_code in core) |
| category_title | VARCHAR | portal | Budget function title (renamed function_name in core) |
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

**ref.column_dictionary** (422 rows)

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
| evidence | VARCHAR | reference | Source or reasoning behind the mapping decision |

**ref.payment_agency_rule** (21 rows)

| column | type | origin | definition |
|---|---|---|---|
| rule | VARCHAR | reference | Name of the mapping or scope rule |
| payment_name_pattern | VARCHAR | reference | Regular expression matching payment agency names |
| target | VARCHAR | reference | Agency code the rule maps to |
| note | VARCHAR | reference | Explanation of the rule or row |

**ref.stage_evidence** (4 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | VARCHAR | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| file_label | VARCHAR | portal | Stage label the portal file assigned to the year |
| official_stage | VARCHAR | reference | Stage DBM's budget books assign to the year |
| evidence | VARCHAR | source | Where in DBM's budget books the stage is confirmed |
| evidence_url | VARCHAR | source | Link to the evidence document |
| programs_compared | VARCHAR | derived | Programs compared between the portal file and DBM's books |
| programs_exact | VARCHAR | derived | Programs whose totals match DBM's books exactly |
| file_total | VARCHAR | derived | Portal file total for the year |
| dbm_actual_total | VARCHAR | source | Actual total printed in DBM's budget books |
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

**d_all_funds** (11 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| operating_budget | number | derived | Operating budget, all funds, from the operating budget dataset (yu65-jmmv) only: the figure every other budget view uses; nominal dollars |
| public_higher_education | number | derived | Operating budget of R13 Morgan State, R14 St. Mary's College, R30 University System of Maryland and R95 Baltimore City Community College (4mca-332u, CUR and CR funds), which yu65-jmmv leaves out; nominal dollars |
| all_funds_including_higher_education | number | derived | Operating budget plus public higher education: the all-funds total including public higher education, a separate labeled figure that no GMI savings baseline uses |
| label | text | derived | How the all-funds figure must be labeled wherever it is shown |
| source_datasets | text | derived | Portal datasets summed in the row |

**d_area_top** (175 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| area | text | derived | One of GMI's six focus areas |
| vendor | text | derived | Company name after grouping payee names |
| agencies | number | derived | Agencies paying the vendor (or with payments in the year) |
| spend | number | derived | Dollars spent (budget actuals or payments) |
| rank | number | derived | Rank of the vendor within its area and year by spend |

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

**d_deflator** (20 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| cpi_index | number | source | Average of the monthly CPI-U (U.S. city average, all items, not seasonally adjusted, BLS CUUR0000SA0) over the Maryland fiscal year (July-June) |
| cpi_months | number | source | Months of CPI in the fiscal-year average (12 = complete; fewer = partial year) |
| factor | number | derived | Multiplier from nominal dollars of the fiscal year to FY2026 dollars: FY2026 CPI average / that year's CPI average (six-decimal text so the export keeps the precision); real dollars = nominal x factor |
| population | number | source | Maryland resident population on July 1 at the start of the fiscal year (Census Population Estimates); per-resident dollars = dollars / population |
| source | text | source | Where cpi_index and population come from, with the CPI months averaged and the population vintage |

**d_families** (1,257 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| family | text | reference | Company that several payee names belong to |
| payee_name | text | derived | One payee name grouped into the vendor |
| agencies | number | derived | Agencies paying the vendor (or with payments in the year) |
| spend | number | derived | Dollars spent (budget actuals or payments) |

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

**d_multi** (216 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| vendor | text | derived | Company name after grouping payee names |
| area | text | derived | Payee-name focus area, or 'Other goods & services' |
| agencies | number | derived | Agencies paying the vendor (or with payments in the year) |
| spend | number | derived | Dollars spent (budget actuals or payments) |
| payee_names | number | derived | Payee names grouped into the vendor |
| agency_codes | text | derived | Budget agency codes that paid the vendor that year (comma-separated) |
| agencies_prior | number | derived | Agencies that paid the vendor the year before |
| spend_prior | number | derived | Spend with the vendor the year before |

**d_multi_basis** (10 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| basis | text | derived | Counting basis: company and budget agency (this dashboard) or payee name and payment account (Maryland Spend Lens) |
| vendors | number | derived | Distinct payees in the year |
| spend | number | derived | Dollars spent (budget actuals or payments) |

**d_opps** (396 rows)

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

**d_payment_screen** (8 rows)

| column | type | origin | definition |
|---|---|---|---|
| group_id | text | derived | Identifier of a flagged group of payment records (hash of the rule and its grouping keys) |
| rule | text | derived | Payment screen rule: Possible duplicate, Repeated annual line or Possible split purchase (docs/models/payment_screen.md) |
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | text | derived | Agency's cleaned name from agency_master (budget name, or the payment data's own name for payment-only codes); agency_raw keeps the name as paid |
| agency_raw | text | portal | Paying agency name as published (most common name in the group); agency is the pipeline's cleaned name (agency_master) |
| vendor | text | derived | Company name after grouping payee names; 'Payee not named (may be an individual)' when the payee type is Business or other and no payee name looks like an organization |
| payee_type | text | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| first_date | text | derived | Earliest record date in the group |
| last_date | text | derived | Latest record date in the group |
| n | number | derived | Number of payment records in the group |
| amount | number | derived | Dollars of each record in the group (equal for duplicates and repeated lines); blank for split purchases |
| total_amount | number | derived | Dollars of all records in the group(s) |
| review_amount | number | derived | Dollars a review could recover if confirmed: every copy after the first for duplicates and repeated lines; 0 for split purchases (a compliance lead) |
| payee_names | number | derived | Distinct payee names (as paid) in the group |
| zips | number | derived | Distinct payee ZIP codes in the group |
| also_flagged_under | number | derived | Other screen rules that flag the same agency, vendor and year (records are never in two groups; this labels the overlap) |
| date_grain | text | derived | Grain of the payments' dates in the screened years: annual (record dates, one row per agency, payee and year) or payment (payment-level dates) |
| confidence_score | number | derived | Confidence points from rules fixed before measuring (config payment_screen.confidence): +1 not a round amount, -1 a multiple of $1,000, +1 one paying unit, -1 several paying units, -1 same amount in another year, -1 under $5,000, -1 non-profit payee |
| confidence | text | derived | Confidence that the lead is a real duplicate: high (score >= 1), medium (0) or low (<= -1); low for split purchases |
| review_status | text | derived | Evidence review from the data alone: unreviewed, confirmed_duplicate_in_source (records identical in every published field), likely_legitimate (a pattern of equal payments from several units) or needs_records; never a confirmed overpayment |
| review_note | text | derived | One-line evidence note behind review_status (paying units, ZIPs, the vendor's other payments by the agency, equal payments from other units) |

**d_payment_screen_summary** (15 rows)

| column | type | origin | definition |
|---|---|---|---|
| rule | text | derived | Payment screen rule: Possible duplicate, Repeated annual line or Possible split purchase (docs/models/payment_screen.md) |
| rule_order | number | derived | Display order of the rule |
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| groups | number | derived | Number of flagged groups |
| records | number | derived | Number of payment records in the flagged groups |
| total_amount | number | derived | Dollars of all records in the group(s) |
| review_amount | number | derived | Dollars a review could recover if confirmed: every copy after the first for duplicates and repeated lines; 0 for split purchases (a compliance lead) |
| date_grain | text | derived | Grain of the payments' dates in the screened years: annual (record dates, one row per agency, payee and year) or payment (payment-level dates) |
| status | text | derived | Whether the rule can be measured at the data's date grain: Measured, Not measurable (split rule on annual records) or Not applied |
| lever_fy | number | reference | Payments year whose flagged review dollars the Calculator lever uses (config/assumptions.yaml payment_screen.lever.fy) |
| lever_rate_low | number | derived | Calculator lever rate, low case: lower Wilson bound of the measured confirmation rate; 0 when not measurable (rate_basis) |
| lever_rate_likely | number | derived | Calculator lever rate, likely case: the measured confirmation rate; 0 when not measurable (rate_basis) |
| lever_rate_high | number | derived | Calculator lever rate, high case: upper Wilson bound of the measured confirmation rate; 0 when not measurable (rate_basis) |
| measured_confirmation_rate | number | derived | Share of reviewed leads confirmed by the evidence review; blank when the review confirms none (not measurable without payment records) |
| rate_basis | text | derived | How the confirmation rate and the lever rates were set: the measured share with its Wilson interval, or 'not measurable without payment records' (lever 0) |
| reviewed_leads | number | derived | Payment leads the evidence review reached a status for (not unreviewed) |
| confirmed_leads | number | derived | Payment leads the evidence review marked confirmed_duplicate_in_source |

**d_plan50** (28 rows)

| column | type | origin | definition |
|---|---|---|---|
| step | number | derived | Order of the step in the path to $50M |
| action | text | derived | Action in the path to $50M |
| basis | text | derived | How the step's saving is calculated |
| saving | number | derived | Annual saving of the step in dollars |
| low | number | derived | Low end of the estimated saving; uses a screening assumption (see Assumptions register) |
| high | number | derived | High end of the estimated saving; uses a screening assumption (see Assumptions register) |
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

**d_source_issues** (2 rows)

| column | type | origin | definition |
|---|---|---|---|
| issue_id | text | derived | Source issue identifier: 'SRC-<fiscal year>-<agency code>' |
| issue | text | derived | Short description of the data-publication issue |
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| agency | text | derived | Agency's cleaned name from agency_master (budget name, or the payment data's own name for payment-only codes); agency_raw keeps the name as paid |
| agency_raw | text | portal | Paying agency name as published (most common name in the group); agency is the pipeline's cleaned name (agency_master) |
| records | number | derived | Records in the second (off-year dated) block of the agency's fiscal year |
| amount | number | derived | Dollars in the second (off-year dated) block of the agency's fiscal year, as published |
| identical_records | number | derived | Records of the second block equal to a first-block record in payee name, ZIP and amount (matched one to one) |
| identical_amount | number | derived | Dollars of the identical records |
| screen_groups | number | derived | Payment-screen groups moved here from the leads (repeated annual lines inside this issue) |
| screen_records | number | derived | Payment records in those groups |
| screen_review_amount | number | derived | Review dollars those groups carried as leads before they were recognised as a publication issue (every copy after the first) |
| evidence | text | derived | The numbers behind the issue: both blocks' records and dollars, identical records, screen groups |
| verified_against | text | reference | Where the issue was checked at the source (config source_issues); blank when not yet verified |
| verified_on | text | reference | Date the issue was checked at the source (docs/reconciliation/crosschecks_2026-11-10.csv) |
| status | text | reference | Whether the issue is confirmed in the published source and what to do next |

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

**f_area** (6,396 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| area | text | derived | One of GMI's six focus areas |
| spend | number | derived | Dollars spent (budget actuals or payments) |
| payee_spend | number | derived | Payments to payees assigned to the focus area |

**f_budget_vs_pay** (874 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| budget | number | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| general_funds | number | derived | Operating budget paid from the General Fund |
| special_funds | number | derived | Operating budget paid from special funds (dedicated State revenue) |
| federal_funds | number | derived | Operating budget paid from federal funds, including the ARRA and COVID federal fund types |
| payments | number | derived | Payments to all payees in the year (vendor payments dataset, 7syw-q4cy) |
| paid_to_government | number | derived | Payments to government payees (counties, cities, school systems, State and federal bodies) per reference/payee_type_rules.csv |
| paid_to_others | number | derived | Payments to all other payees: businesses, non-profits, health care, education and financial institutions, utilities and individuals |
| partial_year | number | derived | True for the latest payments year while it is still being updated monthly |

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

**f_concentration** (114 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| area | text | derived | One of GMI's six focus areas |
| vendors | number | derived | Distinct payees in the year |
| spend | number | derived | Dollars spent (budget actuals or payments) |
| top5_share | number | derived | Share of the area's private-vendor spend held by its five largest vendors |
| hhi | number | derived | Herfindahl-Hirschman Index: sum of squared percentage shares of spend (0-10,000; above 1,800 is highly concentrated under the 2023 DOJ/FTC Merger Guidelines) |

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

**f_fund_source** (10,617 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| fund_type | text | derived | Fund type (General, Special, Federal, Reimbursable and so on) |
| fund_source_code | text | portal | Fund source code within a fund type |
| fund_source_name | text | portal | Fund source name |
| budget | number | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**f_grants** (23,085 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| grantor | text | portal | State agency and program awarding the grant or loan |
| grantee | text | portal | Recipient of the grant or loan |
| description | text | portal | Grant or loan program description as the grantor published it (free text, as listed) |
| category | text | derived | Grant or Loan, from the dataset's category code (G/L) |
| nonprofit | text | portal | Y when the portal marks the grantee as a non-profit |
| zipcode | text | portal | Grantee ZIP code as published |
| amount | number | portal | Dollars paid, awarded or reported on the row; nominal dollars |
| in_payments | number | derived | True when the grantee is also a payee in the payments data that fiscal year (names compared without case, spaces or punctuation) |
| paid_same_fy | number | derived | Payments to the grantee that fiscal year (all agencies) when in_payments is true |

**f_object** (7,817 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| object_name | text | portal | Comptroller object name |
| budget | number | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| controllable | number | derived | Controllable purchases: contractual services, supplies, equipment, rent and similar spending agencies can renegotiate, per reference/controllable_rules.csv |

**f_overlap** (11 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| budget | number | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |
| general_funds | number | derived | Operating budget paid from the General Fund |
| special_funds | number | derived | Operating budget paid from special funds (dedicated State revenue) |
| federal_funds | number | derived | Operating budget paid from federal funds, including the ARRA and COVID federal fund types |
| payments | number | derived | Payments to all payees in the year (vendor payments dataset, 7syw-q4cy) |
| paid_to_government | number | derived | Payments to government payees (counties, cities, school systems, State and federal bodies) per reference/payee_type_rules.csv |
| paid_to_others | number | derived | Payments to all other payees: businesses, non-profits, health care, education and financial institutions, utilities and individuals |
| partial_year | number | derived | True for the latest payments year while it is still being updated monthly |
| grants | number | derived | Grants dataset rows with category Grant |
| loans | number | derived | Grants dataset rows with category Loan |
| grants_and_loans | number | derived | All grants dataset rows (grants and loans) |
| grants_in_payments | number | derived | Grant and loan dollars whose grantee is also a payee in the payments data that year |
| grants_in_payments_share | number | derived | Share of grant and loan dollars whose grantee is also a payee that year (name match; a lower bound on overlap) |
| grant_rows | number | derived | Rows in the grants dataset that year |
| grant_rows_in_payments | number | derived | Grant rows whose grantee is also a payee that year |
| payments_to_budget_share | number | derived | Payments divided by the operating budget at its latest stage (a cross-check; the two measure different things) |

**f_payee_type** (5,600 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| payee_type | text | derived | Payee type from reference/payee_type_rules.csv: Government, Health care organization, Education institution, Financial institution, Utility, Non-profit (grants data) or Business or other |
| function_name | text | derived | Budget function title (from the portal's category_title) |
| paid | number | derived | Payments in dollars |
| vendors | number | derived | Distinct payees in the year |

**f_program** (6,648 rows)

| column | type | origin | definition |
|---|---|---|---|
| fiscal_year | number | portal | Maryland fiscal year (July 1 to June 30), named for the year it ends |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| agency_code | text | portal | Three-character State budget agency code (for example D50); the key that joins budget and payments |
| unit_name | text | portal | Budget unit name |
| program_code | number | portal | Budget program code, two digits in core |
| program_name | text | portal | Budget program name |
| budget | number | portal | Dollars budgeted or spent (actual years) on the row; nominal dollars |

**f_savings_check** (1,625 rows)

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

**pipeline_runs** (5 rows)

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

**run_checks** (96 rows)

| column | type | origin | definition |
|---|---|---|---|
| run_id | text | ops | Pipeline run identifier, UTC timestamp YYYYMMDDTHHMMSSZ |
| stage | text | reference | Confirmed budget stage for the fiscal year (Actual, Working, Legislative Appropriation) from ref.budget_stage, or the pipeline layer in run_checks |
| check | text | ops | Check description |
| status | text | ops | pass, warn or fail |
| detail | text | ops | Numbers behind the check result |

**sources** (6 rows)

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
1,481 of 1,481 columns documented (85 source, 1013 warehouse, 383 dashboard).
<!-- /gen:coverage -->

**Source schema changes since the last snapshot:**

<!-- gen:drift -->
No change in source schemas since the last snapshot.
<!-- /gen:drift -->

To update: add or edit a definition in `reference/column_dictionary.csv` (column, the tables it applies to or blank for all, origin, definition), then run `make docs`. `make docs-strict` fails on any undocumented column or schema change.
