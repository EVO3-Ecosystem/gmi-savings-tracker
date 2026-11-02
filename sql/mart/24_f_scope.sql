-- Dashboard file f_scope: budget by fiscal year, agency and scope.
CREATE OR REPLACE TABLE mart.f_scope AS
SELECT b.fiscal_year, s.stage, b.agency_code, b.scope, sum(b.budget) AS budget
FROM core.fact_budget_scope b JOIN ref.dim_stage s USING (fiscal_year) GROUP BY ALL;
