-- yoy: keys=area,agency_code values=spend stage good=lower
-- Dashboard file area_agency_year: focus-area spending by agency.
SELECT b.fiscal_year, s.stage, b.focus_area AS area, b.agency_code, sum(b.budget) AS spend, any_value(n.agency) AS agency
FROM core.fact_budget_scope b JOIN ref.dim_stage s USING (fiscal_year) LEFT JOIN mart.agency_name n USING (agency_code)
WHERE b.focus_area IS NOT NULL GROUP BY b.fiscal_year, s.stage, b.focus_area, b.agency_code
