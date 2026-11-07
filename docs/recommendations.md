# The six recommendations: data and build

The GMI Savings Tracker's Overview recommends six steps. Each is produced by the pipeline and re-checked every run.

| # | Recommendation | Data it needs | Where it comes from | Built in |
|---|---|---|---|---|
| 1 | Bid statewide contracts for shared vendors | Payments by vendor and agency; vendor master list | Payments (7syw-q4cy); `reference/` vendor map | ✔ `mart.d_bid_list` (30 vendors) and vendor drill-downs |
| 2 | Confirm which reported savings recur | GMI's reported items; payments to matching vendors each year; status history | `reference/gmi_reported_savings.csv` (18 items); payments | ✔ `mart.d_savings_status`, with history |
| 3 | Name the seven renegotiated contracts | Vendor payments FY2025 vs FY2026 | Payments | ✔ the four named contract types are checked; `mart.d_vendor_moves` lists the largest decreases |
| 4 | Plan the path to $50M | Budget by spending code and year; forecasts; **CPI** for real-dollar trends | Budget (yu65-jmmv); CPI (BLS, FRED fallback) | ✔ `mart.d_plan50`; see `docs/models/recommendations.md` for how much of it rests on assumptions |
| 5 | Keep one vendor and agency master list | Payment agency names; payee names; budget agency codes | Payments, budget; `reference/` maps | ✔ `ref.map_payment_agency` (143 of 145 names after the Nov 4 agency decisions; 100% of FY2026 dollars), `ref.map_payee_vendor` (9,686 names in 4,478 multi-name companies) |
| 6 | Tie spending to results | **Managing for Results** measures by agency; spending by agency | DBM MFR strategic plans (111 agency PDFs, FY2027); budget | ✔ `core.mfr_measure`: 2,957 measures from 108 plans, 106 of 111 plans matched to a budget agency |

Context added for all six: federal grants to Maryland governments (USAspending, `core.fact_federal_award`) to separate federal from General Fund savings, and population (Census estimates, `core.fact_population`) for spending per resident.
