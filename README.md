# GMI Savings Tracker

An independent savings tracker for Maryland's Government Modernization Initiative (GMI): it checks reported savings against the state's own payments, and finds the next $50M. Prototype by Sierra Napier; not an official State of Maryland product.


A free, local pipeline for Maryland's budget, payments, funding, staffing and grants data: SODA pulls → Parquet files → one DuckDB database → dashboard CSVs. It replaces the pipeline that built the **GMI Savings Tracker** and **Maryland Spend Lens** dashboards, whose original code is saved here under `legacy/`.

The plan, data dictionary and reference lists are in the *Maryland Transparency Data — Dev Wiki* (Roadmap & build plan tab).

## Status

| Phase | State | Gate |
|---|---|---|
| 1. Extract | **Done** (Oct 28, 2026) | Two runs in a row matched portal row counts for all five datasets ✔ |
| 2. Database | **Done** (Oct 29, 2026) | 30 of 30 checks pass; all five datasets' yearly totals tie to the portal to the cent ✔ |
| 3. Reference data | **Done** (Oct 29, 2026) | Match rates equal the dashboard's; controllable purchases and focus areas FY2025 match it to the dollar ✔ | Match rates at or above the dashboard's master list quality |
| 4. Marts & dashboard | Next | Every dashboard file reproduced, or each difference explained |
| 5. Analytics | — | Outputs match the dashboard |
| 6. Automate & document | — | Two clean scheduled runs with no manual steps |

## Run it

```bash
pip install sodapy pandas pyarrow pyyaml requests duckdb pytest
make extract        # download what changed since the last good run
make extract-full   # download everything
make gate1          # Phase 1 gate: last two runs matched the portal
make build          # Phase 2: DuckDB layers + checks (non-zero exit on a failed check)
make all            # extract then build
make test
```

An app token is optional: copy `.env.example` to `.env` and set `MD_SODA_APP_TOKEN`. Without one, a full download takes about 2.5 minutes; a run where nothing changed takes about 4 seconds.

## Phase 1: extract (`src/pipeline/extract.py`)

For each dataset in `config/datasets.yaml` (budget yu65-jmmv, fund gy87-e27x, fte x8qy-486w, payments 7syw-q4cy, grants absk-avps):

1. Reads the portal's `rowsUpdatedAt`, its own `count(*)` and its own per-year totals.
2. **Freshness check:** if `rowsUpdatedAt` is unchanged since the last good run, reuses that run's Parquet (hard link) instead of downloading.
3. Otherwise downloads 20,000-row pages ordered by `:id`, retrying each page with exponential backoff (50,000-row pages drop without a token).
4. **Self-healing:** if the file's row count differs from the portal's, re-downloads it (up to twice), re-reading the portal's count in case it changed mid-run. Tested with `EXTRACT_FAULT=fte`, which drops half the rows: the run repaired it and passed.
5. Writes `data/raw/<run_id>/<dataset>.parquet` and `manifest.json` (rows, portal count, match, `rowsUpdatedAt`, source, seconds, repairs, per-year portal totals for the Phase 2 totals check).
6. **Feedback loop:** every run, including failed ones, is appended to `data/runs.csv`. A failed run exits non-zero and is never reused.

Gate runs, Oct 28, 2026 (1,208,477 rows each):

| Run | Mode | Time | Result |
|---|---|---|---|
| 20261028T202434Z | first download | 168 s | all five match |
| 20261028T202736Z | forced download, test fault in fte | 148 s | fte repaired by re-download; all five match |
| 20261028T203005Z | freshness check (portal unchanged) | 3.5 s | all five reused and match |

Budget (11 years) and payments (20 years) per-year sums from the downloaded files equal the portal's own totals to the cent.

## Phase 2: database (`src/pipeline/build.py`, `checks.py`)

Builds `data/md_transparency.duckdb` from a run's files in about 9 seconds: `raw` (as delivered), `ref` (agencies, functions, objects, sub-objects, fund types, budget stages), `core` (typed and normalized facts, plus CPI by fiscal year, federal awards, population, and the Managing for Results document index), `ops` (source snapshot, portal yearly totals, enrichment status, check results, run log). Every check is recorded in `ops.check_result` and `data/check_history.csv`. A failed stop check exits non-zero and **keeps the last good database**; the failed build is saved as `md_transparency.failed.duckdb` for inspection (tested by faking a one-row mismatch).

