-- mart.d_payment_screen (dashboard Opportunities tab: Payment screen)
-- Grain: one row per flagged group (mart.v_payment_screen_rows) that is a payment lead: leads to review, not errors.
-- Groups that are a data-publication issue (source_issue_id set, e.g. the FY2022 MDTA/MES double listing) are not leads:
-- they are reported in mart.d_source_issues, and a check makes sure no record is in both.
-- What: the agency (the pipeline's cleaned name from mart.agency_master; agency_raw = the name as paid), vendor, fiscal year,
-- record dates, number of records and dollars of each group. review_amount is the money a review could recover if the group
-- is confirmed: for a duplicate or repeated line, every copy after the first (amount x (n - 1)); a split purchase recovers
-- nothing by itself (0; it is a procurement-compliance lead). A payee whose type is "Business or other" and none of whose
-- payee names (as paid) looks like an organization (payment_screen.org_name_pattern) may be an individual and is never
-- shown by name. also_flagged_under names any other rule that flags the same agency, vendor and year.
-- confidence (high/medium/low): rules fixed before measuring (config payment_screen.confidence; docs/models/payment_screen.md).
-- review_status / review_note: an evidence review from the data alone (raw records, other years, the vendor's other
-- payments); without invoices it can never confirm an overpayment (config payment_screen.review).
CREATE OR REPLACE TABLE mart.d_payment_screen AS
WITH v AS (SELECT * FROM mart.v_payment_screen_rows WHERE source_issue_id IS NULL),
g AS (
  SELECT group_id, rule, any_value(date_grain) AS date_grain, min(fiscal_year) AS fiscal_year, any_value(agency_key) AS agency_key,
         any_value(agency_code) AS agency_code, mode(agency_name_as_paid) AS agency_raw, any_value(vendor) AS vendor_full,
         bool_or(regexp_matches(upper(vendor_name_as_paid), {{payment_screen.org_name_pattern}})) AS org_name, any_value(payee_type) AS payee_type,
         min(record_date) AS first_date, max(record_date) AS last_date, count(*) AS n,
         CASE WHEN rule = 'Possible split purchase' THEN NULL ELSE max(amount) END AS amount,
         sum(amount) AS total_amount,
         CASE WHEN rule = 'Possible split purchase' THEN 0 ELSE sum(amount) - max(amount) END AS review_amount,
         count(DISTINCT vendor_name_as_paid) AS payee_names, count(DISTINCT vendor_zip) AS zips,
         count(DISTINCT agency_name_as_paid) AS units, count(DISTINCT coalesce(agency_code_as_paid, '')) AS unit_codes,
         string_agg(DISTINCT agency_name_as_paid, '; ' ORDER BY agency_name_as_paid) AS unit_names,
         round(max(amount) * 100) AS cents
  FROM v GROUP BY group_id, rule
), o AS (
  SELECT a.group_id, string_agg(DISTINCT b.rule, '; ' ORDER BY b.rule) AS also_flagged_under
  FROM g a JOIN g b ON a.agency_key = b.agency_key AND a.vendor_full = b.vendor_full AND a.fiscal_year = b.fiscal_year AND a.rule <> b.rule
  GROUP BY 1
), pay AS (  -- every positive payment of the screened years, keyed like the screen (agency, company, cents)
  SELECT p.fiscal_year, coalesce(p.agency_code, p.agency_name_as_paid) AS agency_key, p.agency_name_as_paid, m.vendor, round(p.amount * 100) AS cents
  FROM core.fact_payment_mapped p JOIN ref.map_payee_vendor m ON m.payee = p.vendor_name_as_paid
  WHERE p.fiscal_year BETWEEN {{payment_screen.first_fy}} AND {{payment_screen.last_fy}} AND NOT p.partial_year AND p.amount > 0
), ev AS (  -- evidence per group from the data
  SELECT g.group_id,
         (SELECT count(DISTINCT fiscal_year) FROM pay WHERE pay.agency_key = g.agency_key AND pay.vendor = g.vendor_full AND pay.fiscal_year <> g.fiscal_year) AS other_years,
         (SELECT count(DISTINCT fiscal_year) FROM pay WHERE pay.agency_key = g.agency_key AND pay.vendor = g.vendor_full AND pay.cents = g.cents AND pay.fiscal_year <> g.fiscal_year) AS same_amount_years,
         (SELECT count(DISTINCT agency_name_as_paid) FROM pay WHERE pay.vendor = g.vendor_full AND pay.cents = g.cents AND pay.fiscal_year = g.fiscal_year) AS units_same_amount
  FROM g
), s AS (
  SELECT g.*, ev.other_years, ev.same_amount_years, ev.units_same_amount,
         CASE WHEN g.rule = 'Possible split purchase' THEN NULL ELSE
           (CASE WHEN g.cents % ({{payment_screen.confidence.round_cents_low}} * 100) <> 0 THEN 1 ELSE 0 END)
         - (CASE WHEN g.cents % ({{payment_screen.confidence.round_unit}} * 100) = 0 THEN 1 ELSE 0 END)
         + (CASE WHEN g.units = 1 THEN 1 ELSE -1 END)
         - (CASE WHEN ev.same_amount_years > 0 THEN 1 ELSE 0 END)
         - (CASE WHEN g.amount < {{payment_screen.confidence.small_amount}} THEN 1 ELSE 0 END)
         - (CASE WHEN g.payee_type = 'Non-profit' THEN 1 ELSE 0 END) END AS confidence_score
  FROM g JOIN ev USING (group_id)
)
SELECT s.group_id, s.rule, s.fiscal_year, s.agency_code,
       coalesce(am.agency, s.agency_raw) AS agency, s.agency_raw,
       CASE WHEN s.payee_type <> 'Business or other' OR s.org_name THEN s.vendor_full
            ELSE 'Payee not named (may be an individual)' END AS vendor,
       s.payee_type, s.first_date, s.last_date, s.n, s.amount, s.total_amount, s.review_amount, s.payee_names, s.zips,
       o.also_flagged_under, s.date_grain,
       s.confidence_score,
       CASE WHEN s.confidence_score IS NULL THEN 'low'
            WHEN s.confidence_score >= {{payment_screen.confidence.high_min}} THEN 'high'
            WHEN s.confidence_score <= {{payment_screen.confidence.low_max}} THEN 'low' ELSE 'medium' END AS confidence,
       CASE WHEN s.rule = 'Possible split purchase' THEN 'unreviewed'
            WHEN s.units = 1 AND s.unit_codes = 1 AND s.payee_names = 1 AND s.zips = 1 THEN 'confirmed_duplicate_in_source'
            WHEN s.units > 1 AND s.units_same_amount >= {{payment_screen.review.pattern_min_units}} THEN 'likely_legitimate'
            ELSE 'needs_records' END AS review_status,
       CASE WHEN s.rule = 'Possible split purchase' THEN 'Not reviewed: the split rule needs payment-level dates'
       ELSE concat_ws('; ',
         CASE WHEN s.units = 1 AND s.unit_codes = 1 AND s.payee_names = 1 AND s.zips = 1
                   THEN 'records identical in every published field (paying unit, code, payee name, ZIP): one line published twice'
              WHEN s.units = 1 THEN format('one paying unit, {} payee ZIPs (remit addresses) for the same amount: the classic double-invoice pattern', s.zips)
              ELSE format('{} paying units under one agency code ({}): each unit''s own record, so one payment booked twice or two payments', s.units, s.unit_names) END,
         CASE WHEN s.units > 1 AND s.units_same_amount >= {{payment_screen.review.pattern_min_units}}
                   THEN format('the payee got exactly this amount from {} paying units in FY{} (a sponsorship or fee pattern)', s.units_same_amount, s.fiscal_year) END,
         CASE WHEN s.same_amount_years > 0 THEN format('same agency, vendor and amount in {} other screened year(s): likely recurring', s.same_amount_years)
              WHEN s.other_years > 0 THEN format('agency paid this vendor in {} other screened year(s), never this amount', s.other_years)
              ELSE 'no payment by this agency to this vendor in the other screened years' END,
         CASE WHEN NOT (s.units = 1 AND s.unit_codes = 1 AND s.payee_names = 1 AND s.zips = 1)
                   AND NOT (s.units > 1 AND s.units_same_amount >= {{payment_screen.review.pattern_min_units}})
              THEN 'needs the invoices or grant agreements to tell one payment from two' END) END AS review_note
FROM s LEFT JOIN o USING (group_id)
LEFT JOIN (SELECT agency_code, any_value(agency) AS agency FROM mart.agency_master WHERE agency_code IS NOT NULL GROUP BY 1) am ON am.agency_code = s.agency_code
ORDER BY s.review_amount DESC, s.total_amount DESC, s.group_id;
