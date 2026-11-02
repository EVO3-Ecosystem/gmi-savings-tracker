-- Dashboard file agency_master: each budget agency code with the payment agency names mapped to it.
CREATE OR REPLACE TABLE mart.agency_master AS
SELECT m.agency_code, n.agency, m.in_budget, count(DISTINCT m.payment_agency_name) AS payment_names,
       array_to_string(list_slice(list_sort(list_distinct(list(m.matched_by))), 1, 3), '; ') AS how_matched
FROM ref.map_payment_agency m LEFT JOIN mart.agency_name n USING (agency_code) GROUP BY ALL;
