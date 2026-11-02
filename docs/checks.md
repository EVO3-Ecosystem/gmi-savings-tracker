# Checks catalog

A failed "Stop" check ends the run before anything is exported.

| Check | Layer | On failure | Phase | Implemented |
|---|---|---|---|---|
| Rows downloaded = portal `count(*)` (self-heals by re-downloading up to twice) | raw | Stop | 1 | yes (`extract.py`) |
| Portal per-year totals saved with each run | raw | Stop | 1 | yes (`extract.py`, `tests/test_extract.py`) |
| Yearly totals and row counts = portal's own `sum()` (all five datasets) | core | Stop | 2 | yes |
| Budget totals = funding-source totals, within $1 | core | Stop | 2 | yes |
| No missing year or amount | core | Stop | 2 | yes |
| Agency names carry no code suffix; every budget year has a confirmed stage; latest payments year flagged partial | core/ref | Stop | 2 | yes |
| CPI, federal awards, population, Managing for Results plans present | core | Warn | 2 | yes |
| Object and program codes two digits; sub-object codes without leading zeros | core | Stop | 2 | yes |
| Every focus-area code exists in the budget | ref | Stop | 3 | yes |
| Controllable purchases and focus-area totals FY2025 = dashboard (to the dollar) | ref | Stop | 3 | yes |
| Payee names grouped into companies ≥ dashboard | ref | Stop | 3 | yes |
| Managing for Results measures read from the plans | ref | Warn | 3 | yes |
| Payment agency names matched to a code, share of dollars | ref | Stop below today's rate | 3 | yes |
| New payee names since last run | ref | Warn and list them | 3 | yes |
| Vendor payments by year = core payments; agency roll-up budget by year = core budget | mart | Stop | 4 | yes |
| One vendor master row per vendor; every vendor has a payee type | mart | Stop | 4 | yes |
| Every mapped payment rolls up to a function or a named exception; exceptions are not in the budget | mart | Stop | 4 | yes |
| Each agency's budget sits in one function | mart | Warn | 4 | yes |
| Agency results rows = matched Managing for Results rows | mart | Stop | 4 | yes |
| Each dashboard-file mart = the legacy file (or the difference explained) | mart | Stop | 4 | |
| Exported files differ from last run | mart | Report the changes | 4 | |

The legacy pipeline ran about 90 checks (see the GMI Savings Tracker's Data & pipeline tab); phases 2–5 port them here.
