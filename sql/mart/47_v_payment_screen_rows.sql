-- mart.v_payment_screen_rows (helper for the payment screen; not published)
-- Grain: one row per payment record that falls in a flagged group; a record is in at most one group (one rule).
-- What: the duplicate and split payment screen, rules defined in docs/models/payment_screen.md and every threshold in
-- config/assumptions.yaml (payment_screen). Screened: full payment years first_fy..last_fy, positive amounts, payees that
-- are not government or institutional (ref.map_payee_vendor is_government), not an excluded payee type (transfers to
-- government, health plans and benefits, debt service), not payroll- or benefit-like by name, and not a pass-through
-- payment (reference/payee_area_exclusions.csv, as mart.payment_area applies it). Agency = budget agency code, else the
-- agency name as paid; vendor = the company after payee names are grouped (ref.map_payee_vendor).
--   Possible duplicate: same agency, vendor and exact amount (>= min_amount), record dates within duplicate_window_days.
--   Repeated annual line: only when the data are annual records (fewer than transaction_grain_min_dates distinct dates in
--     every screened year): the same agency, vendor and exact amount twice or more in one fiscal year with record dates
--     further apart than the duplicate window (a line published twice for the year).
--   Possible split purchase: only at payment-level dates: same agency and vendor, 2+ payments within split_window_days,
--     each under small_procurement_threshold, together above it. At annual grain it is not measurable and flags nothing.
-- Precedence: duplicate, then repeated annual line, then split; a record already flagged is not offered to a later rule.
CREATE OR REPLACE TABLE mart.v_payment_screen_rows AS
WITH grain AS (
  SELECT CASE WHEN max(d) >= {{payment_screen.transaction_grain_min_dates}} THEN 'payment' ELSE 'annual' END AS date_grain
  FROM (SELECT fiscal_year, count(DISTINCT record_date) AS d FROM core.fact_payment
        WHERE fiscal_year BETWEEN {{payment_screen.first_fy}} AND {{payment_screen.last_fy}} AND NOT partial_year GROUP BY 1)
), p AS (
  SELECT p.fiscal_year, p.agency_code, p.agency_name_as_paid, p.agency_code_as_paid, p.vendor_name_as_paid, p.vendor_zip,
         p.amount, p.record_date, m.vendor, m.vendor_key, t.payee_type,
         coalesce(p.agency_code, p.agency_name_as_paid) AS agency_key,
         round(p.amount * 100) AS cents,
         (m.is_government OR t.payee_type IN ({{payment_screen.excluded_payee_types}})
          OR regexp_matches(m.vendor_key, {{payment_screen.exclude_payee_pattern}}) OR coalesce(x.hit, false)) AS excluded
  FROM core.fact_payment_mapped p
  JOIN ref.map_payee_vendor m ON m.payee = p.vendor_name_as_paid
  JOIN mart.vendor_type t USING (vendor)
  LEFT JOIN LATERAL (
    SELECT true AS hit FROM ref.payee_area_exclusions e
    WHERE (e.area = '*' OR e.area = m.payee_area)
      AND (coalesce(e.agency_name_pattern, '') = '' OR regexp_matches(upper(p.agency_name_as_paid), e.agency_name_pattern))
      AND (coalesce(e.payee_pattern, '') = '' OR regexp_matches(m.vendor_key, e.payee_pattern))
    LIMIT 1) x ON true
  WHERE p.fiscal_year BETWEEN {{payment_screen.first_fy}} AND {{payment_screen.last_fy}} AND NOT p.partial_year AND p.amount > 0
), c AS (
  SELECT *, md5(concat_ws('|', fiscal_year, agency_name_as_paid, agency_code_as_paid, vendor_name_as_paid, vendor_zip, cents, record_date))
            || '-' || row_number() OVER (PARTITION BY fiscal_year, agency_name_as_paid, agency_code_as_paid, vendor_name_as_paid, vendor_zip, cents, record_date) AS record_key
  FROM p WHERE NOT excluded
), d0 AS (  -- islands of records with the same agency, vendor and amount, record dates within the duplicate window
  SELECT *, sum(brk) OVER (PARTITION BY fiscal_year, agency_key, vendor, cents ORDER BY record_date, record_key) AS island
  FROM (SELECT *, CASE WHEN date_diff('day', lag(record_date) OVER (PARTITION BY fiscal_year, agency_key, vendor, cents ORDER BY record_date, record_key), record_date)
                            <= {{payment_screen.duplicate_window_days}} THEN 0 ELSE 1 END AS brk
        FROM c WHERE amount >= {{payment_screen.min_amount}})
), dup AS (
  SELECT d0.*, 'Possible duplicate' AS rule, md5(concat_ws('|', 'dup', fiscal_year, agency_key, vendor, cents, island)) AS group_id
  FROM d0 QUALIFY count(*) OVER (PARTITION BY fiscal_year, agency_key, vendor, cents, island) >= 2
), rep AS (
  SELECT d0.*, 'Repeated annual line' AS rule, md5(concat_ws('|', 'rep', fiscal_year, agency_key, vendor, cents)) AS group_id
  FROM d0 WHERE (SELECT date_grain FROM grain) = 'annual' AND record_key NOT IN (SELECT record_key FROM dup)
  QUALIFY count(*) OVER (PARTITION BY fiscal_year, agency_key, vendor, cents) >= 2
), s0 AS (  -- payment-level data only: runs of small payments to one vendor by one agency, gaps within the split window
  SELECT *, sum(brk) OVER (PARTITION BY agency_key, vendor ORDER BY record_date, record_key) AS island
  FROM (SELECT *, CASE WHEN date_diff('day', lag(record_date) OVER (PARTITION BY agency_key, vendor ORDER BY record_date, record_key), record_date)
                            <= {{payment_screen.split_window_days}} THEN 0 ELSE 1 END AS brk
        FROM c WHERE (SELECT date_grain FROM grain) = 'payment' AND amount < {{payment_screen.small_procurement_threshold}}
          AND record_key NOT IN (SELECT record_key FROM dup UNION ALL SELECT record_key FROM rep))
), spl AS (
  SELECT s0.*, 'Possible split purchase' AS rule, md5(concat_ws('|', 'split', agency_key, vendor, island)) AS group_id
  FROM s0 WINDOW w AS (PARTITION BY agency_key, vendor, island)
  QUALIFY count(*) OVER w >= 2 AND sum(amount) OVER w > {{payment_screen.small_procurement_threshold}}
      AND date_diff('day', min(record_date) OVER w, max(record_date) OVER w) <= {{payment_screen.split_window_days}}
)
SELECT group_id, rule, record_key, fiscal_year, agency_key, agency_code, agency_name_as_paid, vendor, vendor_key, payee_type,
       vendor_name_as_paid, vendor_zip, amount, record_date, (SELECT date_grain FROM grain) AS date_grain
FROM (SELECT * EXCLUDE (island, brk) FROM dup UNION ALL BY NAME SELECT * EXCLUDE (island, brk) FROM rep
      UNION ALL BY NAME SELECT * EXCLUDE (island, brk) FROM spl);
