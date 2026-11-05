-- mart.f_program: where it's going (the portal's spending view of the operating budget, yu65-jmmv)
-- Grain: one row per fiscal year x budget agency x unit x program x fund type.
-- What: operating budget (all funds) by agency, unit and program, with the budget stage.
CREATE OR REPLACE TABLE mart.f_program AS
SELECT b.fiscal_year, s.stage, b.agency_code, b.unit_name, b.program_code, b.program_name, b.fund_type, sum(b.budget) AS budget
FROM core.fact_budget b JOIN ref.dim_stage s USING (fiscal_year)
GROUP BY ALL;
