-- mart.d_multi_basis: the 15+ agency count on both counting bases
-- Grain: one row per fiscal year (FY2022-FY2026) x counting basis.
-- What: "company and budget agency" (payee names grouped into companies, payment accounts mapped to budget agencies;
-- the basis of mart.d_multi) and "payee name and payment account" (the Maryland Spend Lens basis: normalized payee name,
-- payment agency name as published). Same payments, same exclusions.
CREATE OR REPLACE TABLE mart.d_multi_basis AS
WITH a AS (SELECT fiscal_year, vendor, count(DISTINCT coalesce(agency_code, '?')) n, sum(amount) s FROM mart.v_purchase GROUP BY ALL),
b AS (SELECT p.fiscal_year, m.vendor_key, count(DISTINCT p.agency_name_as_paid) n, sum(p.amount) s
      FROM mart.payment_area p JOIN ref.map_payee_vendor m ON m.payee = p.vendor_name
      WHERE NOT p.is_government AND NOT p.passthrough GROUP BY ALL)
SELECT fiscal_year, 'company and budget agency' AS basis, count(*) AS vendors, sum(s) AS spend FROM a WHERE n >= 15 AND fiscal_year BETWEEN 2022 AND 2026 GROUP BY 1
UNION ALL
SELECT fiscal_year, 'payee name and payment account', count(*), sum(s) FROM b WHERE n >= 15 AND fiscal_year BETWEEN 2022 AND 2026 GROUP BY 1;
