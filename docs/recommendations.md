# The six recommendations: data and build

The GMI Savings Tracker's Overview recommends six steps. Each is produced by the pipeline and re-checked every run.

| # | Recommendation | Data it needs | Where it comes from | Built in |
|---|---|---|---|---|
| 1 | Bid statewide contracts for shared vendors | Payments by vendor and agency; vendor master list | Payments (7syw-q4cy); `reference/` vendor map | Extract ✔, database ✔; bid list in Phase 5 |
| 2 | Confirm which reported savings recur | GMI's reported items; payments to matching vendors each year; status history | GMI Joint Chairmen's Report (reference CSV); payments | Extract ✔; checks in Phase 5 |
| 3 | Name the seven renegotiated contracts | Vendor payments FY2025 vs FY2026 | Payments | Extract ✔; candidate search in Phase 5 |
| 4 | Plan the path to $50M | Budget by spending code and year; forecasts; **CPI** for real-dollar trends | Budget (yu65-jmmv); CPI (BLS, FRED fallback) | Extract ✔, `core.cpi_fy` ✔; plan in Phase 5 |
| 5 | Keep one vendor and agency master list | Payment agency names; payee names; budget agency codes | Payments, budget; `reference/` maps | Extract ✔, `ref.dim_agency` ✔; maps and match rates in Phase 3 |
| 6 | Tie spending to results | **Managing for Results** measures by agency; spending by agency | DBM MFR strategic plans (111 agency PDFs, FY2027); budget | Extract ✔, `core.mfr_document` ✔; measures parsed from the PDFs in Phase 3 |

Context added for all six: federal grants to Maryland governments (USAspending, `core.fact_federal_award`) to separate federal from General Fund savings, and population (Census estimates, `core.fact_population`) for spending per resident.
