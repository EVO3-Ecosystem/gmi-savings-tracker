"""Baseline forecasts and evidence-based savings rates for the Calculator.

Forecast: for each focus area (and the rest of controllable purchases), annual actual spending FY2017-FY2025
from the operating budget. Two candidate models are compared on a backtest (fit FY2017-FY2022, predict
FY2023-FY2025) and the more accurate one is kept:
  * log-linear trend (constant growth rate, ordinary least squares on log spending)
  * naive (last actual value, no growth)
  * drift (last actual value growing at the average yearly rate)
Prediction intervals come from 4,000 bootstrap paths (resampled residuals for the trend, resampled yearly changes
for naive and drift), so they widen with the horizon. FY2026 (working budget) and FY2027 (Legislative Appropriation) are kept alongside as
the state's own plan, for comparison, not used to fit.

Savings rates: the default for each area is the recurring saving GMI itself reported for that area in its
January 2026 report, divided by the area's FY2025 actual spending. Areas with no GMI figure get no default.
General Fund share: each agency's FY2025 General Fund share, weighted by its spending in the area.
"""
import numpy as np
import pandas as pd

A0, A1, H1 = 2017, 2025, 2031
OTHER = "Other controllable purchases"
# GMI's recurring savings by area (Joint Chairmen's Report, Jan 26, 2026), middle of each range
GMI = {"Fleet & fuel": (0.8e6 + 1.3e6, "fuel and maintenance $0.8M + maintenance vendors $1.3M"),
       "Telecom": (0.5e6 + 2.2e6 + 1.55e6, "phone lines $0.5M + plan catalog $2.1-2.3M + copper lines $1.4-1.7M"),
       "IT hardware, software & services": (1.5e6 + 1.5e6 + 1.9e6, "laptop refresh $1.5M + specifications $1.5M + pricing $1.9M"),
       "Print, copy & mail": (0.8e6, "shipping contract $0.8M"),
       OTHER: (18e6, "contract renegotiation $18M year over year")}


def _fit(y, x):
    b, a = np.polyfit(x, np.log(y), 1)
    return a, b


def series(f_code, f_scope):
    a = f_code.groupby(["area", "fiscal_year", "stage"]).spend.sum().reset_index()
    c = f_scope[f_scope.scope == "Controllable purchases"].groupby(["fiscal_year", "stage"]).budget.sum().reset_index()
    tot = a.groupby(["fiscal_year", "stage"]).spend.sum().reset_index()
    o = c.merge(tot, on=["fiscal_year", "stage"], how="left").fillna(0)
    o = pd.DataFrame({"area": OTHER, "fiscal_year": o.fiscal_year, "stage": o.stage, "spend": o.budget - o.spend})
    return pd.concat([a, o], ignore_index=True)


def build(f_code, f_scope, f_fund, seed=11):
    rng = np.random.default_rng(seed)
    s = series(f_code, f_scope)
    rows, meta = [], []
    for area, g in s.groupby("area"):
        act = g[(g.stage == "Actual") & g.fiscal_year.between(A0, A1)].set_index("fiscal_year").spend.sort_index()
        plan = g[g.stage != "Actual"].set_index("fiscal_year").spend
        x, y = act.index.values.astype(float), act.values
        # backtest: fit through FY2022, predict FY2023-FY2025
        tr, te = x <= 2022, x > 2022
        a, b = _fit(y[tr], x[tr])
        mape_trend = float(np.mean(np.abs(np.exp(a + b * x[te]) - y[te]) / y[te]))
        mape_naive = float(np.mean(np.abs(y[tr][-1] - y[te]) / y[te]))
        d_tr = np.diff(np.log(y[tr])).mean()
        mape_drift = float(np.mean(np.abs(y[tr][-1] * np.exp(d_tr * (x[te] - x[tr][-1])) - y[te]) / y[te]))
        scores = {"Log-linear trend": mape_trend, "Naive (last actual)": mape_naive, "Drift (average yearly growth)": mape_drift}
        method = min(scores, key=scores.get)
        dl = np.diff(np.log(y)); drift = dl.mean(); shocks = dl - drift
        a, b = _fit(y, x)
        res = np.log(y) - (a + b * x)
        fy = np.arange(A1 + 1, H1 + 1)
        sims = np.empty((4000, len(fy)))
        for i in range(4000):  # residual bootstrap: refit on resampled data, then add a random walk of residuals
            yb = np.exp(a + b * x + rng.choice(res, len(x)))
            ab, bb = _fit(yb, x)
            if method.startswith("Naive"):
                level = np.log(y[-1]) + np.cumsum(rng.choice(shocks, len(fy)))
            elif method.startswith("Drift"):
                level = np.log(y[-1]) + np.cumsum(drift + rng.choice(shocks, len(fy)))
            else:
                level = ab + bb * fy + rng.choice(res, len(fy)) * np.sqrt(np.arange(1, len(fy) + 1)) / np.sqrt(2)
            sims[i] = np.exp(level)
        p10, p50, p90 = np.percentile(sims, [10, 50, 90], axis=0)
        for yr, v in act.items():
            rows.append({"area": area, "fiscal_year": int(yr), "kind": "Actual", "value": v, "p10": None, "p50": None, "p90": None, "plan": None})
        for k, yr in enumerate(fy):
            rows.append({"area": area, "fiscal_year": int(yr), "kind": "Forecast", "value": None, "p10": p10[k], "p50": p50[k], "p90": p90[k],
                         "plan": plan.get(yr)})
        base = float(act.get(A1))
        rep, note = GMI.get(area, (None, "GMI reported no recurring saving for this area"))
        meta.append({"area": area, "method": method, "growth": float(np.exp(b) - 1), "backtest_mape": scores[method],
                     "trend_mape": mape_trend, "naive_mape": mape_naive, "drift_mape": mape_drift, "baseline_fy2025": base, "gmi_recurring": rep,
                     "gmi_rate": rep / base if rep else None, "gmi_note": note})
    f = pd.DataFrame(rows)
    m = pd.DataFrame(meta)
    # General Fund share by area: agency GF share weighted by the agency's FY2025 spending in the area
    fu = f_fund[f_fund.fiscal_year == A1]
    gf = (fu[fu.fund_type_name.str.contains("General", case=False)].groupby("agency_code").budget.sum() / fu.groupby("agency_code").budget.sum()).fillna(0)
    ag = f_code[f_code.fiscal_year == A1].groupby(["area", "agency_code"]).spend.sum().reset_index()
    ag["gf"] = ag.agency_code.map(gf).fillna(0)
    share = ag.groupby("area").apply(lambda d: (d.spend * d.gf).sum() / d.spend.sum() if d.spend.sum() else 0, include_groups=False)
    allgf = float((fu[fu.fund_type_name.str.contains("General", case=False)].budget.sum()) / fu.budget.sum())
    m["gf_share"] = m.area.map(share).fillna(allgf)
    for c in ("value", "p10", "p50", "p90", "plan"):
        f[c] = pd.to_numeric(f[c]).round(0)
    for c in ("growth", "backtest_mape", "trend_mape", "naive_mape", "drift_mape", "gmi_rate", "gf_share"):
        m[c] = pd.to_numeric(m[c]).round(5)
    return f, m
