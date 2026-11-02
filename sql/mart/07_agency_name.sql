-- mart.agency_name: each budget agency code with its latest name (legacy: budget agency_name, last by fiscal year).
CREATE OR REPLACE TABLE mart.agency_name AS
SELECT agency_code, arg_max(agency_name, fiscal_year) AS agency FROM core.fact_budget GROUP BY 1;
