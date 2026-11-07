-- yoy: keys=object_name values=budget,controllable stage good=lower
-- Dashboard file budget_by_object: budget and controllable purchases by Comptroller object.
SELECT b.fiscal_year, s.stage, b.object_name, sum(b.budget) AS budget, coalesce(sum(b.budget) FILTER (WHERE b.controllable), 0) AS controllable
FROM core.fact_budget_scope b JOIN ref.dim_stage s USING (fiscal_year) GROUP BY ALL
