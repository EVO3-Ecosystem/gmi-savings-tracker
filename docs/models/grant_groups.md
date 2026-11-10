# Model card: grant groups and overlap leads

**What it does.** Groups the State's grant descriptions (grants and loans dataset, absk-avps, FY2009-FY2025) by meaning, so grants with the same purpose given by different grantor agencies show up together as possible overlap leads. Code: `src/models/grant_groups.py`. Input: `sql/mart/61_v_grant_rows.sql`, with grantors resolved through `reference/grantor_agency_aliases.csv`. Outputs: `mart.d_grant_groups` (one row per group), `mart.d_grant_group_members` (description -> group), `mart.d_grant_groups_sensitivity` (one row per threshold). Settings: `config/assumptions.yaml` (`grant_groups`). Checks: `src/pipeline/checks_ml.py`; tests: `tests/test_grant_groups.py`.

**A lead is a question, not a finding.** It says only that two or more agencies fund grants described alike. It is not a duplicate, not waste and **not a saving**. Grant dollars in a group are what was granted; they are not additive with payments (grants are largely paid out through the payments data, `mart.f_overlap`), not additive across groups and not additive across thresholds.

## Method

1. **Descriptions.** 23,084 grant rows with a description; matched after lower case and collapsed spaces: **5,008 distinct descriptions**.
2. **Grantor agency.** The grantor as listed (`grantor_listed`) is the part before the first "/" (the portal joins agency and program), upper case, "&" as AND, punctuation and a leading MARYLAND or STATE removed: 363 listed names. Each published grantor string is then looked up in the alias map (below) to give the resolved agency (`grantor_agency`): **43 agencies**. A grantor missing from the map, or mapped as unknown, keeps its listed name (`alias_reason` says which).
3. **Embeddings.** sentence-transformers `all-MiniLM-L6-v2` on CPU, normalized (cached in `data/ml_cache/`). **Backend used for the results below: all-MiniLM-L6-v2.** If the package or model cannot load, TF-IDF word unigrams + bigrams are used and every row's `backend` says so (CI and the tests run this way).
4. **Clustering.** Agglomerative, average linkage, cosine distance, threshold **0.85 set before looking**. Sensitivity at 0.80 and 0.90 is reported, never used for leads.
5. **Leads.** `overlap_lead`: the group was funded by **2+ resolved agencies in FY2025** (`lead_fy`, the last year in the data; definition unchanged). `multi_agency_any_year` is the looser reading (2+ resolved agencies over FY2009-FY2025). `multi_listed_any_year` keeps the round-1 reading (2+ names as listed) and `collapsed_by_aliases` marks the groups that had 2+ names but are one agency after the map.

## The alias map (`reference/grantor_agency_aliases.csv`)

One row per distinct grantor string in `raw.grants`: **1,944 rows**, columns `grantor_raw`, `grantor_agency`, `agency_code`, `reason`, `evidence`. Targets are the pipeline's own agency names (`mart.agency_name`, or `mart.agency_master` for the few agencies outside the budget data, such as Maryland Environmental Service). The rows were drafted from rules and then read through by hand. The rules:

