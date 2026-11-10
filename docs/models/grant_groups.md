# Model card: grant groups and overlap leads

**What it does.** Groups the State's grant descriptions (grants and loans dataset, absk-avps, FY2009-FY2025) by meaning, so grants with the same purpose given by different grantor agencies show up together as possible overlap leads. Code: `src/models/grant_groups.py`. Input: `sql/mart/61_v_grant_rows.sql`. Outputs: `mart.d_grant_groups` (one row per group), `mart.d_grant_group_members` (description -> group), `mart.d_grant_groups_sensitivity` (one row per threshold). Settings: `config/assumptions.yaml` (`grant_groups`). Checks: `src/pipeline/checks_ml.py`.

**A lead is a question, not a finding.** It says only that two or more agencies fund grants described alike. It is not a duplicate, not waste and **not a saving**. Grant dollars in a group are what was granted; they are not additive with payments (grants are largely paid out through the payments data, `mart.f_overlap`), not additive across groups and not additive across thresholds.

## Method

1. **Descriptions.** 23,084 grant rows with a description; matched after lower case and collapsed spaces: **5,008 distinct descriptions**. Grantor agency = the grantor before the first "/" (the portal joins agency and program), upper case, "&" as AND, punctuation and a leading MARYLAND or STATE removed (393 spellings -> 363). Renamed agencies stay separate (Health and Mental Hygiene and Health are two names).
2. **Embeddings.** sentence-transformers `all-MiniLM-L6-v2` on CPU, normalized (installed with `pip install sentence-transformers`, model downloaded through the proxy; cached in `data/ml_cache/`). **Backend used for the results below: all-MiniLM-L6-v2.** If the package or model cannot load, TF-IDF word unigrams + bigrams are used and every row's `backend` says so.
3. **Clustering.** Agglomerative, average linkage, cosine distance, threshold **0.85 set before looking** (descriptions whose average similarity is at least 0.85 join). Sensitivity at 0.80 and 0.90 is reported, never used for leads.
4. **Leads.** `overlap_lead`: the group was funded by **2+ grantor agencies in the same year, FY2025** (the last year in the data; same year so a renamed agency is not counted twice). `multi_agency_any_year` is the looser reading (2+ agencies over FY2009-FY2025), added after the FY2025 definition returned one group, and checked by hand below.

## Results (Nov 9, 2026 extract, run 20261109T154457Z)

| Threshold | Groups | Groups with 2+ descriptions | FY2025 leads (2+ agencies in FY2025) | Lead FY2025 grant $ | 2+ agencies, any year | Their FY2025 grant $ |
|---|---|---|---|---|---|---|
| 0.80 | 3,452 | 763 | 1 | $17.18M | 463 | $219.7M |
| **0.85** | **3,803** | **660** | **1** | **$17.18M** | **445** | **$173.3M** |
| 0.90 | 4,161 | 524 | 1 | $17.18M | 417 | $128.5M |

FY2025 grants total $1.08B; 480 groups have FY2025 dollars. The single FY2025 lead is the description **"VARIOUS"** (Natural Resources and Transportation): generic text, **spurious**. So at the pre-set definition there are **no real same-year overlap leads** in FY2025, at any threshold.

## Hand check: top 20 groups with 2+ agencies in any year, by FY2025 dollars (threshold 0.85)

Real = the same purpose funded by genuinely different agencies. Spurious = one agency under two names (rename, reorganization), a program or fund name in the grantor field, or generic text.

