-- mart.vendor_master
-- Grain: one row per vendor (company).
-- What: payee type, how many names and agencies, the functions it is paid from, its main function by dollars,
-- focus area (rule-based, where a payee pattern assigns one), and payments in the latest full year and the year before.
-- Check: one row per vendor in mart.vendor_agency_year.
CREATE OR REPLACE TABLE mart.vendor_master AS
WITH y AS (SELECT max(fiscal_year) AS fy FROM core.fact_payment WHERE NOT partial_year),
fn AS (
  SELECT vendor, function_name, sum(paid) AS paid FROM mart.vendor_agency_year GROUP BY ALL
)
SELECT v.vendor, t.payee_type, t.type_basis, t.payee_names, t.focus_area,
       min(v.fiscal_year) AS first_fy, max(v.fiscal_year) AS last_fy,
       count(DISTINCT v.agency_code) AS agencies_all_years,
       count(DISTINCT v.agency_code) FILTER (WHERE v.fiscal_year = (SELECT fy FROM y)) AS agencies_last_full_year,
       count(DISTINCT v.function_name) AS functions,
       (SELECT arg_max(function_name, paid) FROM fn WHERE fn.vendor = v.vendor) AS main_function,
       (SELECT fy FROM y) AS last_full_year,
       coalesce(sum(v.paid) FILTER (WHERE v.fiscal_year = (SELECT fy FROM y)), 0) AS paid_last_full_year,
       coalesce(sum(v.paid) FILTER (WHERE v.fiscal_year = (SELECT fy FROM y) - 1), 0) AS paid_prior_year,
       sum(v.paid) AS paid_all_years
FROM mart.vendor_agency_year v JOIN mart.vendor_type t USING (vendor)
GROUP BY v.vendor, t.payee_type, t.type_basis, t.payee_names, t.focus_area;
