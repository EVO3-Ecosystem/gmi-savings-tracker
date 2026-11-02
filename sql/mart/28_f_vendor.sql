-- Dashboard file f_vendor: payee-name focus-area payments by fiscal year, agency and vendor, FY2022 on.
CREATE OR REPLACE TABLE mart.f_vendor AS
SELECT fiscal_year, agency_code, area, vendor, sum(amount) AS spend FROM mart.payment_area
WHERE area IS NOT NULL AND fiscal_year >= 2022 AND agency_code IS NOT NULL GROUP BY ALL;
