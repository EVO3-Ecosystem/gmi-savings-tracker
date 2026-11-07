# Model card: GMI's reported savings checked against payments

**What it does.** Lists the 18 savings the Government Modernization Initiative reported (Joint Chairmen's Report, January 26, 2026; each with its page and verbatim quote) and, where payments could show the saving, compares FY2025 with FY2026 payments to the vendors that sell the thing being cut. It also lists the vendors whose payments fell most, as candidates for the unnamed renegotiated contracts. Code: `src/models/savings.py` (a port of `legacy/gst/scripts/savings.py` and the recurrence status in `legacy/gst/scripts/recs.py`); the items and their payee patterns: `reference/gmi_reported_savings.csv`; years and thresholds: `config/assumptions.yaml` (`savings`); tables: `mart.d_savings`, `mart.f_savings_check`, `mart.d_savings_status`, `mart.d_vendor_moves`.

**It shows direction and size, not proof.** Payee names miss spending (office supplies are mostly bought on purchasing cards the payments data does not show), contracts change for other reasons, and a reported saving may be measured against a plan or an appropriation (avoided cost) rather than against last year's payments. A payment that did not fall does not mean a saving was not achieved; a payment that fell does not prove it was.

## How a check is read

For each check, payments in FY2025 (before) and FY2026 (after) are summed over the payees it names (`reference/gmi_reported_savings.csv`: a payee pattern, optionally limited to agencies, a focus area, or "the four named contract types together"). Where GMI gave a dollar figure:

| Status | Rule |
|---|---|
| Seen | payments fell by at least half the reported saving |
| Partly seen | payments fell, by less than half |
| Not seen yet | payments did not fall |

Where GMI gave no figure, the status is only *Payments fell* or *Payments did not fall*. `previous_status` and `changed` compare with the last earlier build (history in `data/savings_status_history.csv`, written only by a build that passed its checks, one row per run and check).

## What the November 7, 2026 build shows

| Check | Reported (midpoint) | Matching payments FY2025 | FY2026 | Change | Status |
|---|---|---|---|---|---|
| S06 paused vehicle purchases (one-time) | $8.0M | $28.9M | $21.2M | -$7.6M | **Seen** |
| S13-S15 laptop refresh, specifications, pricing | $4.9M | $61.4M | $54.8M | -$6.7M | **Seen** |
| S10-S11 mobile lines and plan catalog | $2.7M | $4.0M | $3.4M | -$0.6M | Partly seen |
| S01 the $18M renegotiated contracts (four contract types together) | $18.0M | $86.4M | $96.4M | +$10.1M | Not seen yet |
| S08-S09 fleet fuel and maintenance | $2.1M | $93.5M | $100.9M | +$7.4M | Not seen yet |
| S12 copper landlines | $1.55M | $33.9M | $39.9M | +$6.0M | Not seen yet |
| S16 shipping contract | $0.8M | $8.3M | $9.8M | +$1.5M | Not seen yet |

Of the seven checks that have a reported figure, **two are seen, one partly and four not seen**. Among the five checks with no figure, payments fell for two (S02 the food-services contract, S04 office supplies) and did not fall for three (S03 radio maintenance, S05 software licences, S17 leases).

**How to read this fairly.**
- The matching payments are broad (every payee that sells vehicles, fuel, carriers, shippers), so volume and price movements unrelated to GMI swamp a saving of $1-2M on $90M. A saving that is real but small, or measured against a plan, cannot show up here.
- The one-time and cost-avoidance items (S06 paused purchases, S07 vehicle sales, S18 the $326M of avoided facility costs) are a different kind of saving from a year-over-year reduction in payments; S07 and S18 have no payment line at all.
- The strongest statement the data supports is narrow: for the $18M renegotiated-contracts claim, payments to the four named contract types **rose** by $10M between FY2025 and FY2026, so the payments data neither shows nor refutes that saving. The report names no vendors, and the card does not pretend otherwise.

## Vendor moves

The 40 vendors paid by five or more agencies whose payments fell most between FY2025 and FY2026 (at least $1M in FY2025; construction, health plans, banks, schools and similar excluded): together **$71.9M** lower, led by Applied Technology Services (-$12.4M, 28 agencies), Apple Ford (-$8.2M, 14) and Gantech (-$4.3M, 9). They are leads for the "seven renegotiated contracts" GMI did not name, not findings: a payment can fall because a contract ended or the work finished.

**Changed from the legacy script (output on the real data is identical):** the list now contains *only decreases*. The legacy code sorted by change and took the first 40, so with fewer than 40 decreasing vendors it would have listed increases as "decreases". It does not show on this data, where all 40 are decreases; a test constructs the case. A year with no payments counts as zero instead of failing.

## Parity and tests

On this pipeline's payments the four tables are **identical to the legacy scripts' output** (`tests/test_savings_parity.py`). `tests/test_savings.py` (data-free, in CI) pins each kind of payee check (plain pattern, agency-limited, the four-type union, "checked together", focus area with pass-through excluded), the status thresholds, the history (one row per run, a rerun replaces itself and is compared with the run before it), the vendor-move filters and cap, and that the reference file still equals the legacy items. A failed build records no history (`tests/test_fault_injection.py`).

## Checks that run on every build

Every reported item is unique, cites a page and a quote, and has low at most high; every payment check matches payments and the four named contract types are checked; every check has a status (the build reports how many are Seen, Partly seen and Not seen yet); vendor moves are decreases by vendors paid by enough agencies.

## Limits

- Matching is by payee name, so a vendor under an unexpected name is missed and a payee that also sells other things is over-counted (the S05 note flags that SHI and CDW sell both software and laptops).
- One year-over-year comparison. A different pair of years, or a trend, could tell a different story; the years are settings.
- The status history starts with this build; `previous_status` and `changed` are empty until the next one. The history file lives in `data/`, outside the database, so a database snapshot does not carry it.
- Nothing here measures whether a saving was achieved against what the State would otherwise have spent.
