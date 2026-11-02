-- mart.vendor_agency_year
-- Grain: one row per vendor x paying agency x fiscal year.
-- What: every payment dollar, with the vendor, its payee type, and the paying agency's budget function.
-- Agencies are mapped to the function of the same fiscal year; payment years before FY2017 (no budget data) use the
-- agency's earliest budget year. Payments from accounts the operating budget dataset doesn't carry (capital accounts,
-- independent authorities) take the group named in reference/function_exceptions.csv. Unmapped agencies keep agency_code NULL.
-- Check: yearly total = core.fact_payment yearly total (to the dollar).
CREATE OR REPLACE TABLE mart.vendor_agency_year AS
WITH p AS (
  SELECT m.vendor, p.agency_code, p.fiscal_year, any_value(p.partial_year) AS partial_year,
         sum(p.amount) AS paid, count(*) AS payments, count(DISTINCT p.vendor_name_as_paid) AS payee_names
  FROM core.fact_payment_mapped p JOIN ref.map_payee_vendor m ON m.payee = p.vendor_name_as_paid
  GROUP BY ALL
), first_fn AS (
  SELECT agency_code, arg_min(function_name, fiscal_year) AS function_name FROM mart.agency_function GROUP BY 1
)
SELECT p.vendor, t.payee_type, p.agency_code, p.fiscal_year, p.partial_year,
       coalesce(f.function_name, ff.function_name, x.function_name) AS function_name, p.paid, p.payments, p.payee_names
FROM p
JOIN mart.vendor_type t USING (vendor)
LEFT JOIN mart.agency_function f ON f.agency_code = p.agency_code AND f.fiscal_year = p.fiscal_year
LEFT JOIN first_fn ff ON ff.agency_code = p.agency_code
LEFT JOIN ref.function_exceptions x ON x.agency_code = p.agency_code;
