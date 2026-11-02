-- Dashboard file f_area: focus-area spending by fiscal year and agency, by spending code and by payee name.
CREATE OR REPLACE TABLE mart.f_area AS
WITH b AS (SELECT fiscal_year, agency_code, focus_area AS area, sum(budget) AS spend FROM core.fact_budget_scope WHERE focus_area IS NOT NULL GROUP BY ALL),
p AS (SELECT fiscal_year, agency_code, area, sum(amount) AS payee_spend FROM mart.payment_area WHERE area IS NOT NULL GROUP BY ALL)
SELECT coalesce(b.fiscal_year, p.fiscal_year) AS fiscal_year, coalesce(s.stage, 'Payments only') AS stage, coalesce(b.agency_code, p.agency_code) AS agency_code,
       coalesce(b.area, p.area) AS area, b.spend, p.payee_spend
FROM b FULL JOIN p ON b.fiscal_year = p.fiscal_year AND b.agency_code IS NOT DISTINCT FROM p.agency_code AND b.area = p.area
LEFT JOIN ref.dim_stage s ON s.fiscal_year = coalesce(b.fiscal_year, p.fiscal_year);
