-- mart.d_vendors (dashboard Vendors tab)
-- Grain: one row per non-government vendor paid at least $1M in some year FY2022-FY2026.
-- What: payee type, main function, focus area (payee-name rule), payee names, agencies paying (FY2025, FY2026) and
-- payments per year FY2022-FY2026. Government payees (counties, school boards, public funds) are left out: they are
-- transfers, not purchases. Check: every vendor here has rows in mart.f_vendor_pay.
CREATE OR REPLACE TABLE mart.d_vendors AS
WITH y AS (
  SELECT vendor, fiscal_year, sum(paid) AS paid, count(DISTINCT agency_code) AS agencies
  FROM mart.vendor_agency_year WHERE payee_type <> 'Government' AND fiscal_year BETWEEN 2022 AND 2026 GROUP BY ALL
), keep AS (SELECT vendor FROM y GROUP BY 1 HAVING max(paid) >= 1e6)
SELECT m.vendor, m.payee_type, m.main_function, m.focus_area, m.payee_names,
       coalesce(sum(y.paid) FILTER (WHERE y.fiscal_year = 2022), 0) AS fy2022,
       coalesce(sum(y.paid) FILTER (WHERE y.fiscal_year = 2023), 0) AS fy2023,
       coalesce(sum(y.paid) FILTER (WHERE y.fiscal_year = 2024), 0) AS fy2024,
       coalesce(sum(y.paid) FILTER (WHERE y.fiscal_year = 2025), 0) AS fy2025,
       coalesce(sum(y.paid) FILTER (WHERE y.fiscal_year = 2026), 0) AS fy2026,
       coalesce(max(y.agencies) FILTER (WHERE y.fiscal_year = 2025), 0) AS agencies_fy2025,
       coalesce(max(y.agencies) FILTER (WHERE y.fiscal_year = 2026), 0) AS agencies_fy2026
FROM mart.vendor_master m JOIN keep USING (vendor) JOIN y USING (vendor)
GROUP BY m.vendor, m.payee_type, m.main_function, m.focus_area, m.payee_names;
