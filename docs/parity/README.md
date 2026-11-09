# Parity with the original pipeline

Two gates compare this pipeline with the original pandas pipeline (`legacy/`).

| Gate | Command | Compares | Files |
|---|---|---|---|
| Phase 4: base files | `make parity` | the 21 base marts in the database with the legacy pipeline's files of the same name | `summary.csv`, `differences.csv`, `explanations.csv` |
| Phase 5: published files | `python -m src.pipeline.parity_published` | the 44-file dashboard export (`data/export/latest`) with the CSVs the original pipeline published (`legacy/gst/out`, run `20261102T183034Z`) | `published_summary.csv`, `published_differences.csv`, `published_explanations.csv` |

## Phase 5: published files (checked Nov 9, 2026)

**Rules.** 30 of the 44 exports have a legacy file of the same name. Rows are matched on each file's key (its grain, `KEYS` in `src/pipeline/parity_published.py`); row and column order do not matter. Money must agree within $0.01, ratios (the export's 5-decimal columns) within 1e-5, integer counts exactly, text after trimming. Every difference is recorded as an aspect (`rows_only_legacy`, `rows_only_export`, `column_only_<side>:<col>`, `cells:<col>`, `duplicate_keys`); an explanation in `published_explanations.csv` lists the aspects it `covers`, so a new kind of difference in an explained file shows up as unexplained. The command exits 1 while any file has an uncovered aspect or a newer export is missing.

**Result: 13 equivalent, 15 explained, 2 unexplained.**

- Equivalent: `d_agency`, `d_bid_list`, `d_savings`, `d_vendor_moves`, `d_vendor_names`, `f_code`, `f_function`, `f_fund`, `f_object`, `f_scope`, `f_vendor`, `measures`, `stage_evidence`.
- Explained (reasons in `published_explanations.csv`): FY2027 added as a partial year (`f_savings_check`, `f_vendor_detail`, `sources` rows), the Nov 4 payment agency decisions (`agency_master`, `d_master_quality`, `f_agency`, `f_area`, `totals_by_fy`), the Nov 7 decisions (forecast model chosen by rolling-origin MASE: `d_forecast_model`, `f_forecast`; $1M growth base and plan range, PR 17: `d_opps`, `d_plan50`; recommendation 6 from Managing for Results, PR 15: `d_rec_status`), this pipeline's own status history (`d_rec_status`, `d_savings_status` previous columns), one company's spelling (`vendor_families`) and each pipeline's own run log (`pipeline_runs`, `run_checks`). `d_opps` was also re-run with the legacy growth rule (`min_base_budget: 0`): it then equals the legacy file exactly.
- **Unexplained, to fix in the pipeline (reported, not fixed here):**
  - `agency_master`, column `agency`: blank for the 8 payment-only codes CAPITAL, D30, E90, J11, R37, R60, R95 and U10, which the legacy file named (for example "MARYLAND TRANSPORTATION AUTHORITY"). `sql/mart/16_agency_master.sql` takes names from `mart.agency_name`, which holds budget agencies only; the Data & pipeline tab's agency table shows these rows without a name. The Phase 4 parity compared numeric columns only, so it did not see this.
  - `sources`, column `portal_name`: repeats the dashboard title ("State of Maryland Payments Data") instead of the title the portal publishes ("State of Maryland Payments Data: FY2008 to FY2024"), against its documented meaning in `docs/schemas/dashboard_columns.csv`; `src/pipeline/facts.py` sets `portal_name = title`.

**14 exports without a legacy file** (the Vendors tab and the portal views) are listed in `published_summary.csv` with the build check or test that covers each instead (`covered_by`). Two have no check of their own beyond the page tests: `f_vendor_year` and `d_area_top`.

**Also noted.** `export.py` holds FY2027 payments back from six files until the page labels partial years, but not from `f_vendor_detail` or `f_savings_check`. The savings tracker limits payment years to FY2026, so it is unaffected; the vendor drill-down's "Payments by year" chart, whose note says FY2022-FY2026, can draw a partial FY2027 bar.

## Cross-checks against the State's own sites

`python -m src.pipeline.parity_published --crosschecks` re-runs the original pipeline's 8 independent cross-checks (plus FY2027 payments) and writes `docs/reconciliation/crosschecks_<date>.csv`. On Nov 9, 2026 all three hosts were reachable and all 9 checks passed: the budget for FY2025-FY2027 equals operatingbudget.maryland.gov to the dollar, payments for FY2024-FY2027 equal vendorpayments.maryland.gov to the cent, and DBM's Volume 2 books, downloaded and parsed again, match 145 of 210 FY2021 programs (69.0%) and 159 of 199 FY2022 programs (79.9%) to the dollar against the 60% threshold (the stored evidence from the legacy parse says 147 of 210 and 163 of 203). An unreachable host is recorded as "unreachable from build environment" and leaves that check open.
