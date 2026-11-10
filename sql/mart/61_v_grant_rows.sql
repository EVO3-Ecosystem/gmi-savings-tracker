-- mart.v_grant_rows (input to src/models/grant_groups.py; not published)
-- Grain: one row per grants dataset row (core.fact_grant) with a description.
-- What: the grantor agency (the part of the grantor before the first "/", which the portal joins to a program name; upper
-- case, "&" as AND, punctuation and a leading MARYLAND or STATE removed, so "MARYLAND DEPARTMENT OF LABOR" and "DEPARTMENT
-- OF LABOR" are one agency; renamed agencies, e.g. Health and Mental Hygiene -> Health, stay separate), the grantor program (the rest), the grantee, the description as published and a matching key (lower case, spaces
-- collapsed), so descriptions that differ only in case or spacing are one description for clustering.
CREATE OR REPLACE TABLE mart.v_grant_rows AS
SELECT fiscal_year,
       trim(regexp_replace(regexp_replace(regexp_replace(replace(upper(trim(split_part(grantor, '/', 1))), '&', ' AND '), '[^A-Z0-9 ]', ' ', 'g'),
            '^\s*(MARYLAND|STATE)\s+', ''), '\s+', ' ', 'g')) AS grantor_agency,
       nullif(trim(substr(grantor, length(split_part(grantor, '/', 1)) + 2)), '') AS grantor_program,
       grantee, category, description, lower(regexp_replace(trim(description), '\s+', ' ', 'g')) AS description_key, amount
FROM core.fact_grant WHERE description IS NOT NULL AND trim(description) <> '';
