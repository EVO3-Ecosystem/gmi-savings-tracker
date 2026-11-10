# Model notes: duplicate and split payment screen

**What it does.** Flags groups of State payments that a reviewer should look at because they could be a duplicate payment, a line published twice, or a purchase split to stay under the small-procurement threshold. It feeds the Opportunities tab's Payment screen and the Calculator's "Payment recovery review (leads)" lever. SQL: `sql/mart/47_v_payment_screen_rows.sql` (records in flagged groups, not published), `48_d_payment_screen.sql` (one row per group), `49_d_payment_screen_summary.sql` (by rule and year, with the measured confirmation rate and the lever), `50_d_source_issues.sql` (data-publication issues the screen found, kept out of the leads). Every threshold: `config/assumptions.yaml` (`payment_screen`), filled into the SQL by `src/pipeline/marts.py` (`{{section.key}}`). Checks: `phase5_payment_screen` and `phase5_source_issues` in `src/pipeline/checks.py`. The counts in this note's generated section come from the data (`src/models/doc_facts.py`, run by `make docs`).

**It is a screen, not an audit.** A flagged group is a lead to review, not an error and not money owed. Nothing here says a payment was wrong.

## The data's grain decides what can be measured

The payments dataset (7syw-q4cy) is **one row per paying agency, payee name, ZIP and fiscal year**: about 23,000 rows a year, each an annual total. Its `date` column is a record date (Jan 1 of the year; for FY2022 some rows carry Jan 1, 2023), not a payment date, and `fiscal_period` is a placeholder (column dictionary). There are no individual payments and no payment dates. So:

* the duplicate rule's 7-day window can only compare record dates (records with the same date fall in it);
* the split rule (several small payments within 14 days) **cannot be measured**: an annual total under the small-procurement limit says nothing about the payments inside it. It is written and runs only when a screened year has at least `transaction_grain_min_dates` (24) distinct dates; on this data it flags nothing and the summary says "Not measurable";
* a third rule, **repeated annual line**, covers what annual records can show: the same exact annual amount for the same agency and company twice in one fiscal year, with record dates further apart than the window. It applies only to annual records (on payment-level data, equal amounts weeks apart are normal recurring payments).

The rules were written down before the counts below were taken; the grain was inspected first because the windows cannot be applied without knowing it.

## Rules

Screened: full payment years FY2022-FY2026 (the partial latest year is never screened), amounts above zero. Left out, reusing the pipeline's payee rules: payees flagged government or institutional (`ref.map_payee_vendor.is_government`), payee types Government (transfers to government), Health care organization (health plans, benefits) and Financial institution (debt service, paying agents) from `reference/payee_type_rules.csv`, payroll-, benefit- and court-like payee names (`exclude_payee_pattern`), and pass-through payments (`reference/payee_area_exclusions.csv`, as `mart.payment_area` applies it). Agency = budget agency code (agency name as paid when unmatched); vendor = the company after payee names are grouped.

| Rule | Groups records that have | At this data's grain |
|---|---|---|
| Possible duplicate | same agency, vendor and exact amount (to the cent, each $1,000+), record dates within 7 days | measured |
| Repeated annual line | same agency, vendor and exact amount ($1,000+) twice or more in one fiscal year, record dates more than 7 days apart; not already a duplicate | measured (annual records only) |
| Possible split purchase | same agency and vendor, 2+ payments within 14 days, each under the small-procurement limit on the record date ($50,000 before Oct 1, 2023, $100,000 from then: SF&P 13-109(a)(1), Ch. 161 of 2023), together above it | not measurable |

A record is in at most one group (precedence: duplicate, repeated line, split). When two rules flag the same agency, vendor and year, `also_flagged_under` labels it; dollars are never counted twice. `review_amount` is what a review could recover if a group is confirmed: every copy after the first (amount x (n - 1)); 0 for a split (a compliance lead, not an overpayment). A "Business or other" payee none of whose names looks like an organization may be an individual and is shown as "Payee not named (may be an individual)" (41 of the 205 groups before the source issues were split out; 2 of the 8 leads now).

## Source verification: the FY2022 double listing is in the published source (checked Nov 10, 2026)

Queried directly, not through the pipeline (`docs/reconciliation/crosschecks_2026-11-10.csv`):

