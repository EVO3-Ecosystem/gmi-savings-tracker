-- mart.payment_area
-- Grain: one row per payment.
-- What: every payment with its vendor (company), the exclusion flag and the payee-name focus area (legacy pm: family,
-- is_government, lens), with the pass-through exclusions in reference/payee_area_exclusions.csv applied per payment:
-- a payment that matches an exclusion (its paying agency and/or payee) loses its focus area and is flagged passthrough.
CREATE OR REPLACE TABLE mart.payment_area AS
WITH p AS (
  SELECT p.fiscal_year, p.agency_code, p.agency_name_as_paid, p.vendor_name_as_paid AS vendor_name, p.amount,
         m.vendor, m.vendor_key, m.is_government, m.payee_area
  FROM core.fact_payment_mapped p JOIN ref.map_payee_vendor m ON m.payee = p.vendor_name_as_paid
)
SELECT p.fiscal_year, p.agency_code, p.agency_name_as_paid, p.vendor_name, p.amount, p.vendor, p.is_government,
       CASE WHEN x.hit THEN NULL ELSE p.payee_area END AS area, coalesce(x.hit, false) AS passthrough
FROM p LEFT JOIN LATERAL (
  SELECT true AS hit FROM ref.payee_area_exclusions e
  WHERE (e.area = '*' OR e.area = p.payee_area)
    AND (coalesce(e.agency_name_pattern, '') = '' OR regexp_matches(upper(p.agency_name_as_paid), e.agency_name_pattern))
    AND (coalesce(e.payee_pattern, '') = '' OR regexp_matches(p.vendor_key, e.payee_pattern))
  LIMIT 1) x ON true;
