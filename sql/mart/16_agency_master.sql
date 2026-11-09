-- Dashboard file agency_master: each agency code with the payment agency names mapped to it.
-- Budget agencies take the budget's name; payment-only codes (e.g. D30, R95, U10) take the payment data's own name;
-- CAPITAL gets a label. The unmapped row (no agency code) stays unnamed.
CREATE OR REPLACE TABLE mart.agency_master AS
SELECT m.agency_code,
       coalesce(n.agency,
                CASE WHEN m.agency_code = 'CAPITAL' THEN 'Capital projects (capital budget, not in the operating budget)' END,
                CASE WHEN m.agency_code IS NOT NULL THEN min(m.payment_agency_name) END) AS agency,
       m.in_budget, count(DISTINCT m.payment_agency_name) AS payment_names,
       array_to_string(list_slice(list_sort(list_distinct(list(m.matched_by))), 1, 3), '; ') AS how_matched
FROM ref.map_payment_agency m LEFT JOIN mart.agency_name n USING (agency_code) GROUP BY m.agency_code, n.agency, m.in_budget;
