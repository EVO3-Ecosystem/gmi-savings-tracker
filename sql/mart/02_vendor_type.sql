-- mart.vendor_type
-- Grain: one row per vendor (company after payee names are grouped).
-- What: payee type from reference/payee_type_rules.csv, applied to normalized payee names in priority order (lowest wins
-- across a vendor's names). Non-profit comes from the State's grants data: the grantee is flagged nonprofit = 'Y' on at
-- least half of its grants. Everything else is "Business or other", which includes individuals (never featured by name).
-- Note: ref.map_payee_vendor.is_government is a different, wider exclusion flag kept for parity with the dashboard.
CREATE OR REPLACE TABLE mart.vendor_type AS
WITH rules AS (SELECT CAST(priority AS INTEGER) AS priority, payee_type, pattern FROM ref.payee_type_rule),
hit AS (
  SELECT m.vendor, m.payee, m.payee_area,
         coalesce(
           (SELECT min(r.priority) FROM rules r WHERE r.pattern IS NOT NULL AND r.pattern <> '' AND regexp_matches(m.vendor_key, r.pattern)),
           CASE WHEN n.nonprofit_share >= 0.5 THEN 6 END,
           7) AS priority
  FROM ref.map_payee_vendor m LEFT JOIN ref.map_nonprofit n USING (vendor_key)
), v AS (
  SELECT vendor, min(priority) AS priority, count(DISTINCT payee) AS payee_names, mode(payee_area) AS focus_area FROM hit GROUP BY 1
)
SELECT v.vendor, r.payee_type,
       CASE WHEN v.priority = 6 THEN 'grants data nonprofit = Y' WHEN v.priority = 7 THEN 'default' ELSE 'name rule' END AS type_basis,
       v.payee_names, v.focus_area
FROM v JOIN rules r USING (priority);
