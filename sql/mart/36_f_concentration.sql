-- mart.f_concentration: how concentrated each focus area's buying is
-- Grain: one row per fiscal year (FY2008-FY2026) x focus area.
-- What: vendors, spend, share held by the five largest vendors, and the Herfindahl-Hirschman Index
-- (HHI = sum of squared percentage shares, 0-10,000; above 1,800 is "highly concentrated" under the
-- 2023 U.S. DOJ/FTC Merger Guidelines).
CREATE OR REPLACE TABLE mart.f_concentration AS
WITH v AS (SELECT fiscal_year, area, vendor, sum(amount) AS spend FROM mart.v_purchase WHERE area <> 'Other goods & services' GROUP BY ALL HAVING sum(amount) > 0),
s AS (SELECT *, spend / sum(spend) OVER (PARTITION BY fiscal_year, area) AS share,
             row_number() OVER (PARTITION BY fiscal_year, area ORDER BY spend DESC) AS rk FROM v)
SELECT fiscal_year, area, count(*) AS vendors, sum(spend) AS spend, sum(share) FILTER (WHERE rk <= 5) AS top5_share,
       round(sum(power(share * 100, 2))) AS hhi
FROM s GROUP BY ALL;
