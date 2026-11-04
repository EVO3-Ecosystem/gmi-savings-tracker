-- mart.d_area_top: largest vendors in each focus area
-- Grain: one row per fiscal year (FY2022-FY2026) x focus area x vendor, the six largest per area.
CREATE OR REPLACE TABLE mart.d_area_top AS
SELECT fiscal_year, area, vendor, agencies, spend, rk AS rank FROM (
  SELECT fiscal_year, area, vendor, count(DISTINCT coalesce(agency_code, '?')) AS agencies, sum(amount) AS spend,
         row_number() OVER (PARTITION BY fiscal_year, area ORDER BY sum(amount) DESC) AS rk
  FROM mart.v_purchase WHERE area <> 'Other goods & services' AND fiscal_year BETWEEN 2022 AND 2026 GROUP BY fiscal_year, area, vendor)
WHERE rk <= 6;
