-- mart.agency_function
-- Grain: one row per agency_code x fiscal_year (budget years).
-- What: the budget function each agency belongs to (the state's category_title), and the share of the agency's budget in it.
-- Source: core.fact_budget. Check: every agency-year has a function; share is 100% for every agency in the current data.
CREATE OR REPLACE TABLE mart.agency_function AS
WITH f AS (
  SELECT agency_code, fiscal_year, function_name, sum(budget) AS budget
  FROM core.fact_budget GROUP BY ALL
), r AS (
  SELECT *, budget / nullif(sum(budget) OVER (PARTITION BY agency_code, fiscal_year), 0) AS share,
         row_number() OVER (PARTITION BY agency_code, fiscal_year ORDER BY budget DESC) AS rn
  FROM f
)
SELECT agency_code, fiscal_year, function_name, share AS function_share
FROM r WHERE rn = 1;
