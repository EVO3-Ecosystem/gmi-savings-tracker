# Model card: opportunity detectors and the bid list

**What it does.** Screens the State's controllable spending for places a saving is plausible, and ranks private vendors that many agencies pay separately. It feeds the dashboard's Opportunities tab and the first recommendation (bid statewide contracts for shared vendors). Code: `src/models/opportunities.py` (a port of `legacy/gst/scripts/opportunities.py` and the bid list in `legacy/gst/scripts/recs.py`); every threshold and rate: `config/assumptions.yaml` (`opportunities`); tables: `mart.d_opps` and `mart.d_bid_list`.

**It is a screening tool, not a forecast of savings.** The saving rates are percentages carried over from the legacy pipeline (the Assumptions register in `docs/data-governance.md`); the first-stage backtest below only follows flags one year, it does not test the rates. A finding is a lead to ask about, not a number to bank.

## The detectors

| Detector | Looks at | Flags | Saving counted |
|---|---|---|---|
| Peer gap | FY2025 actual controllable spending per budgeted position, by spending code, agencies with 50+ positions and 8+ comparable agencies | an agency above the 75th percentile of its peers | 5-15% of the spending above the 75th percentile, at most 3-10% of the agency's spending on the code |
| Growth above trend | FY2022 to FY2025 spending by agency and code | growth 25+ points faster than the state's on the same code, on $500k+ | 10-30% of the growth above the state's pace |
| Tail spend | FY2026 private-vendor payments by focus area | payments to vendors outside the ten largest, over $1M | 3-10% |
| Leverage | FY2026 private-vendor payments | one vendor paid separately by 10+ agencies, $5M+ | 2-5% |

Findings at the same agency and spending code are listed once (the larger kept). The **bid list** is the vendor-level view: private vendors paid separately by 10+ agencies, $5M+ in FY2026, minus service providers and regulated utilities (not biddable), at 2-5%.

## Parity with the legacy pipeline

On this pipeline's marts the port gives **exactly the legacy scripts' output**: 453 findings and a 30-vendor bid list (`tests/test_opportunities_parity.py` runs both on the same inputs). One deliberate difference: an agency's name is its latest one; the legacy script took whichever row came first, which depends on row order. Eleven tests on constructed cases (`tests/test_opportunities.py`) pin each rule, including the percentile, the cap, the tie-break between detectors and the exclusions, and run in CI.

## What the numbers show (FY2025 and FY2026 data, Nov 7, 2026 build)

| Detector | Findings | Likely saving | Range |
|---|---|---|---|
| Peer gap | 246 | $93.4M | $43.8M-$143.1M |
| Growth above trend | 166 | $135.7M | $67.9M-$203.6M |
| Leverage | 38 | $27.5M | $15.7M-$39.3M |
| Tail spend | 3 | $1.6M | $0.8M-$2.5M |
| **All** | **453** | **$258.3M** | **$128.1M-$388.4M** |

Bid list: 30 vendors, $21.1M likely.

**Do not read $258M as the size of the opportunity.** Three reasons, all measured:

1. **The findings are not additive.** The budget detectors flag $3.08B of baseline spending and the payment detectors $0.81B of the same money seen from the payments side; only the two budget detectors are de-duplicated against each other.
2. **Some growth findings look like re-coding, not growth.** 38 of the growth detector's 166 findings grew 1,000% or more (for example Food Services at Public Safety and Correctional Services, +42,462%; Food at the Health department, +2,090%) and carry **$52.0M, 38% of that detector's $135.7M**. A line that jumps from a few thousand dollars to millions is more likely a budget line that was renamed or moved than a saving to chase. The build warns when this share exceeds 25% (it did at the legacy setting: 38%; with the $1M minimum it is 22%).
3. **The rates are assumptions.** The percentages are not evidence of what a renegotiation yields.

**A minimum prior-year base removes most of the re-coding.** `opportunities.growth.min_base_budget` (default $1M since Nov 7, 2026; 0 is the legacy rule, which the parity test sets explicitly). Measured on this build:

| Minimum prior-year spending | Growth findings kept | Growth likely saving kept |
|---|---|---|
| None (legacy) | 166 | $135.7M |
| $100k | 134 | $122.1M (90%) |
| $250k | 107 | $104.7M (77%) |
| $1M (roadmap gap 7) | 39 | $93.8M (69%) |

**Applied Nov 7, 2026.** The minimum base is $1M, as the roadmap proposed (gap 7): 39 growth findings and $93.8M likely saving remain, and the share from findings that grew 1,000% or more fell from 38% to 22%, so the build check now passes. Findings still read as leads worth up to a range, not a total: the rates are screening assumptions. The legacy behaviour is one line in `config/assumptions.yaml`.

## Limits

