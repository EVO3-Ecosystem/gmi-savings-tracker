-- mart.f_payee_type (dashboard Vendors tab)
-- Grain: one row per payee type x budget function (of the paying agency) x paying agency x fiscal year.
-- What: all payments, by who received them. Check: yearly total = core payments.
CREATE OR REPLACE TABLE mart.f_payee_type AS
SELECT fiscal_year, agency_code, payee_type, coalesce(function_name, 'No agency') AS function_name, sum(paid) AS paid, count(DISTINCT vendor) AS vendors
FROM mart.vendor_agency_year GROUP BY ALL;
