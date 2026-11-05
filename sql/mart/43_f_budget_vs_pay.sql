-- mart.f_budget_vs_pay: operating budget (latest stage) next to payments, by agency
-- Grain: one row per fiscal year x budget agency code (agency_code NULL = payments whose account is not in the budget data).
-- What: budget at its latest stage (actual FY2017-FY2025, working FY2026, appropriation FY2027) split by fund type, and
-- payments split by payee (government bodies vs everyone else). Budget and payments measure different things (payments
-- leave out payroll and include capital and pass-through money), so they sit side by side and are never added.
CREATE OR REPLACE TABLE mart.f_budget_vs_pay AS
WITH b AS (SELECT fiscal_year, agency_code, sum(budget) AS budget,
                  sum(budget) FILTER (WHERE fund_type = 'General Funds') AS general_funds,
                  sum(budget) FILTER (WHERE fund_type = 'Special Funds') AS special_funds,
                  sum(budget) FILTER (WHERE fund_type NOT IN ('General Funds', 'Special Funds')) AS federal_funds
           FROM core.fact_budget GROUP BY ALL),
p AS (SELECT p.fiscal_year, p.agency_code, sum(p.amount) AS payments,
             sum(p.amount) FILTER (WHERE m.is_government) AS paid_to_government,
             sum(p.amount) FILTER (WHERE NOT coalesce(m.is_government, false)) AS paid_to_others,
             bool_or(p.partial_year) AS partial_year
      FROM core.fact_payment_mapped p LEFT JOIN ref.map_payee_vendor m ON m.payee = p.vendor_name_as_paid
      WHERE p.fiscal_year >= 2017 GROUP BY ALL)
SELECT coalesce(b.fiscal_year, p.fiscal_year) AS fiscal_year, s.stage, coalesce(b.agency_code, p.agency_code) AS agency_code,
       b.budget, b.general_funds, b.special_funds, b.federal_funds, p.payments, p.paid_to_government, p.paid_to_others,
       coalesce(p.partial_year, false) AS partial_year
FROM b FULL JOIN p ON p.fiscal_year = b.fiscal_year AND p.agency_code IS NOT DISTINCT FROM b.agency_code
JOIN ref.dim_stage s ON s.fiscal_year = coalesce(b.fiscal_year, p.fiscal_year);
