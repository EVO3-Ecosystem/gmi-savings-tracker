# Checks catalog

A failed "Stop" check ends the run before anything is exported. The export itself is gated (`src/pipeline/gate.py`): it refuses to run when the database has a failed check, when a newer build failed (the database is stale), or when `docs/parity/summary.csv` is missing or has an unexplained difference. `make test-fault` shows a damaged extract failing its checks while the last good database is kept.

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
| Each dashboard-file mart = the legacy file (or the difference explained) | mart | Stop (`make parity`) | 4 | yes: 12 of 21 exact, 9 explained |
| Exported files differ from last run | mart | Report the changes | 4 | yes (`export.py` writes `changed` per file to `manifest.csv`) |
| Forecast ranges ordered (p10 <= p50 <= p90) | mart | Stop | 5 | yes |
| Forecast actuals add up to controllable purchases (every actual year); FY2025 baseline = the area's actual | mart | Stop | 5 | yes |
| Every forecast area has nine actual and six forecast years | mart | Stop | 5 | yes |
| Every forecast area also scored against the State's plan for FY2026 and FY2027 | mart | Stop | 5 | yes |
| Backtest ranges ordered (p10 <= p50 <= p90) | mart | Stop | 5 | yes |
| Chosen forecast model no worse than naive on the rolling-origin backtest (against actuals) | mart | Warn | 5 | yes |
| Published forecast ranges cover about their nominal 80% on the rolling backtest (within 10 points) | mart | Warn | 5 | yes |
| Opportunity findings well formed (low <= high, unique ids, one per agency and code) | mart | Stop | 5 | yes |
| Bid list vendors meet the agency and spend thresholds and are ranked by FY2026 payments | mart | Stop | 5 | yes |
| Growth detector does not lean on findings that grew 1,000% or more | mart | Warn | 5 | yes |
| Every reported savings item is unique, cites a page and a quote, and has low <= high | mart | Stop | 5 | yes |
| Every payment check matches payments, and the four named contract types are checked | mart | Stop | 5 | yes |
| Every payment check has a status (reports how many are Seen, Partly seen, Not seen yet) | mart | Stop | 5 | yes |
| Vendor moves are decreases by vendors paid by enough agencies, largest first | mart | Stop | 5 | yes |
| All six recommendations have a status and a key number | mart | Stop | 5 | yes |
| The path to $50M is numbered, adds up, and agrees with recommendation 4's status | mart | Stop | 5 | yes |
| Vendor drill-downs tie to their payee names, and every bid-list vendor has one | mart | Stop | 5 | yes |
| Most of the path to $50M does not rest on assumed saving rates | mart | Warn | 5 | yes |

The legacy pipeline ran about 90 checks (see the GMI Savings Tracker's Data & pipeline tab); phases 2–5 port them here.
