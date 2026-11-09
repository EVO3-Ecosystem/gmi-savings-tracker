# Model notes: duplicate and split payment screen

**What it does.** Flags groups of State payments that a reviewer should look at because they could be a duplicate payment, a line published twice, or a purchase split to stay under the small-procurement threshold. It feeds the Opportunities tab's Payment screen and the Calculator's "Payment recovery review (leads)" lever. SQL: `sql/mart/47_v_payment_screen_rows.sql` (records in flagged groups, not published), `48_d_payment_screen.sql` (one row per group), `49_d_payment_screen_summary.sql` (by rule and year). Every threshold: `config/assumptions.yaml` (`payment_screen`), filled into the SQL by `src/pipeline/marts.py` (`{{section.key}}`). Checks: `phase5_payment_screen` in `src/pipeline/checks.py`.

**It is a screen, not an audit.** A flagged group is a lead to review, not an error and not money owed. Nothing here says a payment was wrong.

## The data's grain decides what can be measured

The payments dataset (7syw-q4cy) is **one row per paying agency, payee name, ZIP and fiscal year**: about 23,000 rows a year, each an annual total. Its `date` column is a record date (Jan 1 of the year; for FY2022 some rows carry Jan 1, 2023), not a payment date, and `fiscal_period` is a placeholder (column dictionary). There are no individual payments and no payment dates. So:

* the duplicate rule's 7-day window can only compare record dates (records with the same date fall in it);
* the split rule (several small payments within 14 days) **cannot be measured**: an annual total under $50,000 says nothing about the payments inside it. It is written and runs only when a screened year has at least `transaction_grain_min_dates` (24) distinct dates; on this data it flags nothing and the summary says "Not measurable";
* a third rule, **repeated annual line**, covers what annual records can show: the same exact annual amount for the same agency and company twice in one fiscal year, with record dates further apart than the window. It applies only to annual records (on payment-level data, equal amounts weeks apart are normal recurring payments).

The rules were written down before the counts below were taken; the grain was inspected first because the windows cannot be applied without knowing it.

## Rules

Screened: full payment years FY2022-FY2026 (the partial latest year is never screened), amounts above zero. Left out, reusing the pipeline's payee rules: payees flagged government or institutional (`ref.map_payee_vendor.is_government`), payee types Government (transfers to government), Health care organization (health plans, benefits) and Financial institution (debt service, paying agents) from `reference/payee_type_rules.csv`, payroll-, benefit- and court-like payee names (`exclude_payee_pattern`), and pass-through payments (`reference/payee_area_exclusions.csv`, as `mart.payment_area` applies it). Agency = budget agency code (agency name as paid when unmatched); vendor = the company after payee names are grouped.

| Rule | Groups records that have | At this data's grain |
|---|---|---|
| Possible duplicate | same agency, vendor and exact amount (to the cent, each $1,000+), record dates within 7 days | measured |
| Repeated annual line | same agency, vendor and exact amount ($1,000+) twice or more in one fiscal year, record dates more than 7 days apart; not already a duplicate | measured (annual records only) |
| Possible split purchase | same agency and vendor, 2+ payments within 14 days, each under $50,000 (**assumed, verify against COMAR/Procurement Manual**; no statute citation published), together above it | not measurable |

A record is in at most one group (precedence: duplicate, repeated line, split). When two rules flag the same agency, vendor and year, `also_flagged_under` labels it; dollars are never counted twice. `review_amount` is what a review could recover if a group is confirmed: every copy after the first (amount x (n - 1)); 0 for a split (a compliance lead, not an overpayment). A "Business or other" payee none of whose names looks like an organization may be an individual and is shown as "Payee not named (may be an individual)" (41 of 205 groups).

## Results (Nov 9, 2026 extract, run 20261109T154457Z)

| Rule | Groups | Records | Dollars in groups | Review dollars |
|---|---|---|---|---|
| Possible duplicate | 8 | 16 | $3.72M | $1.86M |
| Repeated annual line | 197 | 394 | $193.45M | $96.73M |
| Possible split purchase | not measurable | | | |

**Backtest, by year** (groups / review dollars): FY2022 202 / $97.58M; FY2023 0 / $0; FY2024 1 / $5,000; FY2025 2 / $1.00M; FY2026 0 / $0.

The screen is **not stable across years, and that is the finding**: 197 of the 205 groups are FY2022 lines of two agencies, Maryland Transportation Authority (81 groups, $62.56M) and Maryland Environmental Service (116 groups, $34.17M), published once with a Jan 1, 2022 record date and again with Jan 1, 2023 under fiscal year 2022 (MDTA's FY2022 payments total $1.50B against $0.80B in FY2023 and $0.84B in FY2024). That looks like a publication duplicate in the dataset rather than double payments: the first thing to ask is the Comptroller's open-data team, not the vendors. Outside FY2022 the screen finds three small groups in four years. With no payment-level dates, the screen cannot see real duplicate payments inside an annual total.

## Calculator lever

"Payment recovery review (leads)" = review dollars of `payment_screen.lever.fy` (FY2026) x an assumed confirmation rate: low 2%, likely 5%, high 10%. The rates are **assumptions, to be replaced by the share confirmed in a reviewed sample**. FY2026 has no flagged groups, so the lever is $0 at every rate on this data; the page also offers the FY2022-FY2026 yearly average (review dollars $19.72M a year, which is almost all the FY2022 publication duplicate). The lever is shown separately and is not added to the plan's savings unless the user turns it on: it is a recovery of past payments, not a recurring saving, and it may overlap other findings.

## To make it useful

Payment-level data (date, document or invoice number, amount) from the Comptroller's FMIS would let the 7- and 14-day windows work as intended and would turn the split rule on without code changes.
