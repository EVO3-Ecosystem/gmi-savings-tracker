# Model card: the six recommendations and the path to $50M

**What it does.** Turns the Overview's six recommendations into tracked tables, each with a status and one key number that is re-computed every build and compared with the previous one, and builds the step-by-step path to $50M a year. Code: `src/models/recommendations.py` (a port of the plan, status and vendor-detail parts of `legacy/gst/scripts/recs.py`); assumptions: `config/assumptions.yaml` (`recommendations`); tables: `mart.d_plan50`, `mart.d_rec_status`, `mart.f_vendor_detail`, `mart.d_vendor_names`.

| # | Recommendation | Where the number comes from |
|---|---|---|
| 1 | Bid statewide contracts for shared vendors | the bid list (`opportunities.py`): 30 vendors, $12.1M-$30.2M a year |
| 2 | Confirm which reported savings recur | the savings checks (`savings.py`): 2 of 7 checks seen in payments |
| 3 | Name the seven renegotiated contracts | the four named contract types, checked in the savings status: payments fell for 2 of 4 |
| 4 | Plan the rest of the path to $50M | `d_plan50`: 28 steps to $50.2M a year |
| 5 | Keep one vendor and agency master list | 100.0% of FY2026 payments matched to an agency |
| 6 | Tie spending to results | 2,957 performance measures read from 108 of 111 agency plans; 106 plans matched to a budget agency |

## The path to $50M, and what it rests on

Step 1 applies each area's GMI-reported saving rate to the forecast FY2027 median; the next steps add statewide contracts (the bid list, largest first) at an **assumed** 3.5% of their FY2026 payments until the total reaches $50M, with two fallback areas at an assumed 1% if the contracts fall short. The build's result: **28 steps to $50.2M a year.**

| Part of the $50.2M | Amount | Share | What supports it |
|---|---|---|---|
| Other controllable purchases: the $18M contract renegotiation, carried forward | $17.7M | 35% | its payment check is **Not seen yet** (payments to the four named contract types rose $10.1M) |
| IT hardware, software and services (laptop refresh, specifications, pricing) | $4.9M | 10% | its payment check is **Seen** |
| Telecom (mobile lines and plans, copper landlines) | $4.1M | 8% | mixed: mobile lines **Partly seen**, copper landlines **Not seen yet** |
| Fleet and fuel; print, copy and mail | $3.0M | 6% | both **Not seen yet** |
| 27 statewide contracts at an assumed 3.5% | $20.6M | 41% | nothing but the assumed rate (the card's own range is 2-5%) |

**So the headline "Plan reaches $50M" is conditional.** About 10% of the path has payment evidence behind it, about 8% mixed evidence, and the rest is either reported savings the payments data does not show (41%, mostly the $18M claim) or an assumed rate (41%). That is not the same as saying the savings are not real: payments checks are broad and reported savings may be measured against a plan (see `docs/models/savings.md`). It does mean the Overview should not read as a forecast. The build warns if more than half the path rests on assumed rates (it does not today: 41%).

**Recommendation (not applied).** Word the Overview's headline as a conditional ("a path to $50M if the reported savings recur and statewide contracts save 3.5%") and show the table above next to it; the plan's numbers are the owner's to present. One more consequence of the forecasts: Utilities & facility energy moved to the naive model (`docs/models/forecast.md`), which changes only the fallback steps, and only if the contracts fall short.

## Differences from the legacy pipeline

- **Recommendation 6 is read from this pipeline's data.** The legacy status said "Needs a data feed … the open data portal has 2016 files only". This pipeline reads every agency's Managing for Results plan, so that text is false here; the row now reports what was read, and falls back to the old wording only when the plans are not available in a run (tested).
- **History** (`previous` in `d_rec_status`) is kept in `data/rec_history.csv` and written only by a build that passed its checks, one row per run and recommendation. The legacy script wrote it for every run. The history starts with this build, so `previous` is empty until the next one, and it lives outside the database.
- Everything else is **identical to the legacy functions on the real data**: the vendor drill-downs on both bases (the bid-list basis and every other vendor on an area page), the path to $50M, and status rows 1 to 5 (`tests/test_recommendations_parity.py`).

## Checks that run on every build

All six recommendations have a status and a key number; the path is numbered, adds up and agrees with recommendation 4's status; vendor drill-downs add up to their payee names and every bid-list vendor has one; and a warning when more than half the path is assumed.

## Limits

- The contract rate (3.5%, range 2-5%) and the fallback rate (1%) are assumptions carried over from the legacy pipeline, not evidence.
- Step 1 depends on the forecasts, so it moves when the forecast model or the FY2027 plan moves.
- Payment evidence is by payee name and one pair of years; see `docs/models/savings.md`.
