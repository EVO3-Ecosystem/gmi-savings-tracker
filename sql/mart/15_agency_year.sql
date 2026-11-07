-- yoy: keys=agency_code values=controllable,fte,controllable_per_fte stage good=lower
-- Dashboard file agency_year: per agency and budget year: operating spending, controllable purchases, positions,
-- payments (all payees) and controllable purchases per position.
WITH b AS (SELECT agency_code, fiscal_year, sum(budget) AS operating_spending, coalesce(sum(budget) FILTER (WHERE controllable), 0) AS controllable
           FROM core.fact_budget_scope GROUP BY ALL),
f AS (SELECT agency_code, fiscal_year, sum(fte) AS fte FROM core.fact_fte GROUP BY ALL),
p AS (SELECT agency_code, fiscal_year, sum(amount) AS payments FROM mart.payment_area WHERE agency_code IS NOT NULL GROUP BY ALL)
SELECT b.agency_code, n.agency, b.fiscal_year, s.stage, b.operating_spending, b.controllable, f.fte, p.payments,
       CASE WHEN f.fte > 0 THEN b.controllable / f.fte END AS controllable_per_fte
FROM b JOIN ref.dim_stage s USING (fiscal_year) LEFT JOIN mart.agency_name n USING (agency_code)
LEFT JOIN f USING (agency_code, fiscal_year) LEFT JOIN p USING (agency_code, fiscal_year)
