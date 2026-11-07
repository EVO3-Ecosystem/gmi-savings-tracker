# Model card: focus-area spending forecasts

**What it does.** For each of GMI's six focus areas, and for the rest of controllable purchases, it projects annual spending from FY2026 to FY2031 with a 10th, 50th and 90th percentile range, and sets it beside the State's own plan for FY2026 and FY2027. The Calculator uses the median as the baseline that savings are measured against. Code: `src/models/forecast.py` (a port of `legacy/gst/scripts/forecast.py`); assumptions: `config/assumptions.yaml`; tables: `mart.f_forecast`, `mart.d_forecast_model`, `mart.d_forecast_backtest`, `mart.d_forecast_calibration`.

**Data.** Actual spending FY2017 to FY2025 from the operating budget (nine annual points per area). FY2026 (working budget) and FY2027 (legislative appropriation) are the State's plan: shown, never used to fit.

**Models.** Three candidates per area: log-linear trend, naive (last actual, no growth) and drift (last actual growing at the average yearly rate). The naive model is the baseline every other model has to beat. An equal-weight average of the three is also scored, but is never kept (see below).

## How a model is chosen (changed Nov 7, 2026)

**Rule: lowest mean MASE over the rolling origins, a tie going to naive.** Each model is refitted at origins FY2021 to FY2025 and scored one to three years ahead against actual spending (forecasts of FY2022 to FY2025); the model with the lowest mean MASE is kept. The legacy rule (fit through FY2022, score FY2023 to FY2025 once, lowest MAPE) remains available as `selection: legacy_single_split` in `config/assumptions.yaml`, and `tests/test_forecast_parity.py` proves that under that setting the output is identical to the legacy script. **The new rule changes one area:** Utilities & facility energy moves from drift to naive. Every other area, and every forecast outside Utilities, is identical to the legacy output (also tested).

