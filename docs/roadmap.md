# Roadmap

Six phases over about eight weeks; each phase's gate must pass before the next starts. Full plan: the *Maryland Transparency Data — Dev Wiki*, Roadmap & build plan tab.

| Phase | Weeks | Build | Gate | Status |
|---|---|---|---|---|
| 0. Align | done | Data dictionary, gap analysis, API references, reference lists | Team signs off on definitions | Done |
| 1. Extract | 1 | `extract.py`: 20,000-row pages by `:id`, retries, freshness check on `rowsUpdatedAt`, Parquet per run, manifest with portal counts and totals | Two runs in a row match portal row counts | **Passed Oct 28, 2026**; context sources added Oct 29 |
| 2. Database | 2–3 | DuckDB `raw`, `core`, `ops`; type casting and code normalizing; reconciliation checks; non-zero exit on failure | Every check passes; yearly totals tie to the portal | **Passed Oct 29, 2026** (30 of 30) |
| 3. Reference data | 3–4 | `ref` layer from `reference/` CSVs: agencies and aliases, stages, focus areas, payment-name and vendor maps; match-rate report | Match rates at or above the dashboard's master list quality | **Passed Oct 29, 2026** |
| 4. Marts & dashboard | 4–5 | One `mart` table per dashboard file; `export.py` writes the CSVs; FY2027 payments as a partial year | Every dashboard file reproduced, or each difference explained | **Gate passed for the 21 base dashboard files (Nov 2, 2026).** `sql/mart/*.sql` (28 files; the change measure applied by `marts.py` from each file's `-- yoy:` header), `make parity` against the legacy files: 13 reproduced exactly; 8 differ only as explained in `docs/parity/explanations.csv` (FY2027 partial year added; one company spelled differently). Also added: vendor master, payee types, agency functions, agency roll-up and results marts. Fixed on the way: scope precedence (client payments, then charges between agencies, then staff/grants/capital) and the payee-name pass-through exclusions (`reference/payee_area_exclusions.csv`). Left for Phase 5: the analytics files (opportunities, forecasts, savings checks, recommendations) and `export.py` |
| 5. Analytics | 5–7 | Forecasts, savings detectors, savings checks, path to $50M on the database | Outputs match the dashboard | |
| 6. Automate & document | 7–8 | `make all`; launchd or cron on the Mac; run log, optional PDF report, wiki update | Two clean scheduled runs with no manual steps | |

## Open questions
- Which decision for the 4 unmatched payment agency names? Recorded as pending in `reference/payment_agency_decisions.csv`; none paid in FY2026.
- Is 4mca-332u (higher-education CUR and CR funds) already inside yu65-jmmv's totals?
- When to register the Socrata app token (before daily scheduling).
