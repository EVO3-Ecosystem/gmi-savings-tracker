-- mart.v_grant_rows (input to src/models/grant_groups.py; not published)
-- Grain: one row per grants dataset row (core.fact_grant) with a description.
-- What: the grantor as listed (grantor_listed: the part of the grantor before the first "/", which the portal joins to a
-- program name; upper case, "&" as AND, punctuation and a leading MARYLAND or STATE removed), the grantor agency resolved
-- through reference/grantor_agency_aliases.csv (grantor_agency: renamed departments -> the current agency, e.g. Health and
-- Mental Hygiene -> Maryland Department of Health; fund, program or unit names in the grantor field -> the agency that
-- runs them, e.g. MD Stem Cell Research Fund -> Maryland Technology Development Corporation; a grantor missing from the
-- map, or mapped with reason 'unknown', keeps its listed name), why (alias_reason), the grantor program (the rest after
-- "/"), the grantee, the description as published and a matching key (lower case, spaces collapsed), so descriptions that
-- differ only in case or spacing are one description for clustering.
CREATE OR REPLACE TABLE mart.v_grant_rows AS
WITH g AS (
  SELECT fiscal_year, grantor,
         trim(regexp_replace(regexp_replace(regexp_replace(replace(upper(trim(split_part(grantor, '/', 1))), '&', ' AND '), '[^A-Z0-9 ]', ' ', 'g'),
              '^\s*(MARYLAND|STATE)\s+', ''), '\s+', ' ', 'g')) AS grantor_listed,
         nullif(trim(substr(grantor, length(split_part(grantor, '/', 1)) + 2)), '') AS grantor_program,
         grantee, category, description, amount
  FROM core.fact_grant WHERE description IS NOT NULL AND trim(description) <> '')
SELECT g.fiscal_year, g.grantor_listed,
       CASE WHEN a.reason IS NULL OR a.reason = 'unknown' OR coalesce(a.grantor_agency, '') = '' THEN g.grantor_listed ELSE a.grantor_agency END AS grantor_agency,
       coalesce(a.reason, 'not in map') AS alias_reason,
       g.grantor_program, g.grantee, g.category, g.description,
       lower(regexp_replace(trim(g.description), '\s+', ' ', 'g')) AS description_key, g.amount
FROM g LEFT JOIN (SELECT trim(grantor_raw) AS grantor_raw, any_value(grantor_agency) AS grantor_agency, any_value(reason) AS reason
                  FROM ref.grantor_agency_aliases GROUP BY 1) a ON a.grantor_raw = g.grantor;
