-- mart.f_grants: the state's grants and loans as the portal lists them (absk-avps), with a payments cross-reference
-- Grain: one row per grants dataset row (fiscal year x grantor x grantee x description x amount), as delivered.
-- What: grantor, grantee, description, category, non-profit flag and ZIP exactly as published (trimmed, no grouping;
-- groupings are a next-phase suggestion). in_payments / paid_same_fy flag whether the grantee also appears as a payee
-- in the payments data that fiscal year (names compared after removing case, spaces and punctuation), the evidence for
-- whether grants are paid out through the payments data and so must not be added to payments.
CREATE OR REPLACE TABLE mart.f_grants AS
WITH pay AS (SELECT fiscal_year, regexp_replace(upper(vendor_name_as_paid), '[^A-Z0-9]', '', 'g') AS k, sum(amount) AS paid
             FROM core.fact_payment GROUP BY ALL)
SELECT g.fiscal_year, g.grantor, g.grantee, g.description, g.category, g.nonprofit, g.zipcode, g.amount,
       p.paid IS NOT NULL AS in_payments, p.paid AS paid_same_fy
FROM core.fact_grant g
LEFT JOIN pay p ON p.fiscal_year = g.fiscal_year AND p.k = regexp_replace(upper(g.grantee), '[^A-Z0-9]', '', 'g');
