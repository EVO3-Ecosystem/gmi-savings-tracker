-- Dashboard file f_function: budget by fiscal year, agency and function.
CREATE OR REPLACE TABLE mart.f_function AS
SELECT b.fiscal_year, s.stage, b.agency_code, b.function_name AS category_title, sum(b.budget) AS budget
FROM core.fact_budget_scope b JOIN ref.dim_stage s USING (fiscal_year) GROUP BY ALL;
