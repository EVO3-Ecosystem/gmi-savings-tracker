# Checks catalog

A failed "Stop" check ends the run before anything is exported.

| Check | Layer | On failure | Phase | Implemented |
|---|---|---|---|---|
| Rows downloaded = portal `count(*)` (self-heals by re-downloading up to twice) | raw | Stop | 1 | yes (`extract.py`) |
| Portal per-year totals saved with each run | raw | Stop | 1 | yes (`extract.py`, `tests/test_extract.py`) |
| Yearly totals = portal's own `sum()` (budget, payments) | core | Stop | 2 | |
| Budget totals = funding-source totals, within $1 | core | Stop | 2 | |
| Object codes two digits; sub-object codes join to `dim_subobject` | core | Stop | 2 | |
| Every focus-area code exists in the budget | ref | Stop | 3 | |
| Payment agency names matched to a code, share of dollars | ref | Warn below today's rate | 3 | |
| New payee names since last run | ref | Warn and list them | 3 | |
| Each mart total = its core total | mart | Stop | 4 | |
| Exported files differ from last run | mart | Report the changes | 4 | |

The legacy pipeline ran about 90 checks (see the GMI Savings Tracker's Data & pipeline tab); phases 2–5 port them here.