* **opendata.maryland.gov, dataset 7syw-q4cy** (SoQL `$group=fiscal_year,date`; rows updated 2026-11-09): FY2022 holds 23,440 rows dated Jan 1, 2022 ($35,782,271,603.50) **and 539 rows dated Jan 1, 2023 ($874,477,234.00)**. FY2021 and FY2023 each carry a single date. All 539 second-block rows belong to two agencies: Maryland Transportation Authority (category J11; 218 rows, $781,246,241.38) and Maryland Environmental Service (category U10; 321 rows, $93,230,992.62).
* MDTA's FY2022 therefore totals $1,497,976,993.74 (212 rows, $716.73M, dated 2022 + 218 rows, $781.25M, dated 2023) against $799.12M in FY2023. MES: $95.81M + $93.23M against $109.99M in FY2023.
* The second block is **not FY2023 mislabeled**: only 1 of its 539 rows equals a FY2023 row. 212 of its rows (MDTA 91, $75.11M; MES 121, $34.69M) equal a first-block row in payee, ZIP and amount; the others differ, which looks like two versions of the same year's file loaded together.
* **vendorpayments.maryland.gov** `api/opex/totals.json?year=2022` returns $36,656,748,837.50 = $35,782,271,603.50 + $874,477,234.00: the State's own payments site counts the second block too. FY2023 ($39,277,722,859.48) matches the pipeline to the cent. The pipeline's FY2022 total equals the site's.

**Conclusion: the duplicate is in the published source**, on both State sites, not introduced by this pipeline. The pairs the screen found there are a data-publication issue, so they are reported in `mart.d_source_issues`, not as payment leads (below). The question goes to the Comptroller's open-data team; nothing about it is a vendor overpayment.

## Leads and source issues are kept apart (gap 1)

