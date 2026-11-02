-- Dashboard files f_agency and d_agency: agency_year's spending columns, and the agency list.
CREATE OR REPLACE TABLE mart.f_agency AS
SELECT agency_code, agency, fiscal_year, stage, operating_spending, controllable, fte, payments FROM mart.agency_year;
CREATE OR REPLACE TABLE mart.d_agency AS
SELECT agency_code, arg_max(agency, fiscal_year) AS agency FROM mart.agency_year WHERE agency IS NOT NULL GROUP BY 1;