* **Reading the grantor.** The listed agency is the part before "/", then, when that is not itself an agency name, the part before " - " (the FY2015 and FY2018 files join agency and program with a dash). A trailing abbreviation in parentheses is dropped ("Maryland Department of Disabilities (MDOD)").
* **current name / spelling** (1,299 + 126 rows): the agency under its current name, or a variant spelling of it ("Commerce", "Department of Environment", "Executive -- Boards, Commissions, and Offices").
* **rename** (227 rows), always with the year of the change: Health and Mental Hygiene -> Maryland Department of Health (2017); Labor, Licensing and Regulation -> Maryland Department of Labor (2019); Business and Economic Development -> Commerce (2015); Human Resources -> Human Services (2017); Crime Control and Prevention -> Crime Prevention, Youth and Victim Services (2020) -> Crime Prevention and Policy (2023); Maryland Emergency Management Agency -> Department of Emergency Management (2022); Veterans Affairs -> Veterans and Military Families (2023); Interagency Committee -> Commission on School Construction (2018).
* **fund of agency / program of agency / unit of agency** (21 + 146 + 124 rows): a fund, program or office named in the grantor field goes to the agency that runs it. Examples: MD Stem Cell Research Fund, Maryland Innovation Initiative and the Technology Commercialization and Cyber Investment funds -> TEDCO (also when FY2015 lists them under Commerce); Chesapeake and Atlantic Coastal Bays Trust Fund -> Natural Resources; MEMA, MSFA, UASI and FEMA grants under the Military Department -> Department of Emergency Management; AmeriCorps (Governor's Office on Service and Volunteerism, listed under the Executive Department's boards and commissions or the Governor's Office of Community Initiatives) -> Department of Service and Civic Innovation (2023 move); the Crime Control and Prevention grants listed under "Boards and Commissions" (FY2009-FY2016, FY2019) and the 200 Crime Prevention, Youth and Victim Services rows FY2021 lists under the Emergency Management Agency -> Crime Prevention and Policy; Children's Cabinet Interagency Fund -> Governor's Office for Children; MDOT modal administrations and their programs -> Department of Transportation (as `reference/payment_agency_rules.csv` does for payments); Judiciary's Family Administration / Juvenile and Family Services, Mediation and Conflict Resolution Office and Access to Justice -> Judiciary. FY2018 lists most grantors by program only ("Resource Conservation Grants", "Senior Care", "MD STATE ARTS COUNCIL"); each goes to the agency that lists the same program in the other years.
* **A program under one agency that belongs to another** is checked before the listed agency (for example "Department of Commerce - MD Stem Cell Research Fund" -> TEDCO), and its reason says which agency it was listed under.
* **unknown** (1 row): "Administration and Operations" (FY2018, one $63K climate-training grant) keeps its listed name.
* Two calls rest on judgment, not a document: Developmental Disabilities Council -> Department of Disabilities ("assumed" in its reason), and every program under "Boards and Commissions" other than AmeriCorps -> Crime Prevention and Policy (they are victim-services and justice grants, but a few, such as Citizenship Promotion, may be another office's).

`tests/test_grant_groups.py` checks the map: one row per grantor string, every reason from the list above, every rename with a year, one name per agency code, unknown under 1%, and (when the database is built) that it covers every grantor in `raw.grants` and targets only pipeline agency names. A new grantor string in a future extract shows up as `alias_reason = 'not in map'` and in `rows_alias_not_in_map` (0 now).

## Results (Nov 9, 2026 extract; alias map applied)

| Threshold | Groups | 2+ descriptions | FY2025 leads | Lead FY2025 $ | 2+ names as listed, any year | 2+ resolved agencies, any year | Their FY2025 $ | Collapsed by the map |
|---|---|---|---|---|---|---|---|---|
| 0.80 | 3,452 | 763 | 1 | $17.18M | 463 | 71 | $40.8M | 392 |
| **0.85** | **3,803** | **660** | **1** | **$17.18M** | **445** | **56** | **$34.3M** | **389** |
| 0.90 | 4,161 | 524 | 1 | $17.18M | 417 | 42 | $22.3M | 375 |

FY2025 grants total $1.08B; 480 groups have FY2025 dollars. **The alias map collapses 389 of the 445 any-year multi-agency groups (87%)**; none gains a second agency. The FY2025 lead count is unchanged: the single lead is still **"VARIOUS"** (Natural Resources and Transportation), generic text, **spurious**. At the pre-set definition there are **no real same-year overlap leads in FY2025**, before or after the map, at any threshold.

## Hand check: top 20 groups with 2+ resolved agencies in any year (threshold 0.85)

Ranked by FY2025 dollars, ties (groups with no FY2025 dollars) by all-years dollars (`amount_all_years`). Real = the same purpose funded by genuinely different agencies. Spurious = generic text, a program that moved between agencies (never funded by both in one year), or a mislabeled grantor. Unclear = the description is only the grantee's name, so the purpose cannot be compared; not counted as real.

| # | Group (representative description) | FY2025 $ | All years $ | Agencies | Verdict |
|---|---|---|---|---|---|
| 1 | VARIOUS | $17.18M | $53.2M | Natural Resources (FY2025, land trusts); Transportation (FY2018-FY2025, transit operators) | spurious: generic text, two unrelated programs |
| 2 | Downtown Partnership Baltimore (capital / operating) | $12.00M | $24.0M | Commerce (FY2023); Housing and Community Development (FY2024-FY2025) | **real**: one grantee and purpose funded by two agencies, in different years (ask whether funding moved or was doubled) |
| 3 | School Based Health Centers | $3.81M | $7.7M | Education (FY2009-FY2016); Health (FY2023-FY2025) | spurious: the program moved; never both in one year |
| 4 | Legal services for victims of domestic violence | $1.28M | $23.7M | Judiciary (FY2009-FY2025, every year); Crime Prevention and Policy (FY2009-FY2013, FY2020) | **real**: two agencies fund domestic-violence legal services in the same years (both in FY2009, FY2011, FY2013 and FY2020), to some of the same grantees (Heartly House, Life Crisis Center, Mid-Shore Council on Family Violence in FY2020) |
| 5 | 21st Century Community Learning Centers | $0 | $78.0M | Education (FY2012-FY2021); Budget and Management (one FY2022 grant) | spurious: the DBM row is a one-off named grant that matches on words only |
| 6 | Systems Reform Initiative | $0 | $48.3M | Governor's Office for Children (Children's Cabinet fund, listed under Education); Education (FY2020-FY2021) | spurious: one fund, moved; the map sends the fund rows to GOC |
| 7 | AmeriCorps State Service funding | $0 | $36.6M | Service and Civic Innovation; Executive Department (GOCI, FY2018) | spurious: one program; FY2018 lists GOCI without the program name, so the map leaves it under the Executive Department (a map gap) |
| 8 | LMB Administration | $0 | $20.0M | Governor's Office for Children (FY2011); Education (FY2015, Local Management Boards) | spurious: same Children's Cabinet funding to the same boards, moved |
| 9 | Household assistance in BGE service territory | $0 | $12.2M | Judiciary (FY2014); Public Service Commission (FY2015) | spurious: one grantee (Fuel Fund), the BGE merger customer investment program (PSC); the Judiciary label is likely a mislabeled grantor |
| 10 | Maryland Zoo in Baltimore | $0 | $10.2M | General Services; Budget and Management; Education | unclear: grantee-name description; capital (DGS), operating (DBM) and older state-aid (MSDE) channels for one grantee |
| 11 | Hippodrome Foundation | $0 | $9.0M | Budget and Management; General Services | unclear: grantee name; capital vs operating channel |
| 12 | National Aquarium in Baltimore | $0 | $8.9M | Budget and Management; General Services; Education | unclear: as #10 |
| 13 | Anaerobic digestion of animal litter | $0 | $6.6M | Agriculture (FY2018); Energy Administration (FY2019), same grantees | spurious: the Animal Waste to Energy pilot moved from MDA to MEA |
| 14 | Garrett College performing arts | $0 | $5.5M | Budget and Management; General Services | unclear: grantee name; capital vs operating channel |
| 15 | Operating Assistance | $0 | $4.8M | Transportation; Housing and Community Development | spurious: generic text |
| 16 | Historic Annapolis | $0 | $4.7M | Budget and Management; General Services | unclear: grantee name; capital vs operating channel |
| 17 | Olney Theatre Center | $0 | $3.3M | Budget and Management; General Services; Education | unclear: as #10 |
| 18 | YMCA of the Chesapeake | $0 | $3.3M | Budget and Management; General Services | unclear: grantee name; capital vs operating channel |
| 19 | Roberta's House | $0 | $3.2M | General Services (FY2020); Human Services (FY2024) | unclear: grantee name, different years |
| 20 | Living Classrooms Foundation | $0 | $3.1M | General Services; Human Services; Education | unclear: grantee name |

**Precision of the top-20 check: 2 of 20 (10%) after the alias map, against 1 of 20 (5%) before it** (round 1: 19 of 20 were one agency under two names). **0 of 1** for the pre-set FY2025 reading, before and after. The map did what it was for: no group in the new top 20 is one agency under two names. What is left is a different kind of false positive: programs that moved between agencies (#3, #6, #8, #13), generic text (#1, #15), and grantee-name descriptions on the legislative and capital grants paid through DGS and DBM (#10-#12, #14, #16-#20). Only 5 of the 56 groups have FY2025 dollars.

## What would make it more useful

* A **same-year** check on the any-year groups (are the agencies' years disjoint?) would drop most program moves automatically; the pre-set FY2025 lead already does this and finds no real lead.
* Grant descriptions that are only a grantee name (most DGS and DBM rows) say nothing about purpose; comparing them needs the bond bill or budget line, not this dataset.
* Grant descriptions are often program names, not purposes ("Strategic Demolition - CORE - Capital"); purpose-level overlap needs the award documents.

## Columns

`d_grant_groups`: `group_id` (stable hash of the member description keys), `rank_fy` (by FY2025 dollars, ties by all-years dollars), `description` (the member with the most dollars over all years), `n_descriptions`, `example_descriptions` (up to three other members), `grantor_agencies` / `n_agencies` / `grantees` (resolved agencies, all years), `grantors_listed` / `n_grantors_listed` (names as listed, all years), `grantor_agencies_fy2025` / `n_agencies_fy2025` / `grantees_fy2025` / `rows_fy2025` / `amount_fy2025`, `amount_all_years`, `first_fy`, `last_fy`, `overlap_lead`, `multi_agency_any_year`, `multi_listed_any_year`, `collapsed_by_aliases`, `backend`, `cosine_threshold`. `d_grant_groups_sensitivity` adds `multi_listed_any_year`, `collapsed_by_aliases` (counts), `rows_alias_not_in_map` and `rows_alias_unknown`.
