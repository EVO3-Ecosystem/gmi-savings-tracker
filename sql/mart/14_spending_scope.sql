-- yoy: keys=scope values=budget stage
-- Dashboard file spending_scope: budget by what agencies can change.
SELECT b.fiscal_year, s.stage, b.scope, sum(b.budget) AS budget
FROM core.fact_budget_scope b JOIN ref.dim_stage s USING (fiscal_year) GROUP BY ALL
