-- mart.agency_rollup
-- Grain: one row per agency x fiscal year (budget years FY2017 on).
-- What: the roll-up spine for the vendor and results views (added Nov 2, 2026). Not a dashboard file: the dashboard's own agency_year file is reproduced separately as mart.agency_year. Function, confirmed stage, operating budget (all funds), controllable purchases, focus-area
-- spending, positions, payments to non-government payees (payee_type other than Government) and to all payees, plus the factors to restate dollars in the
-- latest full year's prices (CPI-U) and per Maryland resident.
-- Check: yearly budget total = core.fact_budget; roll up by function_name for the function view.
CREATE OR REPLACE TABLE mart.agency_rollup AS
WITH b AS (
  SELECT agency_code, fiscal_year, any_value(agency_name) AS agency_name, sum(budget) AS budget,
         sum(budget) FILTER (WHERE controllable) AS controllable,
         sum(budget) FILTER (WHERE focus_area IS NOT NULL) AS focus_area_spend
  FROM core.fact_budget_scope GROUP BY ALL
), f AS (SELECT agency_code, fiscal_year, sum(fte) AS fte FROM core.fact_fte GROUP BY ALL),
p AS (
  SELECT agency_code, fiscal_year, sum(paid) AS payments_all,
         sum(paid) FILTER (WHERE payee_type <> 'Government') AS payments_non_government,
         count(DISTINCT vendor) FILTER (WHERE payee_type <> 'Government') AS vendors
  FROM mart.vendor_agency_year WHERE agency_code IS NOT NULL GROUP BY ALL
)
SELECT b.agency_code, b.agency_name, b.fiscal_year, af.function_name, s.stage,
       b.budget, coalesce(b.controllable, 0) AS controllable, coalesce(b.focus_area_spend, 0) AS focus_area_spend,
       f.fte, p.payments_all, p.payments_non_government, p.vendors,
       c.to_latest_dollars, c.dollars_of_fy, pop.population
FROM b
JOIN mart.agency_function af USING (agency_code, fiscal_year)
JOIN ref.dim_stage s USING (fiscal_year)
LEFT JOIN f USING (agency_code, fiscal_year)
LEFT JOIN p USING (agency_code, fiscal_year)
LEFT JOIN core.cpi_fy c USING (fiscal_year)
LEFT JOIN core.fact_population pop USING (fiscal_year);