**Why.** Short series leave little room for one test set, so evaluation on a rolling origin is recommended ([Hyndman's textbook, as summarised by SAS](https://blogs.sas.com/content/forecasting/2016/03/18/rob-hyndman-measuring-forecast-accuracy)); for non-stationary series, out-of-sample methods repeated over several test periods gave the most accurate performance estimates in an empirical study ([Cerqueira, Torgo and Mozetič 2020](https://web3.arxiv.org/abs/1905.11744)), and spending that grows year after year is non-stationary. MASE divides each error by the in-sample naive one-step error, so it is scale-free and values above 1 are worse than naive ([Hyndman and Koehler 2006](https://www.doi.org/10.1016/J.IJFORECAST.2006.03.001)).

**FY2026 and FY2027 are scored against the State's plan, not actuals.** Rows with `target = plan` show how far a forecast sits from the budget, not how wrong it was; they are kept apart and never used to fit or to choose a model.

## Results against actuals (rolling origins FY2021 to FY2024, mean MASE)

| Area | Kept | Naive | Drift | Trend | Equal-weight combination |
|---|---|---|---|---|---|
| Fleet & fuel | Naive | **5.07** | 5.88 | 6.47 | 5.70 |
| IT hardware, software & services | Naive | **0.74** | 2.53 | 2.45 | 1.62 |
| Other controllable purchases | Naive | **0.86** | 2.27 | 2.36 | 1.67 |
| Print, copy & mail | Naive | **1.74** | 2.52 | 2.28 | 2.16 |
| Real estate & leases | Trend | 2.02 | 1.66 | **1.57** | 1.73 |
| Telecom | Naive | **0.85** | 1.41 | 1.20 | 1.11 |
| Utilities & facility energy | Naive | **3.78** | 4.10 | 4.41 | 3.98 |
| Mean over areas | | **2.15** | 2.91 | 2.96 | 2.57 |

- Growth models rarely beat standing still on this data: naive is best in six of seven areas, trend in Real estate & leases only.
- **An equal-weight combination does not earn a place.** Averaging is a strong baseline in the forecasting literature: simple combinations often work well ([Clemen 1989](https://people.duke.edu/~clemen/bio/Published%20Papers/13.CombiningReview-Clemen-IJOF-89.pdf)), twelve of the seventeen most accurate M4 methods were combinations ([M4 commentary](https://blogs.sas.com/content/forecasting/2020/01/08/m4-forecasting-competition-results-and-commentary)), and its advantage depends on how unstable the individual models are ([Wang, Hyndman, Li and Kang 2022](https://arxiv.org/pdf/2205.04216)). Here it beats both drift and trend in five of seven areas and beats naive only in Real estate & leases (where trend is better still), so it is never the best (mean MASE 2.57 against naive's 2.15). It stays in the backtest table as a candidate that selection cannot pick, so the result can be re-checked when more actuals arrive.
- Most MASE values are above 1: with nine annual points and spending that moves by programme decisions, no candidate forecasts these series well. Fleet & fuel and Utilities are the hardest (MASE above 3).
- A significance test would not help yet: the small-sample correction of the Diebold-Mariano test ([Harvey, Leybourne and Newbold 1997; later small-sample work](https://eprints.nottingham.ac.uk/43017)) needs more forecasts than four origins provide, so the rule is a plain lowest-error choice with ties to the baseline.

## How far to trust the ranges

Ranges are the 10th and 90th percentiles of 4,000 seeded bootstrap paths per area (resampled residuals for the trend, resampled yearly changes for naive and drift). A range is only useful if it covers about what it claims, and the interval score rewards narrow ranges that still cover ([Gneiting and Raftery 2007](https://apps.dtic.mil/sti/html/tr/ADA459827/index.html)). Coverage of time-series intervals is only approximate in the literature ([conformal prediction for time series](https://arxiv.org/pdf/2010.09107)), so it is measured here on the rolling backtest (`mart.d_forecast_calibration`, a check on every build).

**Finding: the ranges are too narrow.** Of 63 forecasts of actual spending (each area's kept model, 9 per area), **63.5% fell inside the published range, against a nominal 80%.** Coverage is flat across horizons (64% one year ahead, 62% two, 64% three) and very uneven across areas:

| Area | Covered | Area | Covered |
|---|---|---|---|
| Fleet & fuel | 11% | Real estate & leases | 44% |
| Print, copy & mail | 56% | Utilities & facility energy | 56% |
| IT hardware, software & services | 89% | Other controllable purchases | 89% |
| Telecom | 100% | **All areas** | **63.5%** |

A pooled widening of about **1.63 times** (around the median, on the log scale) would have covered 80% in this backtest, but it is measured in-sample on a handful of points and would be wrong for most areas: three areas already cover enough or too much while Fleet & fuel misses almost everything. The build warns when pooled coverage is more than ten points from nominal; it does today.

**Recommendation (not applied).** The p10 and p90 columns are documented as the 10th and 90th percentile of the bootstrap forecast and the Calculator uses them, so the ranges are left as published rather than changed silently. Treat them as indicative, not as an 80% range; show the observed coverage next to them; and revisit when FY2026 actuals arrive (about one more point per area), re-running `make build` to refresh the measurement. A calibrated range (widening by the backtest's own errors, the idea behind conformal methods) is the likely end state, but with nine points per area it should be pooled or judgement-based, not fitted per area. The decision is the owner's.

## Limits

- Nine points per area. The ranges are bootstrap ranges around a simple model, not validated prediction intervals.
- Naive forecasts carry no growth, so a "naive" baseline is flat in expectation; its range still widens because it resamples past yearly changes.
- Spending is nominal dollars. Real-dollar and per-resident views are separate roadmap items (`core.cpi_fy`, `core.fact_population`).
- GMI's recurring savings come from its January 2026 report (middle of each reported range, from `reference/gmi_reported_savings.csv`); an area with no figure gets no default rate.

## Checks that run on every build

Ranges are ordered (forecast and backtest); actuals add up to controllable purchases in every year; every area has nine actual and six forecast years; every area is scored against the plan for FY2026 and FY2027; the kept model is no worse than naive on the rolling backtest; the published ranges cover about their nominal share (warning). Tests prove that no forecast changes when a later actual or the plan changes, that the published forecasts do not depend on the backtest settings, and that the scoring formulas are correct (`tests/test_forecast.py`).

## Sources, and how far each was verified

Search summaries and abstracts were read; the full texts were **not** opened for any of them, and I could not retrieve the book's own page on bootstrapped prediction intervals ([fpp3, section 5.5](https://otexts.com/fpp3/prediction-intervals.html), cited by an R package as the source of the method). No study of interval coverage on series this short was found, so the "too narrow" finding rests on this project's own backtest, not on a published benchmark.

- Hyndman and Athanasopoulos, *Forecasting: Principles and Practice*, 3rd ed.: <https://otexts.com/fpp3/>; summary read: [SAS blog on measuring forecast accuracy](https://blogs.sas.com/content/forecasting/2016/03/18/rob-hyndman-measuring-forecast-accuracy).
- Cerqueira, Torgo and Mozetič (2020), "Evaluating time series forecasting models: an empirical study on performance estimation methods", *Machine Learning* 109: 1997-2028: <https://web3.arxiv.org/abs/1905.11744>.
- Hyndman and Koehler (2006), "Another look at measures of forecast accuracy", *International Journal of Forecasting* 22(4): 679-688: <https://www.doi.org/10.1016/J.IJFORECAST.2006.03.001>.
- Gneiting and Raftery (2007), "Strictly proper scoring rules, prediction, and estimation", *Journal of the American Statistical Association* (DOI 10.1198/016214506000001437): <https://apps.dtic.mil/sti/html/tr/ADA459827/index.html> (the 2004 technical report version).
- Clemen (1989), "Combining forecasts: a review and annotated bibliography", *International Journal of Forecasting*: <https://people.duke.edu/~clemen/bio/Published%20Papers/13.CombiningReview-Clemen-IJOF-89.pdf>.
- Wang, Hyndman, Li and Kang (2022), "Forecast combinations: an over 50-year review": <https://arxiv.org/pdf/2205.04216>.
- M4 competition results and commentary (SAS): <https://blogs.sas.com/content/forecasting/2020/01/08/m4-forecasting-competition-results-and-commentary>.
- "Conformal prediction for time series" (arXiv 2010.09107): <https://arxiv.org/pdf/2010.09107>.
- Harvey, Leybourne and Newbold (1997), *International Journal of Forecasting* 13(2): 281-291, and the later small-sample work "Forecast evaluation tests and negative long-run variance estimates in small samples": <https://eprints.nottingham.ac.uk/43017>.

## Rebuild

`make build` rebuilds the tables with the rest of the database (about 5 seconds for the forecasts and the backtest). Same seed, same output.
