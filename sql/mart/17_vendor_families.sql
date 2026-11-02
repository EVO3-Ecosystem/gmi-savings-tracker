-- Dashboard file vendor_families: FY2026 non-government companies paid under two or more payee names.
CREATE OR REPLACE TABLE mart.vendor_families AS
SELECT vendor AS family, count(DISTINCT vendor_name) AS payee_names, sum(amount) AS spend, count(DISTINCT agency_code) AS agencies
FROM mart.payment_area WHERE fiscal_year = 2026 AND NOT is_government GROUP BY 1 HAVING count(DISTINCT vendor_name) >= 2 ORDER BY spend DESC;
