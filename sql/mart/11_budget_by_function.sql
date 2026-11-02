-- yoy: keys=category_title values=budget stage
-- Dashboard file budget_by_function: operating budget by fiscal year and function.
SELECT b.fiscal_year, s.stage, b.function_name AS category_title, sum(b.budget) AS budget
FROM core.fact_budget_scope b JOIN ref.dim_stage s USING (fiscal_year) GROUP BY ALL
