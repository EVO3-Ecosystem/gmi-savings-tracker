-- mart.agency_results
-- Grain: one row per Managing for Results measure x fiscal year x kind (actual or estimate), for plans matched to an agency.
-- What: each measure next to the agency's spending that year (recommendation 6). Side by side, not cause and effect.
-- Check: rows = core.mfr_measure rows that have an agency_code.
CREATE OR REPLACE TABLE mart.agency_results AS
SELECT m.agency_code, a.agency_name, af.function_name, m.agency_file, m.plan_year, m.goal, m.objective, m.measure,
       m.fiscal_year, m.kind, m.value, m.value_text,
       a.budget, a.controllable, a.fte, a.payments_non_government, a.to_latest_dollars, a.population
FROM core.mfr_measure m
LEFT JOIN mart.agency_rollup a ON a.agency_code = m.agency_code AND a.fiscal_year = m.fiscal_year
LEFT JOIN (SELECT agency_code, arg_max(function_name, fiscal_year) AS function_name FROM mart.agency_function GROUP BY 1) af
  ON af.agency_code = m.agency_code
WHERE m.agency_code IS NOT NULL;
