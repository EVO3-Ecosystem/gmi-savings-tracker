-- yoy: keys=fund_type_name values=budget stage
-- Dashboard file budget_by_fund: funding-source budget by fiscal year and fund type.
SELECT f.fiscal_year, f.fund_type AS fund_type_name, sum(f.budget) AS budget, s.stage
FROM core.fact_fund f LEFT JOIN ref.dim_stage s USING (fiscal_year) GROUP BY f.fiscal_year, f.fund_type, s.stage
