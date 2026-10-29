# GMI Savings Tracker

An independent savings tracker for Maryland's Government Modernization Initiative (GMI): it checks reported savings against the state's own payments, and finds the next $50M. Prototype by Sierra Napier; not an official State of Maryland product.


A free, local pipeline for Maryland's budget, payments, funding, staffing and grants data: SODA pulls → Parquet files → one DuckDB database → dashboard CSVs. It replaces the pipeline that built the **GMI Savings Tracker** and **Maryland Spend Lens** dashboards, whose original code is saved here under `legacy/`.

The plan, data dictionary and reference lists are in the *Maryland Transparency Data — Dev Wiki* (Roadmap & build plan tab).

## Status

| Phase | State | Gate |
|---|---|---|
| 1. Extract | **Done** (Oct 28, 2026) | Two runs in a row matched portal row counts for all five datasets ✔ |
| 2. Database | Next | Every check passes; yearly totals tie to the portal |
| 3. Reference data | — | Match rates at or above the dashboard's master list quality |
| 4. Marts & dashboard | — | Every dashboard file reproduced, or each difference explained |
| 5. Analytics | — | Outputs match the dashboard |
| 6. Automate & document | — | Two clean scheduled runs with no manual steps |

## Run it

```bash
pip install sodapy pandas pyarrow pyyaml requests duckdb pytest
make extract        # download what changed since the last good run
make extract-full   # download everything
make gate1          # Phase 1 gate: last two runs matched the portal
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
