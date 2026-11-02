# Recommendations: building, querying, aggregating and modeling — as a portfolio repo

What the repo already does well, what to change, and in what order. Written Nov 2, 2026, after reconciling every dataset on the Transparency Portal's View Data page with the API extract (all four match every year).

## 1. Creating the datasets (extract)

| Practice | Status | Recommendation |
|---|---|---|
| Pull from the API, not screens | Done: SODA API, 20,000-row pages ordered by `:id` | Keep. The website downloads are a **second copy for reconciliation only**, never a source: they are larger (budget CSV 686 MB vs Parquet), slower, and their `Type` column is stale. |
| Immutable raw layer | Done: `data/raw/<run_id>/` Parquet + manifest | Keep raw exactly as delivered; fix nothing there. |
| Freshness and incremental loads | Done: `rowsUpdatedAt` check reuses unchanged files | Add an `If-Modified-Since` check to the website downloads so `make reconcile` skips the 750 MB when nothing changed. |
| Prove completeness | Done: row count = portal `count(*)`, yearly sums = portal `sum()` | Done twice now: API vs portal aggregates, and API vs website downloads. Keep both in the README. |
| Don't commit data | Done: `data/` is git-ignored | Publish each good run's small outputs (marts as CSV, figures, reconciliation) as a **GitHub Release** tagged with the run ID, so reviewers can download without running anything. |
| Secrets | Done: GitHub secrets / `.env` | Keep. |

## 2. Querying and aggregating

| Practice | Status | Recommendation |
|---|---|---|
| Push aggregation to the server when you only need totals | Done for checks (`select fiscal_year, count(*), sum(...)`) | Use SoQL `$select/$group` for any quick question; download rows only for modeling. |
| One engine, layered | Done: DuckDB `raw → ref → core → ops` | Add `mart` (Phase 4) as **plain `.sql` files** in `sql/mart/`, one table per file, run in order by `build.py`. SQL in files is easier for a reviewer to read than SQL in Python strings. (dbt-duckdb is the heavier, industry-standard version of the same idea; worth it only if the mart layer grows past ~15 tables.) |
| Grain is explicit | Partly | Start each mart file with a header comment: grain, keys, source tables, and the check that ties it back to `core`. |
| Roll-ups tie out | Done for `core` | Every mart gets a check: its total equals its `core` total (Phase 4 gate). |
| Rules as data | Done: `reference/*.csv` | Keep; this is the strongest governance signal in the repo. |
| The vendor and results roll-up | Planned | Function → agency → program, with vendors and Managing for Results measures attached at agency level (every agency sits 100% in one function, so no allocation is needed). See the strategy in the session notes and issue #2. |

## 3. Statistical models

Port `legacy/gst/scripts/forecast.py` and `opportunities.py` into `src/models/` with these standards:

- **Baseline first.** Every model is scored against the naive (last actual) forecast on the same backtest. A model that can't beat naive isn't used. This is already the legacy rule; keep it and print the comparison table.
- **Honest backtests.** Fit FY2017–FY2022, score FY2023–FY2025 (already the design). Report MAPE per area and say how few points there are (nine actual years): intervals matter more than point forecasts.
- **Uncertainty.** Bootstrap P10/P50/P90 bands with a fixed seed recorded in the output; the Monte Carlo savings ranges also get seeds.
- **Real and per-resident dollars.** Every spending comparison over time is available in CPI-adjusted and per-resident terms (`core.cpi_fy`, `core.fact_population`).
- **Assumptions in one place.** The register in `docs/data-governance.md` §8; models read values from a config file, not literals in code.
- **Spending and results (recommendation 6).** Treat it as descriptive: spending next to each agency's measures over the same years. If a model is added later, use agency fixed effects and real per-resident dollars, and state that it is associational, not causal.
- **Model cards.** One short markdown file per model in `docs/models/`: purpose, data, method, backtest result, limits.

## 4. Making it read well as a portfolio

| Item | Status |
|---|---|
| README that answers "what, why, does it work" in the first screen | Pipeline diagram, dataset table, figures: done |
| Figures generated from data, never pasted | `make figures`: done |
| Every number traceable | Reconciliation, checks, citations, governance: done |
| CI badge, tests on every push | CI runs lint and tests; add the badge to the README |
| One-command reproduction | `make all` then `make reconcile figures docs` |
| A notebook for reviewers | Add `notebooks/walkthrough.ipynb` that only reads the marts and tells the story in ten cells; keep logic out of notebooks |
| Licence and citation | Add `LICENSE` (code, e.g. MIT; data stays public domain per the portal) and `CITATION.cff` |
| Changelog | Add `CHANGELOG.md` keyed to phase gates |
| Pinned environment | Add a lock file (`uv lock` or `pip-tools`) so a reviewer gets the same versions |
| Docs site (optional) | GitHub Pages with MkDocs from `docs/` |

## 5. Order of work

1. Phase 4 marts as `sql/mart/*.sql`, with the vendor master and function roll-up first, tie-out checks, and a release of outputs.
2. Port the forecasts and detectors to `src/models/` with model cards and seeded intervals.
3. Recommendation 6: the agency results panel.
4. Portfolio polish: CI badge, licence, citation, changelog, lock file, walkthrough notebook.
5. Phase 6: run on a schedule only if you change the local-only decision; otherwise keep the manual "Extract and build" workflow as the proof that it runs end to end.
