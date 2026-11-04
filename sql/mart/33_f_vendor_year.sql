-- mart.f_vendor_year (dashboard Vendors tab)
-- Grain: one row per fiscal year.
-- What: non-government vendors paid, their payments, and how concentrated they are (share held by the top 10 and top 100).
CREATE OR REPLACE TABLE mart.f_vendor_year AS
WITH v AS (SELECT fiscal_year, vendor, sum(paid) AS paid FROM mart.vendor_agency_year WHERE payee_type <> 'Government' GROUP BY ALL),
r AS (SELECT *, row_number() OVER (PARTITION BY fiscal_year ORDER BY paid DESC) AS rk FROM v)
SELECT fiscal_year, count(*) AS vendors, sum(paid) AS paid_non_government,
       sum(paid) FILTER (WHERE rk <= 10) / sum(paid) AS top10_share,
       sum(paid) FILTER (WHERE rk <= 100) / sum(paid) AS top100_share,
       count(*) FILTER (WHERE paid >= 1e6) AS vendors_1m
FROM r GROUP BY 1;