Context sources pulled with each extract (`src/pipeline/enrich.py`, warnings never block): CPI-U (BLS, falling back to FRED when BLS's shared daily limit is hit), federal grants to Maryland governments (USAspending), Maryland population (Census estimates), and every agency's Managing for Results plan (DBM, 111 PDFs for FY2027). See `docs/recommendations.md`.

## Phase 3: reference data (`reference/*.csv`, `src/pipeline/reference.py`)

Every rule the dashboard pipeline kept in code now lives in a CSV, so each change has an author and a date: payment agency rules and decisions, vendor families and normalization, payee focus areas, controllable-purchase rules, focus-area rules, budget stages, GMI's 14 reported savings items, the Managing for Results plan-to-agency map, and the dashboard's quality baseline. `reference.py` applies them to build `ref.map_payment_agency`, `ref.map_payee_vendor`, `ref.map_focus_area`, `core.fact_payment_mapped`, `core.fact_budget_scope` (controllable flag, scope and focus area per budget line) and `core.mfr_measure` (every performance measure and yearly value read from the plans). Results, Oct 29, 2026:

| Measure | Pipeline | Dashboard |
|---|---|---|
| FY2026 payment dollars matched to a budget agency | 100.00% | 100.00% |
| Payment agency names mapped | 141 of 145 | 141 of 145 |
| Payee names grouped into multi-name companies | 9,686 in 4,478 (all years) | 9,474 in 4,377 (FY2026 payees) |
| Controllable purchases, FY2025 | $4,093,855,308 | $4,093,855,308 |
| Focus areas, FY2025 | $1,287,718,788 in 96 codes | $1,287,718,788 in 96 codes |
| Managing for Results | 2,957 measures, 106 of 111 plans matched to an agency | — |

## Layout

```
.github/                 CI, manual extract smoke test, issue and PR templates
docs/                    roadmap, checks catalog, data sources
scripts/bootstrap_github.sh  one-time labels, milestones and phase issues
config/datasets.yaml     dataset IDs, page size, retries, backoff, heal attempts
reference/               hand-kept CSVs (Phase 3); for now the dashboard pipeline's agency and vendor master lists
src/pipeline/extract.py  Phase 1
tests/                   pytest checks on the latest run
data/                    git-ignored: raw/<run_id>/, runs.csv, md_transparency.duckdb
legacy/gst/              the original GMI Savings Tracker pipeline (see below)
```

## Legacy pipeline (`legacy/gst/`) — the spec for phases 2–5

The code that built the GMI Savings Tracker (pandas, not DuckDB). Run order, from `scripts/run.py`:

| Order | Script | What it does |
|---|---|---|
| 1 | `common.py` | Paths, HTTP with retries, SODA paging, the run log and checks |
| 2 | `sources.py` | Downloads the five datasets per year, reconciles each year to the portal's count and sum, re-downloads mismatches |
| 3 | `budget_legacy.py`, `payments_legacy.py` | Earlier Spend Lens logic reused: controllable-purchase rules, focus-area tagging by payee name, pass-through exclusions |
| 4 | `model.py` | Budget model, official stage labels read from operatingbudget.maryland.gov, agency master list (payment names → budget codes), **vendor master list rules** (`FAMILIES` regex and spacing merges), payments model, agency-year table |
| 5 | `measures.py` | Year-over-year measures (DAX-style), catalog |
| 6 | `savings.py` | GMI reported savings (Joint Chairmen's Report, Jan 26, 2026) and the payee-name payment check for each item |
| 7 | `opportunities.py` | Four savings detectors (peer gap, growth above trend, tail spend, leverage) |
| 8 | `forecast.py` | Backtested forecasts (trend, naive, drift) with bootstrap intervals; GMI-rate defaults; General Fund shares |
| 9 | `recs.py` | Recommendation outputs: bid list, vendor drill-downs, contract candidate sets, savings status history, path to $50M, master list quality |
| 10 | `run.py` | Orchestrates 2–9, runs ~90 checks, publishes only if none fail, records run history |
| 11 | `page_test.py` | Renders the dashboard page in headless Chromium across filter combinations and checks totals reconcile |
| 12 | `report.py` | Optional PDF report of the dashboard |

`page/index.html` is the dashboard page; `deploy/powerbi/measures.dax` holds the same measures for Power BI; `stage_evidence.csv` records how the budget stage of each year was confirmed.
