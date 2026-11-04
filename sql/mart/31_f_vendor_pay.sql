-- mart.f_vendor_pay (dashboard Vendors tab and vendor pages)
-- Grain: one row per listed vendor (mart.d_vendors) x paying agency x fiscal year, FY2022-FY2026.
-- Check: totals by vendor and year equal mart.d_vendors' year columns (payments with no agency included as agency NULL).
CREATE OR REPLACE TABLE mart.f_vendor_pay AS
SELECT v.vendor, v.agency_code, v.fiscal_year, sum(v.paid) AS paid
FROM mart.vendor_agency_year v JOIN mart.d_vendors d USING (vendor)
WHERE v.fiscal_year BETWEEN 2022 AND 2026 GROUP BY ALL;
