-- mart.v_payee_class_input (input to src/models/payee_classifier.py; not published)
-- Grain: one row per payee name as paid (ref.map_payee_vendor), about 61,800 names.
-- What: the payee's current rule label (mart.vendor_type, from reference/payee_type_rules.csv, as the dashboard uses it),
-- how that label was reached (type_basis: name rule, grants data, or the "Business or other" default), and the payee's
-- payments over all years and in FY2025, which set the evaluation sample's spend strata and the "share of dollars
-- classified". payee_key = md5 of the payee name, so a name can be looked up without being published.
CREATE OR REPLACE TABLE mart.v_payee_class_input AS
WITH p AS (SELECT vendor_name_as_paid AS payee, sum(amount) AS paid_all_years, sum(amount) FILTER (WHERE fiscal_year = 2025) AS paid_fy2025
           FROM core.fact_payment GROUP BY 1)
SELECT md5(m.payee) AS payee_key, m.payee, m.vendor_key, m.vendor, t.payee_type AS rule_type, t.type_basis,
       coalesce(p.paid_all_years, 0) AS paid_all_years, coalesce(p.paid_fy2025, 0) AS paid_fy2025
FROM ref.map_payee_vendor m JOIN mart.vendor_type t USING (vendor) LEFT JOIN p USING (payee);
