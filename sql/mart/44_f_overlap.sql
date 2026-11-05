-- mart.f_overlap: statewide evidence for where the budget, payments and grants overlap
-- Grain: one row per fiscal year (FY2017 onward).
-- What: budget by fund type (how it's funded), payments by payee (where it's going), and grants with the share whose
-- grantee is also paid in the payments data that year. A high grants_in_payments_share means grants are largely paid
-- out through the payments data: show grants as part of payments, never on top of them.
CREATE OR REPLACE TABLE mart.f_overlap AS
WITH v AS (SELECT fiscal_year, any_value(stage) AS stage, sum(budget) AS budget, sum(general_funds) AS general_funds,
                  sum(special_funds) AS special_funds, sum(federal_funds) AS federal_funds, sum(payments) AS payments,
                  sum(paid_to_government) AS paid_to_government, sum(paid_to_others) AS paid_to_others,
                  bool_or(partial_year) AS partial_year
           FROM mart.f_budget_vs_pay GROUP BY 1),
g AS (SELECT fiscal_year, sum(amount) FILTER (WHERE category = 'Grant') AS grants, sum(amount) FILTER (WHERE category = 'Loan') AS loans,
             sum(amount) AS grants_and_loans, sum(amount) FILTER (WHERE in_payments) AS grants_in_payments,
             count(*) AS grant_rows, count(*) FILTER (WHERE in_payments) AS grant_rows_in_payments
      FROM mart.f_grants GROUP BY 1)
SELECT v.*, g.grants, g.loans, g.grants_and_loans, g.grants_in_payments, g.grants_in_payments / nullif(g.grants_and_loans, 0) AS grants_in_payments_share,
       g.grant_rows, g.grant_rows_in_payments, v.payments / nullif(v.budget, 0) AS payments_to_budget_share
FROM v LEFT JOIN g USING (fiscal_year) ORDER BY 1;
