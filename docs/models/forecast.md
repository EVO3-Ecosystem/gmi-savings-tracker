# Model card: focus-area spending forecasts

**What it does.** For each of GMI's six focus areas, and for the rest of controllable purchases, it projects annual spending from FY2026 to FY2031 with a 10th, 50th and 90th percentile range, and sets it beside the State's own plan for FY2026 and FY2027. The Calculator uses the median as the baseline that savings are measured against. Code: `src/models/forecast.py` (a port of `legacy/gst/scripts/forecast.py`); assumptions: `config/assumptions.yaml`; tables: `mart.f_forecast`, `mart.d_forecast_model`, `mart.d_forecast_backtest`.

**Data.** Actual spending FY2017 to FY2025 from the operating budget (nine annual points per area). FY2026 (working budget) and FY2027 (legislative appropriation) are the State's plan: shown, never used to fit.

**Models.** Three candidates per area: log-linear trend, naive (last actual, no growth) and drift (last actual growing at the average yearly rate). The naive model is the baseline every other model has to beat.

**Choice rule (unchanged from the legacy pipeline, so the dashboard stays comparable).** Fit through FY2022, score FY2023 to FY2025, keep the lowest mean absolute percentage error. **Ranges:** 4,000 seeded bootstrap paths (resampled residuals for the trend, resampled yearly changes for naive and drift); they widen with the horizon.

**Added evaluation (`mart.d_forecast_backtest`).** A rolling-origin backtest: every model is refitted at each origin from FY2021 to FY2025 and scored one to three years ahead, never using a later year. Forecast years up to FY2025 are scored against **actual** spending; FY2026 (working budget) and FY2027 (legislative appropriation) are scored against **the State's plan** and labelled `target = plan`. A plan figure is a budget, not an outcome, so those rows show how far a forecast sits from the budget, not how wrong it was; they are kept apart from the actuals and never used to fit or to choose a model. MASE divides each error by the mean one-step naive error inside that origin's own training years, so no future value enters the scale. A MASE above 1 means the error is larger than what standing still would have cost one year at a time in the training history.

## Results against actuals (rolling origins FY2021 to FY2024, forecasts of FY2022 to FY2025, mean MASE)

| Area | Chosen by the legacy rule | Naive | Drift | Trend | Best on rolling origins |
|---|---|---|---|---|---|
| Fleet & fuel | Naive | **5.07** | 5.88 | 6.47 | Naive |
| IT hardware, software & services | Naive | **0.74** | 2.53 | 2.45 | Naive |
| Other controllable purchases | Naive | **0.86** | 2.27 | 2.36 | Naive |
| Print, copy & mail | Naive | **1.74** | 2.52 | 2.28 | Naive |
| Real estate & leases | Trend | 2.02 | 1.66 | **1.57** | Trend (agrees) |
| Telecom | Naive | **0.85** | 1.41 | 1.20 | Naive |
| Utilities & facility energy | Drift | **3.78** | 4.10 | 4.41 | **Naive (disagrees)** |

## The chosen forecast against the State's plan (from the FY2025 origin)

| Area | Model | FY2026 forecast | FY2026 plan | Gap | FY2027 forecast | FY2027 plan | Gap |
|---|---|---|---|---|---|---|---|
| Fleet & fuel | Naive | $193.1M | $227.6M | -15.2% | $193.1M | $224.3M | -13.9% |
| IT hardware, software & services | Naive | $692.2M | $682.1M | +1.5% | $692.2M | $723.6M | -4.3% |
| Other controllable purchases | Naive | $2,806.1M | $3,492.4M | -19.7% | $2,806.1M | $3,452.1M | -18.7% |
| Print, copy & mail | Naive | $52.4M | $56.2M | -6.7% | $52.4M | $60.1M | -12.8% |
| Real estate & leases | Trend | $139.4M | $149.7M | -6.9% | $141.3M | $144.5M | -2.2% |
| Telecom | Naive | $46.8M | $58.0M | -19.3% | $46.8M | $55.6M | -15.7% |
| Utilities & facility energy | Drift | $165.9M | $154.2M | +7.6% | $170.5M | $160.3M | +6.4% |

Gap = forecast minus plan, as a share of the plan. In five of seven areas the State plans to spend more in FY2026 than a model fitted to FY2017 to FY2025 expects; in Fleet & fuel, Telecom and Other controllable purchases by 15 to 20 percent. Whether the plan is the better guide cannot be known until those years have actuals, and across FY2022 to FY2025 the plan has not been tested here. Treat the gap as a question for the budget owners, not an error in either number.

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

Ranges are ordered; actuals add up to controllable purchases in every year; every area has nine actual and six forecast years; every area is scored against the plan for FY2026 and FY2027; the chosen model is no worse than naive on the rolling backtest against actuals (warning). Tests prove that no forecast changes when a later actual or the plan changes (`tests/test_forecast.py`). The legacy script and this port give identical tables on the real marts (`tests/test_forecast_parity.py`).

## Rebuild

`make build` rebuilds the tables with the rest of the database (about 2 seconds for the forecasts). Same seed, same output.
