-- yoy: keys=area,vendor values=spend
-- Dashboard file area_vendor_year: the 15 largest vendors per focus area and year, by payee name, FY2022 on.
SELECT fiscal_year, area, vendor, spend, agencies FROM (
  SELECT fiscal_year, area, vendor, sum(amount) AS spend, count(DISTINCT agency_code) AS agencies FROM mart.payment_area
  WHERE area IS NOT NULL AND fiscal_year >= 2022 GROUP BY ALL)
QUALIFY row_number() OVER (PARTITION BY fiscal_year, area ORDER BY spend DESC) <= 15
