-- yoy: keys=area values=spend,payee_spend stage good=lower
-- Dashboard file area_year: each focus area by spending code (budget) and by payee name (payments).
WITH b AS (SELECT b.fiscal_year, s.stage, b.focus_area AS area, sum(b.budget) AS spend, count(DISTINCT b.agency_code) AS agencies, count(DISTINCT b.subobject_code) AS codes
           FROM core.fact_budget_scope b JOIN ref.dim_stage s USING (fiscal_year) WHERE b.focus_area IS NOT NULL GROUP BY ALL),
p AS (SELECT fiscal_year, area, sum(amount) AS payee_spend, count(DISTINCT vendor) AS vendors FROM mart.payment_area WHERE area IS NOT NULL GROUP BY ALL)
SELECT coalesce(b.fiscal_year, p.fiscal_year) AS fiscal_year, coalesce(b.stage, 'Payments only') AS stage, coalesce(b.area, p.area) AS area,
       b.spend, b.agencies, b.codes, p.payee_spend, p.vendors
FROM b FULL JOIN p ON b.fiscal_year = p.fiscal_year AND b.area = p.area
