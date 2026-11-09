-- mart.d_all_funds: the all-funds operating budget including public higher education (a separate, labeled figure)
-- Grain: one row per fiscal year.
-- What: the operating budget dataset (yu65-jmmv), the public higher education dataset (4mca-332u: R13 Morgan State, R14 St. Mary's
-- College, R30 University System of Maryland, R95 Baltimore City Community College, which yu65-jmmv leaves out) and their sum.
-- Every other budget figure and every GMI savings baseline uses yu65-jmmv only; only this table adds higher education in.
-- Checks: operating_budget = core.fact_budget and public_higher_education = core.fact_budget_highered, every year, to the dollar.
CREATE OR REPLACE TABLE mart.d_all_funds AS
WITH t AS (
  SELECT fiscal_year, sum(budget) FILTER (WHERE source_dataset = 'yu65-jmmv') AS operating_budget,
         sum(budget) FILTER (WHERE source_dataset = '4mca-332u') AS public_higher_education
  FROM core.fact_budget_all_funds GROUP BY fiscal_year
)
SELECT t.fiscal_year, s.stage, t.operating_budget, t.public_higher_education,
       t.operating_budget + coalesce(t.public_higher_education, 0) AS all_funds_including_higher_education,
       'Operating budget, all funds, including public higher education' AS label,
       CASE WHEN t.public_higher_education IS NULL THEN 'yu65-jmmv (no higher education rows this year)' ELSE 'yu65-jmmv + 4mca-332u' END AS source_datasets
FROM t LEFT JOIN ref.dim_stage s USING (fiscal_year)
ORDER BY t.fiscal_year;
