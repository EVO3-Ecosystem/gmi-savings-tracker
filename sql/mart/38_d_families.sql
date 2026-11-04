-- mart.d_families: one company, many payee records
-- Grain: one row per fiscal year (FY2022-FY2026) x company x payee name, for private companies paid under two or more
-- names that year and at least $250,000 in all.
CREATE OR REPLACE TABLE mart.d_families AS
WITH c AS (SELECT fiscal_year, vendor FROM mart.v_purchase WHERE fiscal_year BETWEEN 2022 AND 2026 GROUP BY ALL
           HAVING count(DISTINCT vendor_name) >= 2 AND sum(amount) >= 250000)
SELECT p.fiscal_year, p.vendor AS family, p.vendor_name AS payee_name, count(DISTINCT coalesce(p.agency_code, '?')) AS agencies, sum(p.amount) AS spend
FROM mart.v_purchase p JOIN c USING (fiscal_year, vendor) GROUP BY ALL;
