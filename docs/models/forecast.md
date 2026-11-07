# Model card: focus-area spending forecasts

**What it does.** For each of GMI's six focus areas, and for the rest of controllable purchases, it projects annual spending from FY2026 to FY2031 with a 10th, 50th and 90th percentile range, and sets it beside the State's own plan for FY2026 and FY2027. The Calculator uses the median as the baseline that savings are measured against. Code: `src/models/forecast.py` (a port of `legacy/gst/scripts/forecast.py`); assumptions: `config/assumptions.yaml`; tables: `mart.f_forecast`, `mart.d_forecast_model`, `mart.d_forecast_backtest`.

**Data.** Actual spending FY2017 to FY2025 from the operating budget (nine annual points per area). FY2026 (working budget) and FY2027 (legislative appropriation) are the State's plan: shown, never used to fit.

**Models.** Three candidates per area: log-linear trend, naive (last actual, no growth) and drift (last actual growing at the average yearly rate). The naive model is the baseline every other model has to beat.

**Choice rule (unchanged from the legacy pipeline, so the dashboard stays comparable).** Fit through FY2022, score FY2023 to FY2025, keep the lowest mean absolute percentage error. **Ranges:** 4,000 seeded bootstrap paths (resampled residuals for the trend, resampled yearly changes for naive and drift); they widen with the horizon.

**Added evaluation (`mart.d_forecast_backtest`).** A rolling-origin backtest: every model is refitted at each origin from FY2021 to FY2024 and scored one to three years ahead, never using a later year. MASE divides each error by the mean one-step naive error inside that origin's own training years, so no future value enters the scale. A MASE above 1 means the error is larger than what standing still would have cost one year at a time in the training history.

## Results (rolling origins FY2021 to FY2024, mean MASE)

| Area | Chosen by the legacy rule | Naive | Drift | Trend | Best on rolling origins |
|---|---|---|---|---|---|
| Fleet & fuel | Naive | **5.07** | 5.88 | 6.47 | Naive |
| IT hardware, software & services | Naive | **0.74** | 2.53 | 2.45 | Naive |
| Other controllable purchases | Naive | **0.86** | 2.27 | 2.36 | Naive |
| Print, copy & mail | Naive | **1.74** | 2.52 | 2.28 | Naive |
| Real estate & leases | Trend | 2.02 | 1.66 | **1.57** | Trend (agrees) |
| Telecom | Naive | **0.85** | 1.41 | 1.20 | Naive |
| Utilities & facility energy | Drift | **3.78** | 4.10 | 4.41 | **Naive (disagrees)** |

## What this shows

- Growth models rarely beat standing still on this data. The legacy rule already chooses naive for five of seven areas, and the rolling backtest agrees with the choice for six of seven.
- **Utilities & facility energy is the exception:** the legacy rule picks drift because it wins one three-year split, but over rolling origins drift is worse than naive (MASE 4.10 against 3.78). The build reports this as a warning ("Chosen forecast model is no worse than the naive baseline"). The choice is left as the legacy rule made it so the Calculator does not change silently; switching the rule to rolling-origin MASE is a one-line decision for the owner.
- Most MASE values are above 1: with nine annual points and spending that moves by programme decisions, no candidate forecasts these series well. Fleet & fuel and Utilities are the hardest (MASE above 3).

## Limits

- Nine points per area. The ranges are bootstrap ranges around a simple model, not validated prediction intervals: their coverage has not been tested and with this little history it cannot be.
- Naive forecasts carry no growth, so a "naive" baseline is flat in expectation; the range still widens because it resamples past yearly changes.
- Spending is nominal dollars. Real-dollar and per-resident views are separate roadmap items (`core.cpi_fy`, `core.fact_population`).
- GMI's recurring savings come from its January 2026 report (middle of each reported range, from `reference/gmi_reported_savings.csv`); an area with no figure gets no default rate.

## Checks that run on every build

Ranges are ordered; actuals add up to controllable purchases in every year; every area has nine actual and six forecast years; the chosen model is no worse than naive on the rolling backtest (warning). The legacy script and this port give identical tables on the real marts (`tests/test_forecast_parity.py`).

## Rebuild

`make build` rebuilds the tables with the rest of the database (about 2 seconds for the forecasts). Same seed, same output.
