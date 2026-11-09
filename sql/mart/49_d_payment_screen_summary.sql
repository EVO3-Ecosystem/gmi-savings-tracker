-- mart.d_payment_screen_summary (dashboard Opportunities tab and Calculator lever; the screen's year-by-year backtest)
-- Grain: one row per rule x screened fiscal year (payment_screen.first_fy..last_fy), zeros included.
-- What: flagged groups, records, total and review dollars by rule and year, and whether the rule can be measured at the
-- data's date grain (the split rule needs payment-level dates; the repeated-line rule applies only to annual records).
-- lever_*: the Calculator lever's year and assumed confirmation rates (config payment_screen.lever), carried for the page.
-- Check: groups, records and dollars tie to mart.d_payment_screen; every count is non-negative.
CREATE OR REPLACE TABLE mart.d_payment_screen_summary AS
WITH r AS (SELECT * FROM (VALUES (1, 'Possible duplicate'), (2, 'Repeated annual line'), (3, 'Possible split purchase')) t(rule_order, rule)),
y AS (SELECT CAST(range AS INTEGER) AS fiscal_year FROM range({{payment_screen.first_fy}}, {{payment_screen.last_fy}} + 1)),
grain AS (
  SELECT CASE WHEN max(d) >= {{payment_screen.transaction_grain_min_dates}} THEN 'payment' ELSE 'annual' END AS date_grain
  FROM (SELECT fiscal_year, count(DISTINCT record_date) AS d FROM core.fact_payment
        WHERE fiscal_year BETWEEN {{payment_screen.first_fy}} AND {{payment_screen.last_fy}} AND NOT partial_year GROUP BY 1)
), s AS (
  SELECT rule, fiscal_year, count(*) AS groups, sum(n) AS records, sum(total_amount) AS total_amount, sum(review_amount) AS review_amount
  FROM mart.d_payment_screen GROUP BY ALL
)
SELECT r.rule, r.rule_order, y.fiscal_year, coalesce(s.groups, 0) AS groups, coalesce(s.records, 0) AS records,
       coalesce(s.total_amount, 0) AS total_amount, coalesce(s.review_amount, 0) AS review_amount, g.date_grain,
       CASE WHEN r.rule = 'Possible split purchase' AND g.date_grain = 'annual' THEN 'Not measurable: payments are annual records, not dated payments'
            WHEN r.rule = 'Repeated annual line' AND g.date_grain = 'payment' THEN 'Not applied: payment-level dates'
            ELSE 'Measured' END AS status,
       {{payment_screen.lever.fy}} AS lever_fy, {{payment_screen.lever.rate_low}} AS lever_rate_low,
       {{payment_screen.lever.rate_likely}} AS lever_rate_likely, {{payment_screen.lever.rate_high}} AS lever_rate_high
FROM r CROSS JOIN y CROSS JOIN grain g LEFT JOIN s ON s.rule = r.rule AND s.fiscal_year = y.fiscal_year
ORDER BY y.fiscal_year, r.rule_order;