| # | Group (representative description) | FY2025 $ | Agencies in the group | Verdict |
|---|---|---|---|---|
| 1 | Nonpoint source pollution best management practices | $18.48M | Natural Resources; Chesapeake & Atlantic Coastal Bays Trust Fund | spurious: the Trust Fund is DNR's own fund |
| 2 | VARIOUS | $17.18M | Natural Resources; Transportation; two program names | spurious: generic text |
| 3 | Cancer Research Activities | $15.00M | Health; Health and Mental Hygiene | spurious: rename (DHMH -> MDH) |
| 4 | Commercialization Investment | $12.24M | TEDCO; six fund names (Commerce funds) | spurious: fund names in the grantor field; one program |
| 5 | Downtown Partnership Baltimore (capital / operating) | $12.00M | Commerce (FY2023); Housing and Community Development (FY2024-FY2025) | **real**: one grantee and purpose funded by two different agencies (in different years: ask whether funding moved or was doubled) |
| 6 | GRANTS TO NON-GOV ENTITIES | $10.58M | Agriculture; six program names | spurious: generic text and program names |
| 7 | Stem Cell Research Grant | $10.20M | TEDCO; MD Stem Cell Research Fund (two spellings) | spurious: the fund is TEDCO's |
| 8 | Prince George's County Hospital | $10.00M | Health; Health and Mental Hygiene; its Prevention and Health Promotion Administration | spurious: rename and a unit name |
| 9 | Unemployment Insurance IT best practices | $9.13M | Labor; Labor, Licensing and Regulation | spurious: rename (DLLR -> Labor) |
| 10 | UASI Non-Profit Security Grant | $6.89M | Emergency Management; Military Department | spurious: MEMA moved out of the Military Department (reorganization) |
| 11 | Metropolitan Planning Organization requirements | $6.28M | Transportation; "Operating grants in aid" | spurious: program name in the grantor field |
| 12 | E-nnovation Initiative | $5.40M | Commerce (three spellings) | spurious: one agency |
| 13 | Maryland Innovation Initiative | $4.61M | TEDCO; Commerce fund name | spurious: program administered by TEDCO |
| 14 | Performance Incentive Grant Fund | $4.46M | Crime Prevention and Policy (FY2025); Emergency Management Agency (FY2021, other grantees) | spurious / unclear: same program name, different grantees and years; likely a mislabeled grantor, not counted as real |
| 15 | School Based Health Centers | $3.81M | Health; Education (two spellings) | spurious as overlap: the program moved between agencies over time; never funded by both in one year |
| 16 | Sexual Assault Rape Crisis | $3.15M | Crime Control and Prevention under five names | spurious: renames |
| 17 | Domestic Violence Prevention | $2.57M | Crime Control and Prevention under five names | spurious: renames |
| 18 | Regional Navigators Crime Victim Assistance | $2.53M | Crime Prevention, Youth and Victim Services; Crime Prevention and Policy | spurious: rename |
| 19 | Baltimore Regional Neighborhood Initiative | $2.33M | Housing and Community Development; program name | spurious: program name in the grantor field |
| 20 | Advocacy for children in foster care | $1.71M | Judiciary; its Department of Family Administration | spurious: one agency's unit |

**Precision of the top-20 check: 1 of 20 (5%)** for the any-year reading; **0 of 1** for the pre-set FY2025 reading. The grouping itself works (descriptions that differ in case, punctuation, year suffix or wording land together: e.g. 7 spellings of the UASI grant, 4 of School Based Health Centers); the agency field does not. Almost every apparent overlap is one agency under several names.

## What would make it useful

* A hand-kept grantor-agency map (rename history and fund-to-agency, e.g. DHMH -> MDH, DLLR -> Labor, GOCCP -> GOCPP, Stem Cell Research Fund -> TEDCO), like `reference/payment_agency_rules.csv` for payments. With it, the any-year reading would stop counting renames and the remaining leads could be checked again.
* Grant descriptions are often program names, not purposes ("Strategic Demolition - CORE - Capital"); purpose-level overlap needs the award documents, not this dataset.

## Columns

`d_grant_groups`: `group_id` (stable hash of the member description keys), `rank_fy` (by FY2025 dollars), `description` (the member with the most dollars over all years), `n_descriptions`, `example_descriptions` (up to three other members), `grantor_agencies` / `n_agencies` / `grantees` (all years), `grantor_agencies_fy2025` / `n_agencies_fy2025` / `grantees_fy2025` / `rows_fy2025` / `amount_fy2025`, `first_fy`, `last_fy`, `overlap_lead`, `multi_agency_any_year`, `backend`, `cosine_threshold`.
