-- mart.d_deflator: real (FY2026) and per-resident dollars (roadmap gap 7); the page's dollars toggle reads it as d_deflator.csv
-- Grain: one row per fiscal year with CPI data (FY2008 on; FY2007 and the current year are partial averages, see cpi_months).
-- What: cpi_index = average of the monthly CPI-U (U.S. city average, all items, not seasonally adjusted, BLS CUUR0000SA0)
-- over the Maryland fiscal year (July-June, core.cpi_fy); factor = FY2026 average / that year's average, so
-- nominal dollars x factor = FY2026 dollars; population = Maryland's July 1 resident estimate at the start of the fiscal year
-- (Census Population Estimates, core.fact_population). Per-resident dollars = dollars / population.
-- Checks: factor is 1 in FY2026; every year with a full CPI year has a factor; population positive where present.
CREATE OR REPLACE TABLE mart.d_deflator AS
WITH base AS (SELECT cpi_avg FROM core.cpi_fy WHERE fiscal_year = 2026 AND months >= 11)  -- FY2026 has 11 months: BLS published no October 2025 CPI (federal shutdown)
SELECT c.fiscal_year, round(c.cpi_avg, 4) AS cpi_index, c.months AS cpi_months,
       -- six decimals as text: export.py rounds float columns to the cent, which would cost up to 0.5% here
       printf('%.6f', (SELECT cpi_avg FROM base) / c.cpi_avg) AS factor, p.population,
       'CPI-U CUUR0000SA0 (BLS; FRED CPIAUCNS as fallback), fiscal-year average of ' || c.months || ' months'
         || CASE WHEN c.months < 11 THEN ' (partial year)' ELSE '' END
         || '; population: ' || CASE WHEN p.population IS NULL THEN 'not yet published' ELSE 'Census Population Estimates, July 1, ' || p.calendar_year || ' (vintage ' || p.vintage || ')' END
         AS source
FROM core.cpi_fy c LEFT JOIN core.fact_population p USING (fiscal_year)
WHERE c.fiscal_year >= 2008
ORDER BY c.fiscal_year;
