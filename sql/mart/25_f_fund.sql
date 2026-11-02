-- Dashboard file f_fund: funding-source budget by fiscal year, agency and fund type.
CREATE OR REPLACE TABLE mart.f_fund AS
SELECT f.fiscal_year, s.stage, f.agency_code, f.fund_type AS fund_type_name, sum(f.budget) AS budget
FROM core.fact_fund f LEFT JOIN ref.dim_stage s USING (fiscal_year) GROUP BY ALL;
