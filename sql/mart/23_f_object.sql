-- Dashboard file f_object: budget and controllable purchases by fiscal year, agency and object.
CREATE OR REPLACE TABLE mart.f_object AS
SELECT b.fiscal_year, s.stage, b.agency_code, b.object_name, sum(b.budget) AS budget, coalesce(sum(b.budget) FILTER (WHERE b.controllable), 0) AS controllable
FROM core.fact_budget_scope b JOIN ref.dim_stage s USING (fiscal_year) GROUP BY ALL;
