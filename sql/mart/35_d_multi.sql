-- mart.d_multi: "One vendor, dozens of buyers"
-- Grain: one row per fiscal year (FY2022-FY2026) x private vendor paid by 15 or more agencies that year.
-- What: agencies paying (count and the list of budget agency codes), spend, payee names, the vendor's focus area, and the same figures for the year before.
-- Agencies are budget agency codes (payment agency names mapped by ref.map_payment_agency); unmapped names count once each.
CREATE OR REPLACE TABLE mart.d_multi AS
WITH y AS (
  SELECT fiscal_year, vendor, count(DISTINCT coalesce(agency_code, '?')) AS agencies, sum(amount) AS spend,
         count(DISTINCT vendor_name) AS payee_names, mode(area) AS area,
         string_agg(DISTINCT agency_code, ',' ORDER BY agency_code) AS agency_codes
  FROM mart.v_purchase GROUP BY ALL
)
SELECT y.fiscal_year, y.vendor, y.area, y.agencies, y.spend, y.payee_names, y.agency_codes, p.agencies AS agencies_prior, p.spend AS spend_prior
FROM y LEFT JOIN y p ON p.vendor = y.vendor AND p.fiscal_year = y.fiscal_year - 1
WHERE y.agencies >= 15 AND y.fiscal_year BETWEEN 2022 AND 2026;
