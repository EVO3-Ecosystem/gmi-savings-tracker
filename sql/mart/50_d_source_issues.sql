-- mart.d_source_issues (dashboard Opportunities tab: data-publication issues found by the payment screen)
-- Grain: one row per screened fiscal year and agency whose payment records carry more than one record date: a second block
-- of the year's annual records published with another date (FY2022 MDTA and MES: rows dated Jan 1, 2023 under FY2022).
-- What: the second (off-year) block's records and dollars, how many of its records equal a first-block record in payee
-- name, ZIP and amount, and the payment-screen groups moved here from mart.d_payment_screen (source_issue_id in
-- mart.v_payment_screen_rows). Not money owed and not a payment lead: a question for the publisher (the Comptroller).
-- verified_against / verified_on / status: from config source_issues; an issue not listed in verified_ids says it is not yet
-- checked at the source. Agency = the pipeline's cleaned name (mart.agency_master); agency_raw = the name as paid.
CREATE OR REPLACE TABLE mart.d_source_issues AS
WITH p AS (
  SELECT fiscal_year, coalesce(agency_code, agency_name_as_paid) AS agency_key, agency_code, agency_name_as_paid, vendor_name_as_paid,
         vendor_zip, round(amount * 100) AS cents, amount, record_date
  FROM core.fact_payment_mapped
  WHERE fiscal_year BETWEEN {{payment_screen.first_fy}} AND {{payment_screen.last_fy}} AND NOT partial_year
), multi AS (
  SELECT fiscal_year, agency_key FROM p GROUP BY ALL HAVING count(DISTINCT record_date) > 1
), b AS (  -- off-year block (record date in another calendar year than the fiscal year's) vs the on-year block
  SELECT p.*, year(record_date) <> fiscal_year AS off_year FROM p JOIN multi USING (fiscal_year, agency_key)
), off AS (
  SELECT fiscal_year, agency_key, any_value(agency_code) AS agency_code, mode(agency_name_as_paid) AS agency_raw,
         min(record_date) AS off_date, count(*) AS records, sum(amount) AS amount
  FROM b WHERE off_year GROUP BY ALL
), onb AS (
  SELECT fiscal_year, agency_key, min(record_date) AS on_date, count(*) AS on_records, sum(amount) AS on_amount FROM b WHERE NOT off_year GROUP BY ALL
), same AS (  -- off-block records equal to an on-block record (payee name, ZIP, cents), matched one to one
  SELECT fiscal_year, agency_key, sum(least(n_off, n_on)) AS identical_records, sum(least(n_off, n_on) * cents / 100.0) AS identical_amount
  FROM (SELECT fiscal_year, agency_key, vendor_name_as_paid, vendor_zip, cents,
               count(*) FILTER (WHERE off_year) AS n_off, count(*) FILTER (WHERE NOT off_year) AS n_on
        FROM b GROUP BY ALL) GROUP BY ALL
), scr AS (
  SELECT issue_id, count(*) AS screen_groups, sum(n) AS screen_records, sum(rv) AS screen_review_amount
  FROM (SELECT source_issue_id AS issue_id, group_id, count(*) AS n, sum(amount) - max(amount) AS rv
        FROM mart.v_payment_screen_rows WHERE source_issue_id IS NOT NULL GROUP BY 1, 2) GROUP BY 1
), i AS (
  SELECT 'SRC-' || off.fiscal_year || '-' || off.agency_key AS issue_id, off.*, onb.on_date, onb.on_records, onb.on_amount,
         coalesce(same.identical_records, 0) AS identical_records, coalesce(same.identical_amount, 0) AS identical_amount
  FROM off LEFT JOIN onb USING (fiscal_year, agency_key) LEFT JOIN same USING (fiscal_year, agency_key)
)
SELECT i.issue_id,
       format('FY{} payments published twice: a second block dated {}', i.fiscal_year, strftime(i.off_date, '%b %-d, %Y')) AS issue,
       i.fiscal_year, i.agency_code, coalesce(am.agency, i.agency_raw) AS agency, i.agency_raw,
       i.records, i.amount, i.identical_records, i.identical_amount,
       coalesce(scr.screen_groups, 0) AS screen_groups, coalesce(scr.screen_records, 0) AS screen_records,
       coalesce(scr.screen_review_amount, 0) AS screen_review_amount,
       format('{:,d} records dated {} (${:,.2f}) plus {:,d} dated {} (${:,.2f}) under FY{}; {:,d} of the second block equal a first-block record in payee, ZIP and amount (${:,.2f}); the payment screen paired {:,d} of them in {:,d} groups (moved out of the leads)',
              i.on_records, strftime(i.on_date, '%Y-%m-%d'), i.on_amount, i.records, strftime(i.off_date, '%Y-%m-%d'), i.amount, i.fiscal_year,
              i.identical_records, i.identical_amount, coalesce(scr.screen_records, 0) - coalesce(scr.screen_groups, 0), coalesce(scr.screen_groups, 0)) AS evidence,
       CASE WHEN list_contains([{{source_issues.verified_ids}}], i.issue_id) THEN {{source_issues.verified_against}} END AS verified_against,
       CASE WHEN list_contains([{{source_issues.verified_ids}}], i.issue_id) THEN CAST({{source_issues.verified_on}} AS DATE) END AS verified_on,
       CASE WHEN list_contains([{{source_issues.verified_ids}}], i.issue_id) THEN {{source_issues.status_verified}} ELSE {{source_issues.status_unverified}} END AS status
FROM i LEFT JOIN scr USING (issue_id)
LEFT JOIN (SELECT agency_code, any_value(agency) AS agency FROM mart.agency_master WHERE agency_code IS NOT NULL GROUP BY 1) am ON am.agency_code = i.agency_code
ORDER BY i.amount DESC, i.issue_id;