Before Nov 10, 2026 the screen reported 205 groups ($98.6M review dollars); 197 of them were the FY2022 MDTA/MES pairs above. A repeated annual line is now a **source issue** when (rule fixed before re-measuring) it sits in an agency-year whose records carry more than one record date and its records differ only by record date (Jan 1 of consecutive years). Such groups get `source_issue_id` in `mart.v_payment_screen_rows` and are reported in `mart.d_source_issues` (one row per agency-year: the second block's records and dollars, the records identical to the first block, the screen groups moved, where and when it was verified). `mart.d_payment_screen` keeps only the remaining leads. Build check: no record is both a lead and a source issue, and leads + source issues = every flagged record; a second check holds the verified issues to the dollars seen at the source ($874,477,234.00).

## Confidence of each lead (gap 5)

Rules fixed before the leads were scored (`payment_screen.confidence`): score = +1 if the amount is not a multiple of $100 (cents or single dollars); -1 if it is a multiple of $1,000; +1 if every record was paid by one paying unit, -1 if by different paying units (each unit's own record); -1 if the same agency, vendor and amount appear in another screened year (a recurring contract or grant); -1 if the amount is under $5,000; -1 for a Non-profit payee (grants come in equal installments). **high** = score 1 or more, **low** = -1 or less, **medium** otherwise; split-purchase leads are low. Column: `confidence` (and `confidence_score`).

## Evidence review of every lead (gap 3)

From the data only: the raw records (paying unit, its code, payee name, ZIP), the vendor's payments by the same agency in the other screened years, and the same amount paid to the vendor by other units. No invoice is visible, so the review **never marks a confirmed overpayment**. `review_status`: **confirmed_duplicate_in_source** = the records are identical in every published field (one line published twice); **likely_legitimate** = different paying units and the payee got exactly this amount from at least 3 units that year (a sponsorship or fee pattern); **needs_records** otherwise; **unreviewed** = split purchases (the review does not cover them). `review_note` says why in one line. Findings on this extract: the five FY2022 capital pairs and the FY2025 housing pair are each recorded by two capital paying units (category codes 600 Comptroller capital / 602 DGS capital / 606 DHCD capital), so one grant booked twice or two grants: needs the grant agreements. Two leads are one paying unit with two payee ZIPs for the same amount (the double-invoice pattern): needs the invoices. One is a $5,000 payment made by three MDOT and Lottery units to the same payee in FY2024: likely legitimate.

The review sheet for a person's decision is `docs/reviews/payment_screen_review_sheet.csv` (one row per lead; `her_decision`: duplicate_payment / not_duplicate / source_publishing_issue / records_requested / cannot_tell, and `notes`; filled-in values are kept when the sheet is regenerated).

## Calculator lever

"Payment recovery review (leads)" = review dollars of `payment_screen.lever.fy` (FY2026) x a confirmation rate that is now **derived, not assumed** (`sql/mart/49`): measured rate = leads confirmed / leads reviewed; likely = that rate, low / high = its Wilson 95% interval. The review can confirm none of the leads from the data (none is identical in every field), so `measured_confirmation_rate` is NULL, `rate_basis` = "not measurable without payment records", and the lever is **0 at every rate** with that label. The old 2% / 5% / 10% placeholders are retired. FY2026 has no lead in any case. The lever is a recovery of past payments, not a recurring saving, and is not added to the plan's savings unless the user turns it on.

Note: a confirmed_duplicate_in_source lead is a publication issue, not recoverable money; a rate worth putting in the lever needs payment records (the reviewer's `her_decision` = duplicate_payment, from invoices). Until then the honest lever is 0.

## Results

<!-- facts:payment_screen -->
_Generated from `mart.d_payment_screen`, `mart.d_source_issues` and `mart.d_payment_screen_summary`, extract run 20261109T154457Z, by `python -m src.models.doc_facts`._

**Payment leads: 8 groups, 16 records, $3.72M in groups, $1.86M review dollars.**

| Rule | Confidence | Review status | Groups | Records | Review dollars |
|---|---|---|---|---|---|
| Possible duplicate | high | needs_records | 1 | 2 | $4,897 |
| Possible duplicate | low | likely_legitimate | 1 | 2 | $5,000 |
| Possible duplicate | low | needs_records | 5 | 10 | $1.83M |
| Possible duplicate | medium | needs_records | 1 | 2 | $25,000 |

**Source issues (not leads): 2**, 197 screen groups moved out of the leads ($96.73M review dollars they carried).

| Issue | Agency | Second-block records | Second-block dollars | Identical to first block | Screen groups | Status |
|---|---|---|---|---|---|---|
| SRC-2022-J11 | MARYLAND TRANSPORTATION AUTHORITY | 218 | $781.25M | 91 | 81 | In published source (both State sites); ask the Comptroller's open-data team which FY2022 block is current |
| SRC-2022-U10 | MARYLAND ENVIRONMENTAL SERVICE | 321 | $93.23M | 121 | 116 | In published source (both State sites); ask the Comptroller's open-data team which FY2022 block is current |

**Backtest, by year** (lead groups / review dollars): FY2022 5 / $852,000; FY2023 0 / $0; FY2024 1 / $5,000; FY2025 2 / $1.00M; FY2026 0 / $0.

**Measured confirmation rate:** not measured (not measurable without payment records; 8 leads reviewed, 0 confirmed). Lever rates low / likely / high: 0.0% / 0.0% / 0.0%.
<!-- /facts:payment_screen -->

## Do fiscal_period and date vary within a fiscal year? (gap 4, Nov 10, 2026)

Distinct values by fiscal year in the raw extract (`raw.payments`, `raw.grants`, run 20261109T154457Z):

* **Payments (7syw-q4cy):** `fiscal_period` is "1" on every row of every year FY2008-FY2027 (1 distinct value per year). `date` has one value per year (Jan 1 of the year) except FY2008, FY2009 and FY2012 (one Baltimore City Community College row each dated Jan 1 of the next year) and FY2022 (539 MDTA/MES rows dated Jan 1, 2023: the source issue above).
* **Grants (absk-avps):** `fiscalperiod` is "1" and `date` is June 30 of the year on every row, FY2009-FY2025 (1 distinct value each).

So neither dataset varies within a fiscal year: **monthly or payment-date analysis is not possible** on the published data, the split rule stays "Not measurable", and the duplicate window compares record dates only. What would change that is in `docs/data-governance.md`, "Data requests".

## To make it useful

Payment-level data (date, document or invoice number, amount) from the Comptroller's FMIS would let the 7- and 14-day windows work as intended and would turn the split rule on without code changes.
