-- Dashboard file f_code: focus-area spending by fiscal year, agency and spending code.
CREATE OR REPLACE TABLE mart.f_code AS
SELECT b.fiscal_year, s.stage, b.agency_code, b.focus_area AS area, b.subobject_code AS code, b.subobject_name AS spending_code, sum(b.budget) AS spend
FROM core.fact_budget_scope b JOIN ref.dim_stage s USING (fiscal_year) WHERE b.focus_area IS NOT NULL GROUP BY ALL;
