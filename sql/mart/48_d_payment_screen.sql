-- mart.d_payment_screen (dashboard Opportunities tab: Payment screen)
-- Grain: one row per flagged group (mart.v_payment_screen_rows): leads to review, not errors.
-- What: the agency, vendor, fiscal year, record dates, number of records and dollars of each group. review_amount is the
-- money a review could recover if the group is confirmed: for a duplicate or repeated line, every copy after the first
-- (amount x (n - 1)); a split purchase recovers nothing by itself (0; it is a procurement-compliance lead). A payee whose
-- type is "Business or other" and none of whose payee names (as paid) looks like an organization (payment_screen.org_name_pattern) may be
-- an individual and is never shown by name. also_flagged_under names any other rule that flags the same agency, vendor and
-- year (a record is never in two groups, so dollars are not double-counted; the label shows the overlap).
CREATE OR REPLACE TABLE mart.d_payment_screen AS
WITH g AS (
  SELECT group_id, rule, any_value(date_grain) AS date_grain, min(fiscal_year) AS fiscal_year, any_value(agency_key) AS agency_key,
         any_value(agency_code) AS agency_code, mode(agency_name_as_paid) AS agency, any_value(vendor) AS vendor_full,
         bool_or(regexp_matches(upper(vendor_name_as_paid), {{payment_screen.org_name_pattern}})) AS org_name, any_value(payee_type) AS payee_type,
         min(record_date) AS first_date, max(record_date) AS last_date, count(*) AS n,
         CASE WHEN rule = 'Possible split purchase' THEN NULL ELSE max(amount) END AS amount,
         sum(amount) AS total_amount,
         CASE WHEN rule = 'Possible split purchase' THEN 0 ELSE sum(amount) - max(amount) END AS review_amount,
         count(DISTINCT vendor_name_as_paid) AS payee_names, count(DISTINCT vendor_zip) AS zips
  FROM mart.v_payment_screen_rows GROUP BY group_id, rule
), o AS (
  SELECT a.group_id, string_agg(DISTINCT b.rule, '; ' ORDER BY b.rule) AS also_flagged_under
  FROM g a JOIN g b ON a.agency_key = b.agency_key AND a.vendor_full = b.vendor_full AND a.fiscal_year = b.fiscal_year AND a.rule <> b.rule
  GROUP BY 1
)
SELECT g.group_id, g.rule, g.fiscal_year, g.agency_code, g.agency,
       CASE WHEN g.payee_type <> 'Business or other' OR g.org_name THEN g.vendor_full
            ELSE 'Payee not named (may be an individual)' END AS vendor,
       g.payee_type, g.first_date, g.last_date, g.n, g.amount, g.total_amount, g.review_amount, g.payee_names, g.zips,
       o.also_flagged_under, g.date_grain
FROM g LEFT JOIN o USING (group_id)
ORDER BY g.review_amount DESC, g.total_amount DESC, g.group_id;