- Backtest, first stage only (below): flags are followed one year. Whether a flag leads to a saving has not been measured, and the rates have no evidence behind them beyond the legacy pipeline.
- Public higher education (R13, R14, R30, R95) is left out of every input since Nov 9, 2026 (`gmi_baseline_exclusions` in `config/assumptions.yaml`): only R95 Baltimore City Community College appears in the payments data ($15.9M of FY2026 private payments). The likely saving fell by $0.11M ($225.84M to $225.74M: Leverage $27.48M to $27.40M, Tail spend $1.63M to $1.60M); the bid list stays 30 vendors ($12.06M-$30.16M to $12.04M-$30.10M).
- Peer comparisons ignore mission: agencies differ, so a high spend per position can be legitimate. The tool only counts a share of the excess for that reason.
- The vendor list is built from payee names grouped into companies (`reference/vendor_*.csv`); grouping errors carry through.
- The not-biddable list is a name pattern (`bid_list.not_biddable`), so a vendor can be wrongly kept or dropped.

## Checks that run on every build

Findings are well formed (low at most high, no duplicate id, one per agency and code); bid-list vendors meet the thresholds and are ranked by FY2026 payments; and a warning when the growth detector leans on re-coded-looking findings.

## Backtest, first stage: do flags recur, and what did flagged spending do next year? (Nov 9, 2026)

Code: `src/models/backtest.py`; table: `mart.d_detector_backtest` (24 rows: 4 detectors x 3 as-of years x 2 cohorts); tests: `tests/test_backtest.py` (the backtest's flags equal `detect()`'s findings, and nothing after the next year is read). Built and checked on every build.

**Design, fixed before measuring.** Each detector is rerun as of FY2022, FY2023 and FY2024 on data up to that year only, with the live thresholds and the same look-back (growth compares year T with T-3; the payment detectors use year-T payments), and again as of T+1. Window: one year, T to T+1 (all actual years).

| | Unit | Flagged cohort | Not-flagged cohort (same size and comparability filters, not flagged) | Spending followed |
|---|---|---|---|---|
| Peer gap | agency x spending code | above the 75th percentile per position | 50+ positions, 8+ comparable agencies, $250k+ | controllable actual budget |
| Growth above trend | agency x spending code | grew 25+ points faster than the state on the code | $1M+ base at T-3, $500k+ at T | controllable actual budget |
| Tail spend | focus area | over $1M outside the ten largest vendors | every other area with private payments | payments to the vendors outside the ten largest at T |
| Leverage | private vendor | paid by 10+ agencies | paid $5M+ by fewer than 10 agencies | the vendor's payments |

Flags are each detector's own, before the two budget detectors are de-duplicated against each other.

**Results (pooled over FY2022-FY2024; per-year rows in the table).**

| Detector | Cohort | Unit-years | Flagged again next year | Spending, as-of years | Same units, next year | Pooled change |
|---|---|---|---|---|---|---|
| Peer gap | Flagged | 907 | 694 (77%) | $8.46B | $7.84B | -7.3% |
| Peer gap | Not flagged | 849 | 77 (9%) | $1.73B | $1.90B | +9.3% |
| Growth above trend | Flagged | 144 | 55 (38%) | $2.81B | $2.20B | -21.9% |
| Growth above trend | Not flagged | 631 | 72 (11%) | $7.44B | $7.94B | +6.7% |
| Tail spend | Flagged | 9 | 9 (100%) | $74.5M | $75.4M | +1.3% |
| Tail spend | Not flagged | 9 | 0 | $1.1M | $1.3M | +13.7% |
| Leverage | Flagged | 79 | 72 (91%) | $1.64B | $1.77B | +7.7% |
| Leverage | Not flagged | 1,525 | 7 (0.5%) | $54.48B | $50.45B | -7.4% |

Persistence by year: Peer gap 78%, 76%, 76%; Growth 40%, 33%, 41%; Leverage 87%, 93%, 93%; Tail spend 3 of 3 areas each year.

**How to read it.**

- **Peer gap and Leverage flags are stable** (three in four, and nine in ten, recur): they describe lasting structure (an agency's cost per position, a vendor many agencies use), so a lead stays open long enough to act on.
- **Growth flags mostly do not recur** (38%), and flagged lines fell 22% the next year while like-sized unflagged lines grew 7%. That is what regression to the mean and one-off re-coding predict for a detector that selects on unusual growth; it is not evidence that anyone acted on a flag or that a saving was made. Peer-gap lines (selected for being high) fell 7% while unflagged ones grew 9%, for the same reason.
- **Tail spend** has only three areas each year (all flagged every year), too few to compare. **Leverage's** not-flagged cohort is about $18B a year of private payees paid by fewer than ten agencies, a very different population from the 23-29 flagged vendors, so the comparison says little about them.

**Limitations.** Descriptive, not causal: flagged and unflagged units differ in more than the flag. One-year window only; budget lines are re-coded between years, so a "fall" can be a move to another code (12 flagged peer-gap unit-years had no spending the next year). Units are counted once per as-of year, so the pooled rows repeat the same agency-codes across years and are not independent. Nominal dollars. The four detectors' cohorts overlap (the same spending appears on the budget and the payments side), and the as-of years overlap each other, so **no row may be added to another**, and no detector's change may be added to another's. Next stage: a longer window, real dollars (`mart.d_deflator`), and matching flagged units to unflagged ones of similar size and trend before comparing.
