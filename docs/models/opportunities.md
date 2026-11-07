# Model card: opportunity detectors and the bid list

**What it does.** Screens the State's controllable spending for places a saving is plausible, and ranks private vendors that many agencies pay separately. It feeds the dashboard's Opportunities tab and the first recommendation (bid statewide contracts for shared vendors). Code: `src/models/opportunities.py` (a port of `legacy/gst/scripts/opportunities.py` and the bid list in `legacy/gst/scripts/recs.py`); every threshold and rate: `config/assumptions.yaml` (`opportunities`); tables: `mart.d_opps` and `mart.d_bid_list`.

**It is a screening tool, not a forecast of savings.** The saving rates are percentages carried over from the legacy pipeline (the Assumptions register in `docs/data-governance.md`); no detector has been tested against what spending actually did next. A finding is a lead to ask about, not a number to bank.

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
2. **Some growth findings look like re-coding, not growth.** 38 of the growth detector's 166 findings grew 1,000% or more (for example Food Services at Public Safety and Correctional Services, +42,462%; Food at the Health department, +2,090%) and carry **$52.0M, 38% of that detector's $135.7M**. A line that jumps from a few thousand dollars to millions is more likely a budget line that was renamed or moved than a saving to chase. The build warns when this share exceeds 25% (it does: 38%).
3. **The rates are assumptions.** The percentages are not evidence of what a renegotiation yields.

**A minimum prior-year base removes most of the re-coding.** `opportunities.growth.min_base_budget` (default 0, the legacy rule, so parity holds). Measured on this build:

| Minimum prior-year spending | Growth findings kept | Growth likely saving kept |
|---|---|---|
| None (legacy) | 166 | $135.7M |
| $100k | 134 | $122.1M (90%) |
| $250k | 107 | $104.7M (77%) |
| $1M (roadmap gap 7) | 39 | $93.8M (69%) |

**Recommendation (not applied).** Set the minimum base to $1M, as the roadmap already proposes (gap 7), and word the headline as "leads worth up to" rather than a total. This changes dashboard numbers, so it is the owner's decision; one line in `config/assumptions.yaml`.

## Limits

- No backtest: whether flagged agencies and codes later spent less than unflagged ones has not been measured, and the rates have no evidence behind them beyond the legacy pipeline. This is roadmap gap 16 and the next step for this module.
- Peer comparisons ignore mission: agencies differ, so a high spend per position can be legitimate. The tool only counts a share of the excess for that reason.
- The vendor list is built from payee names grouped into companies (`reference/vendor_*.csv`); grouping errors carry through.
- The not-biddable list is a name pattern (`bid_list.not_biddable`), so a vendor can be wrongly kept or dropped.

## Checks that run on every build

Findings are well formed (low at most high, no duplicate id, one per agency and code); bid-list vendors meet the thresholds and are ranked by FY2026 payments; and a warning when the growth detector leans on re-coded-looking findings.
