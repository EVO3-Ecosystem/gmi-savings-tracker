-- yoy: keys=area,code values=spend stage
-- Dashboard file area_code_year: focus-area spending by Comptroller sub-object (spending code).
SELECT b.fiscal_year, s.stage, b.focus_area AS area, b.subobject_code AS code, any_value(b.subobject_name) AS spending_code, sum(b.budget) AS spend, count(DISTINCT b.agency_code) AS agencies
FROM core.fact_budget_scope b JOIN ref.dim_stage s USING (fiscal_year) WHERE b.focus_area IS NOT NULL GROUP BY b.fiscal_year, s.stage, b.focus_area, b.subobject_code
