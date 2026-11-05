-- mart.f_fund_source: how it's funded (the portal's funding-source view, gy87-e27x)
-- Grain: one row per fiscal year x budget agency x fund type x fund source.
-- What: budget by named fund source (general fund, each special fund, each federal program with its Assistance Listing
-- code), with the budget stage. Federal fund sources show which spending is federal money passed through State agencies.
CREATE OR REPLACE TABLE mart.f_fund_source AS
SELECT f.fiscal_year, s.stage, f.agency_code, f.fund_type, f.fund_source_code, f.fund_source_name, sum(f.budget) AS budget
FROM core.fact_fund f JOIN ref.dim_stage s USING (fiscal_year)
GROUP BY ALL;
