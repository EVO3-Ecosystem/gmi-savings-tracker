# Roadmap

Six phases over about eight weeks; each phase's gate must pass before the next starts. Full plan: the *Maryland Transparency Data — Dev Wiki*, Roadmap & build plan tab.

| Phase | Weeks | Build | Gate | Status |
|---|---|---|---|---|
| 0. Align | done | Data dictionary, gap analysis, API references, reference lists | Team signs off on definitions | Done |
| 1. Extract | 1 | `extract.py`: 20,000-row pages by `:id`, retries, freshness check on `rowsUpdatedAt`, Parquet per run, manifest with portal counts and totals | Two runs in a row match portal row counts | **Passed Oct 28, 2026**; context sources added Oct 29 |
| 2. Database | 2–3 | DuckDB `raw`, `core`, `ops`; type casting and code normalizing; reconciliation checks; non-zero exit on failure | Every check passes; yearly totals tie to the portal | **Passed Oct 29, 2026** (30 of 30) |
| 3. Reference data | 3–4 | `ref` layer from `reference/` CSVs: agencies and aliases, stages, focus areas, payment-name and vendor maps; match-rate report | Match rates at or above the dashboard's master list quality | **Passed Oct 29, 2026** |
| 4. Marts & dashboard | 4–5 | One `mart` table per dashboard file; `export.py` writes the CSVs; FY2027 payments as a partial year | Every dashboard file reproduced, or each difference explained | **Gate passed for the 21 base dashboard files (Nov 2, 2026).** `sql/mart/*.sql` (28 files at the gate, 43 now; the change measure applied by `marts.py` from each file's `-- yoy:` header), `make parity` against the legacy files: 12 reproduced exactly; 9 differ only as explained in `docs/parity/explanations.csv` (FY2027 partial year added; one company spelled differently). Also added: vendor master, payee types, agency functions, agency roll-up and results marts. Fixed on the way: scope precedence (client payments, then charges between agencies, then staff/grants/capital) and the payee-name pass-through exclusions (`reference/payee_area_exclusions.csv`). Left for Phase 5: the analytics files (opportunities, forecasts, savings checks, recommendations) and `export.py` |
| 5. Analytics | 5–7 | Forecasts, savings detectors, savings checks, path to $50M on the database; 5a first: pipeline facts, cross-checks, publish gate, fault test (gap analysis below) | Outputs match the dashboard; no carried files | **5a in progress (Nov 7, 2026):** publish gate, fault-injection test and database snapshot done; cross-checks, ops history tables and the 18 carried analytics files still open |
| 6. Automate & document | 7–8 | `make all`; launchd or cron on the Mac; run log, optional PDF report, wiki update | Two clean scheduled runs with no manual steps | |

## Open questions
- ~~Which decision for the 4 unmatched payment agency names?~~ Decided 2026-11-04 in `reference/payment_agency_decisions.csv` (two mapped, two excluded, each with evidence).
- ~~Is 4mca-332u (higher-education CUR and CR funds) already inside yu65-jmmv's totals?~~ No (checked 2026-11-04): it covers R13 Morgan State, R14 St. Mary's, R30 University System of Maryland and R95 Baltimore City Community College, which have no rows in yu65-jmmv ($8.6B in FY2026). Decision: add it in Phase 5 as its own raw table, union into the budget with a `source_dataset` column, show it in all-funds totals labeled "including public higher education", and leave it out of GMI savings baselines (these institutions buy under their own procurement authority, outside the executive-branch procurement GMI works through; confirm the statute citations before publishing).
- When to register the Socrata app token (before daily scheduling).

## Next phase suggestions: grants groupings
Grants are listed as published (`mart.f_grants`). Suggested groupings, each as a reviewed reference CSV:
- Grantor → budget agency code: uppercase, split at "/", map the agency part with the payment agency rules; unmatched names go to a decisions file.
- Grantor program: the text after "/" (for example WMATA operating vs capital grants).
- Grantee → vendor: the same normalization and company families as payments, so a grantee and a payee are one entity.
- Grantee type: the payee type rules (government, non-profit, business and so on) plus the dataset's non-profit flag.
- Purpose: cluster the description text into program families (cover crops, small business COVID loans, arts council grants).
- Overlap: match grants to payments on grantee, agency and year, and report grants outside payments separately.

## Old vs new pipeline: comparison matrix (Nov 5, 2026)

Old: `legacy/gst` (pandas scripts, CSV folders, about 2,000 lines of Python in 13 scripts). New: this repo (DuckDB layers, about 1,700 lines of Python plus 43 SQL marts). Status: **Better** = the new pipeline does more; **Same**; **Partial**; **Carried** = the dashboard file is still copied from the old pipeline; **Gap** = not in the new pipeline yet.

| # | Area | Capability | Old pipeline | New pipeline | Status |
|---|---|---|---|---|---|
| 1 | Extract | Download the five state datasets | `sources.py`: full download, reuse when the portal has not changed | `extract.py`: 20,000-row pages by `:id`, Parquet per run, manifest, freshness check on `rowsUpdatedAt` | Better |
| 2 | Extract | Self-healing | Re-downloads a year whose totals do not match | Re-downloads on a row-count mismatch, with backoff | Same |
| 3 | Extract | Match the portal's own counts and totals | Every year, every dataset | Every year (raw checks), plus `reconcile.py` against the portal's website downloads | Better |
| 4 | Extract | Cross-check with the state's sites | Budget vs operatingbudget.maryland.gov and payments vs vendorpayments.maryland.gov, 3 years each | Not ported | **Gap** |
| 5 | Extract | Budget stage evidence | FY2021-FY2022 programs vs DBM Volume 2 | `ref.budget_stage` (CSV with sources); `stage_evidence` file carried | Partial |
| 6 | Extract | Context sources | None | CPI (BLS), population (Census), federal awards (USAspending), Managing for Results plans | Better |
| 7 | Extract | Datasets | 5 | 5, plus 4mca-332u (higher education) planned | Same (planned) |
| 8 | Storage | Layers | CSV folders: raw, staged, model, out | DuckDB: raw, ref, core, mart, ops | Better |
| 9 | Rules | Mapping and classification rules | Mostly in code (`model.py`, `payments_legacy.py`) | 15 reviewed CSVs in `reference/` (CODEOWNERS) | Better |
| 10 | Rules | Agency mapping | Rules plus fuzzy match; 4 names pending | Same rules from CSV; decisions with evidence; 0 pending | Better |
| 11 | Rules | Vendor names and companies | Normalization and families in code | CSV rules, vendor master, 7 payee types | Better |
| 12 | Model | Change measure (year over year) | `measures.py`, defined once | `marts.py` from each SQL file's `-- yoy:` header, same definition | Same |
| 13 | Model | The 21 base dashboard files | Built in pandas | SQL marts: 12 reproduced exactly, 9 differ only as explained (`docs/parity/`) | Same (proven) |
| 14 | Model | Vendors tab and portal views | None | 10 vendor marts; budget vs payments, funding sources, programs, grants as listed, overlap | Better |
| 15 | Analytics | Forecasts (trend vs naive vs drift, backtest, bootstrap band) | `forecast.py` | `f_forecast`, `d_forecast_model` | **Carried** |
| 16 | Analytics | Opportunity detectors and bid list | `opportunities.py` (4 detectors) | `d_opps`, `d_bid_list` | **Carried** |
| 17 | Analytics | Savings checks against payments | `savings.py` | `d_savings`, `f_savings_check`, `d_savings_status` | **Carried** |
| 18 | Analytics | Recommendations, path to $50M, history per run | `recs.py`, `model/rec_history.csv` | `d_rec_status`, `d_plan50`; no history | **Carried** |
| 19 | Analytics | Vendor moves, payee-name detail, vendor pages | `payments_legacy.py`, `run.py` | `d_vendor_moves`, `d_vendor_names`, `f_vendor_detail` | **Carried** |
| 20 | Quality | Master list quality | Computed each run | `d_master_quality` carried, so it still lists the four names decided Nov 4 | **Carried (stale)** |
| 21 | Quality | Checks per run | 93 in 7 stages: raw 23, staged 3, model 14, cross-check 8, recommendations 7, page 28, publish 10 | 59 (raw 9, core 19, ref 11, mart 20) plus 34 page tests in `preview.py` | Partial: cross-checks and recommendation checks not ported |
| 22 | Quality | Fault-injection test | `run.py --inject-fault` drops half of FY2015 and shows the repair | `make test-fault` drops half of one budget year in a copy of the raw run and checks that the build fails its stop checks and the last good database survives (`tests/test_fault_injection.py`); the download re-fetch is shown by `EXTRACT_FAULT=fte` | Same |
| 23 | Quality | A failed check blocks publishing | Keeps the last good `out/` | Keeps the last good database; `export.py` refuses (exit 2) when a stop check failed, a newer build failed, or parity has an unexplained difference (`src/pipeline/gate.py`, `tests/test_gate.py`) | Same |
| 24 | Quality | Unit tests and CI | Page test only | 7 test files (14 tests), GitHub Actions CI and extract smoke test | Better |
| 25 | Quality | Parity with the old pipeline | n/a | `parity.py` with explanations | Better |
| 26 | Governance | Column definitions and schema drift | None | `governance.py`: 1,000 of 1,000 columns, drift history, governance doc | Better |
| 27 | Publish | Run log and checks on the dashboard | `pipeline_runs.csv`, `run_checks.csv` | `ops.run_log`, `data/check_history.csv` exist, but the dashboard still shows the old run files | **Carried** |
| 28 | Publish | Dashboard data files | Written to `out/` | `export.py` with a manifest and a "changed since last export" flag, plus a tested preview | Better |
| 29 | Publish | PDF report | `report.py` | None (optional end-user feature) | Gap (optional) |
| 30 | Publish | Power BI measures | `deploy/powerbi/measures.dax` | None | Gap (low) |
| 31 | Run | Scheduling | Manual | Manual locally; CI on GitHub | Same (Phase 6) |
| 32 | Docs | Figures | None | `figures.py`: 5 PNGs from the database | Better |

Summary of the 32 rows: 13 Better, 7 Same, 2 Partial, 7 Carried, 3 Gap (one optional, one low priority). 26 of 44 dashboard files come from the new marts; 18 are carried.

## Gap analysis and improvement backlog (Nov 5, 2026)

Ordered by value for the dashboard and the interview. Effort: S = under a day, M = one to three days.

| # | Gap | Why it matters | Fix | Effort | Phase |
|---|---|---|---|---|---|
| 1 | The Data & pipeline tab shows the old pipeline's facts (rows 20, 27): 93 of 93 checks, the four agency names already decided, the corrected grants "$50,000" claim | A reviewer sees numbers that contradict the repo; integrity scores 2 of 5 | Marts for `sources`, `runs`, `checks`, `measures`, `d_master_quality` and `stage_evidence` from `ops` and `ref`; show new and old check counts during the switch | S | 5a (next) |
| 2 | Analytics still carried (rows 15-19) | Calculator, Opportunities and Savings tracker score 3 only because of this | Port to `src/models/` on the marts: baselines first, backtest FY2017-FY2022 → FY2023-FY2025, seeded bootstrap, assumptions in `config/assumptions.yaml`, model cards in `docs/models/`; parity against the old files | M per module | 5 |
| 3 | No cross-checks with the state's own sites (row 4) or DBM budget books (row 5) | The old pipeline proved totals against three independent publications; the new one against two | Port the 8 cross-checks into `checks.py` (warn if a site is down, stop if a total differs) | S | 5a |
| 4 | Publishing is not gated (row 23) | A bad build could still be exported | `export.py` exits non-zero if the latest run has a failed stop check or parity has an unexplained difference | S | 5a **done Nov 7** |
| 5 | No history of recommendations or new payee names (row 18) | The "changed since last refresh" feedback loop is lost | `ops.rec_history` and `ops.payee_name_seen`, appended each run | S | 5 |
| 6 | No fault-injection test (row 22) | Self-healing is claimed but not demonstrated | `make test-fault`: drop rows from one year in a copy of raw and show the check fails and the last good database is kept | S | 5a **done Nov 7** |
| 7 | Analysis quality from the tab review: small-base changes (+4,177%, +42,462%), nominal dollars only, nine-year sums in Overview tiles | Over-reading risk; executives read one year | Minimum base for changes (about $1M); real and per-resident dollars (`core.cpi_fy`, `core.fact_population`); FY2026 vs FY2025 tiles | M | 5 |
| 8 | Higher education budget (4mca-332u) not loaded | All-funds totals leave out about $8.6B a year | Raw table, `source_dataset` column, labeled totals, kept out of savings baselines | M | 5 |
| 9 | Grants have no groupings; overlap is a name-match minimum | WMATA, the largest grants, show no match | Grantor and grantee groupings (see "Next phase suggestions") | M | 5-6 |
| 10 | Model tidy-ups noted earlier | `core.fact_fund` drops unit and program; `mart.payment_area` holds payment lines | Keep unit/program; rename to `mart.payment_line` | S | 5 |
| 11 | Page speed | The 4.5 MB grants file loads with everything else | Load it only when the Budget tab opens | S | 5 |
| 12 | Power BI measures, PDF report (rows 29-30) | Nice to have | Generate DAX from `config/dashboard.yaml` measures; port `report.py` | S each | 6 (optional) |
| 13 | Scheduling (row 31) | Monthly refresh is manual | `make all` on a schedule; register the Socrata app token first | S | 6 |

Tab scores (rubric in `docs/portfolio-rubric.md`, Nov 5, 2026): Overview 3, Focus areas 4, Savings tracker 3, Opportunities 3, Calculator 3, Vendors 5, Agencies 3, Budget 3, Data & pipeline 2. Gaps 1, 3, 4 and 6 lift Data & pipeline; gap 7 lifts Overview, Agencies and Opportunities; gap 2 lifts the three analytics tabs.

Dashboard-level gaps added in the *GMI Dashboard Optimization Roadmap v2* (Claude Docs, Nov 5, 2026), which supersedes the Dev Wiki's v1 roadmap tab:

| # | Gap | Fix | Effort | Phase |
|---|---|---|---|---|
| 14 | Overview tiles add nine years; 7 dense cards | FY2026 vs FY2025 tiles with stage labels; one-line conclusion; scope chart moves to Focus areas | S | 5a |
| 15 | Savings tracker repeats two tables; 50% tolerance unlabeled | Merge the tables; label the tolerance where "Seen" appears | S | 5a |
| 16 | Opportunities headline reads as a promise; detectors untested | "Leads worth up to"; backtest each detector | M | 5 |
| 17 | Agencies: one table, no chart or headline; pass-through agencies top per-position | Ranked chart, headline, pass-through flag | S | 5a |
| 18 | Budget cards lack conclusions; no funding chart; tall grant rows | One-line finding per card, funding chart, one-line descriptions | S | 5a |

## Roadmap v3 additions (Nov 5, 2026): outside review and portfolio harvest

**Review check.** An outside review of this repo was right that CI is failing (every push from Nov 2 to Nov 6, 11 runs in a row; last green Oct 29) but wrong about the cause: the error is `ModuleNotFoundError: No module named 'src'` at test collection, not network calls. The root cause was packaging, not the pytest import path: setuptools auto-discovery exposed `pipeline` instead of `src` in the editable install, and `tests/test_governance.py` (Nov 2) was the first test to import `src.pipeline`. **Fixed Nov 6, 2026** by declaring `src` and `src.pipeline` in `pyproject.toml` (PR 6); `main` is green again. PR 7 untracked the stale `src/*.egg-info` and set read-only workflow token permissions. Still open: require the `test` check on `main` (branch protection, a repo setting) and bump the Node 20 actions (`checkout@v4`, `setup-python@v5`), which only warn. It also described the repo as static CSVs or SQLite, which it isn't, and said Phase 5 must reproduce the 21 base files, which are already reproduced.

**Ideas register.** 49 unique ideas from the review: 9 done, 25 adopt, 9 adapt, 6 decline. Declined, with reasons: OData (SODA covers it), subcontractor data (no public source), State Police dashboard (out of scope), revenue forecasting with XGBoost/LightGBM (no revenue data; the same models are used for spending), Prophet or Orbit seasonality (annual data only), random forest fiscal-stress classifier (no labeled stress events), switching to Seaborn or Plotly (d3 and matplotlib already use the validated palette).

| Step | Adds | Gate |
|---|---|---|
| Done (Nov 6) | CI package discovery fix | Green CI on main ✔ |
| 5a | SODA fixtures and no-network tests; fixture integration test; contract tests on exports; README diagram, screenshots and findings; executive cards (forecast range, savings vs $50M, review queue); Agencies scatter and box plot; Budget treemap; job description crosswalk (after checking the posting) | CI green on fixtures; nothing stale; export refuses a failed build |
| 5 | Rolling-origin backtests; P10-P90 ranges with coverage; LightGBM quantile challenger on agency x code x year; log and real-dollar transforms; robust scaling; Isolation Forest on vendor-agency-year patterns; agency peer clusters (K-Means/HDBSCAN) with a PCA map; grant-description clustering; review queue with status (Under review, Approved variance, Refer to OLA) and CSV export; State Plan priorities and OLA findings as reference data; BLS employment and BEA GDP context; program-level drill-down | 0 carried files; models beat or match baselines; every tab 5 of 5 |
| 6 | DVC with a local store; optional `make postgres`; freshness alerts as GitHub issues; read-only MCP server over the marts; NAICS and contract-award research (eMMA, SAM.gov); analyst-detail toggle; roadmap timeline figure | Two clean scheduled runs |

**Portfolio harvest** (patterns from the owner's other repos, `snapaiarchitect/sierra-applied-ml` and `snapaiarchitect/genai-engineering`):

| From | Pattern | Lands as | Phase |
|---|---|---|---|
| sierra-applied-ml | GitHub Pages live site with interactive pages | Public preview of the dashboard and a project page | 6 |
| sierra-applied-ml | README order: problem, what it means, results vs baseline, one finding per chart, provenance | README rewrite | 5a |
| sierra-applied-ml | Baseline-first results tables, holdout periods | Model card template | 5 |
| genai-engineering | Docker and docker-compose one-command launch | `docker compose up` runs pipeline and preview | 6 |
| genai-engineering | Model registry with lineage | `ops.model_registry` in DuckDB | 5 |
| genai-engineering | Drift detection (KS test, PSI) | Check comparing this run's payment distributions with the last | 5 |
| genai-engineering | Promote only if better than baseline | Stop check before a model is published | 5 |
| genai-engineering | Confidence threshold to human review | Low-confidence flags go to the review queue | 5 |
| genai-engineering | TF-IDF + logistic regression classifier | Payee-type classifier trained on rule-labeled payees, to catch rule misses; grant description groups | 5 |

**Portfolio housekeeping done Nov 5, 2026:** genai-engineering README counts and claims corrected to its data files (pushed); sierra-applied-ml README corrected to its results files and its links moved to snapaiarchitect (patch ready; this session can't push to that repo); profile README in `snapaiarchitect/snapaiarchitect` links all three repos (pushed; the repo is private, so it shows on the profile only once made public). Pinning is a manual step on GitHub.

## Best practices applied and planned (Nov 7, 2026)

Researched for each open suggestion; what is done is marked, the rest is the standard Phase 5 will follow.

| Area | Practice | Status |
|---|---|---|
| Publishing | Write-audit-publish: stage, audit, publish only if the audit passes ([overview](https://www.tabular.io/?p=549), [orchestration example](https://docs.coginiti.co/tutorials/wap-awap-tutorial/)) | Done: `gate.py` gates `export.py`; the build already keeps the last good database |
| Persistence | Export with `EXPORT DATABASE` to Parquet and import into an empty database ([DuckDB docs](https://duckdb.org/docs/stable/sql/statements/export)); never copy a file that is open for writing | Done: `make snapshot` / `make restore` with a manifest and SHA-256 per file; copy the folder to storage outside the sandbox to keep it |
| Fault injection | Damage an input on purpose and show the checks catch it and nothing bad is published | Done: `make test-fault` |
| Actions security | Read-only default token, third-party actions pinned to full commit SHAs with a version comment, `persist-credentials: false`, Dependabot to keep pins current ([guide](https://boostsecurity.io/blog/how-to-secure-github-actions), [pinning notes](https://medium.com/@jordanritter/security-hardening-github-workflows-at-scale-d291a33774e1)) | Done: all three actions at v7 (Node 24), pinned; `.github/dependabot.yml` added |
| Forecast evaluation | Rolling-origin (walk-forward) evaluation, never shuffled folds; every model compared with the naive last-value baseline on the same origins and horizons; MASE scale recomputed from each origin's training history ([tsCV](https://pkg.robjhyndman.com/forecast/reference/tsCV.html), [workflow](https://metricgate.com/blogs/workflow-for-validating-a-forecasting-model/)) | Planned for the analytics port (gap 2); intervals need a separate source (Hyndman and Athanasopoulos, *Forecasting: Principles and Practice*) |
| Branch protection | Require the `test` check on `main` | Open: a repository setting only an admin can change |
