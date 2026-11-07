"""Baseline forecasts and evidence-based savings rates for the Calculator (port of legacy/gst/scripts/forecast.py).

For each focus area (and the rest of controllable purchases), annual actual spending FY2017-FY2025 from the operating
budget. Three candidate models, each compared with the naive baseline:
  * log-linear trend (constant growth rate, ordinary least squares on log spending)
  * naive (last actual value, no growth)
  * drift (last actual value growing at the average yearly rate)
The kept model is chosen exactly as the legacy pipeline did (fit through FY2022, score FY2023-FY2025, lowest MAPE), so
results stay comparable. Ranges come from seeded bootstrap paths (resampled residuals for the trend, resampled yearly
changes for naive and drift) and widen with the horizon. FY2026 and FY2027 (the State's own plan) are kept alongside,
never used to fit.

Added over the legacy version, following forecast-evaluation practice (Hyndman and Athanasopoulos): a rolling-origin
backtest (`backtest`) that scores every model at several origins and horizons against the naive baseline, with MASE
whose scale is recomputed from each origin's own training history so no future value enters it.

Assumptions (years, paths, seed, GMI savings) live in config/assumptions.yaml.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
OTHER = "Other controllable purchases"
TREND, NAIVE, DRIFT = "Log-linear trend", "Naive (last actual)", "Drift (average yearly growth)"
METHODS = (TREND, NAIVE, DRIFT)


def assumptions():
    return yaml.safe_load((ROOT / "config" / "assumptions.yaml").read_text())


def gmi_recurring(cfg=None, reference=None):
    """area -> (recurring savings in dollars, note): the middle of each reported range, summed over the listed saving IDs."""
    cfg = cfg or assumptions()
    ref = reference if reference is not None else pd.read_csv(ROOT / "reference" / "gmi_reported_savings.csv")
    ref = ref.set_index("saving_id")
    out = {}
    for area, spec in cfg["gmi_recurring"].items():
        mid = (ref.loc[spec["savings"], "reported_low"] + ref.loc[spec["savings"], "reported_high"]) / 2
        out[area] = (float(mid.sum()), spec["note"])
    return out


def _fit(y, x):
    b, a = np.polyfit(x, np.log(y), 1)
    return a, b


def predict(method, x_train, y_train, x_new):
    """Forecast y at the years x_new from a training window."""
    x_new = np.asarray(x_new, dtype=float)
    if method == TREND:
        a, b = _fit(y_train, x_train)
        return np.exp(a + b * x_new)
    if method == NAIVE:
        return np.full(len(x_new), float(y_train[-1]))
    drift = np.diff(np.log(y_train)).mean()
    return y_train[-1] * np.exp(drift * (x_new - x_train[-1]))


def series(f_code, f_scope):
    a = f_code.groupby(["area", "fiscal_year", "stage"]).spend.sum().reset_index()
    c = f_scope[f_scope.scope == "Controllable purchases"].groupby(["fiscal_year", "stage"]).budget.sum().reset_index()
    tot = a.groupby(["fiscal_year", "stage"]).spend.sum().reset_index()
    o = c.merge(tot, on=["fiscal_year", "stage"], how="left").fillna(0)
    o = pd.DataFrame({"area": OTHER, "fiscal_year": o.fiscal_year, "stage": o.stage, "spend": o.budget - o.spend})
    return pd.concat([a, o], ignore_index=True)


def _actuals(g, a0, a1):
    return g[(g.stage == "Actual") & g.fiscal_year.between(a0, a1)].set_index("fiscal_year").spend.sort_index()


def backtest(s, cfg=None):
    """Rolling-origin backtest: every method, every area, origins from the smallest training window to the last actual.

    One row per area, method, origin and horizon (forecast year = origin + horizon, never past the last actual).
    mase = absolute error / mean absolute one-step naive error inside that origin's training window.
    """
    cfg = (cfg or assumptions())["forecast"]
    a0, a1, min_train, max_h = cfg["first_actual_fy"], cfg["last_actual_fy"], cfg["rolling_min_train_years"], cfg["rolling_max_horizon"]
    rows = []
    for area, g in s.groupby("area"):
        act = _actuals(g, a0, a1)
        x, y = act.index.values.astype(float), act.values
        for origin in range(a0 + min_train - 1, a1):
            tr = x <= origin
            scale = float(np.mean(np.abs(np.diff(y[tr]))))
            for h in range(1, max_h + 1):
                if origin + h > a1:
                    break
                te = x == origin + h
                actual = float(y[te][0])
                for m in METHODS:
                    f = float(predict(m, x[tr], y[tr], x[te])[0])
                    err = abs(f - actual)
                    rows.append({"area": area, "method": m, "origin_fy": origin, "horizon": h, "forecast_fy": origin + h,
                                 "actual": actual, "forecast": f, "abs_error": err, "ape": err / actual,
                                 "mase": err / scale if scale > 0 else None})
    out = pd.DataFrame(rows)
    for c in ("actual", "forecast", "abs_error"):
        out[c] = out[c].round(0)
    for c in ("ape", "mase"):
        out[c] = pd.to_numeric(out[c]).round(5)
    return out


def build(f_code, f_scope, f_fund, cfg=None, reference=None):
    cfg = cfg or assumptions()
    p = cfg["forecast"]
    a0, a1, h1, n_paths, fit_end = p["first_actual_fy"], p["last_actual_fy"], p["horizon_fy"], p["bootstrap_paths"], p["selection_fit_end_fy"]
    gmi = gmi_recurring(cfg, reference)
    rng = np.random.default_rng(p["seed"])
    s = series(f_code, f_scope)
    rows, meta = [], []
    for area, g in s.groupby("area"):
        act = _actuals(g, a0, a1)
        plan = g[g.stage != "Actual"].set_index("fiscal_year").spend
        x, y = act.index.values.astype(float), act.values
        # method choice: fit through the cut-off year, score the years after it
        tr, te = x <= fit_end, x > fit_end
        mape = {m: float(np.mean(np.abs(predict(m, x[tr], y[tr], x[te]) - y[te]) / y[te])) for m in METHODS}
        method = min(mape, key=mape.get)
        dl = np.diff(np.log(y))
        drift = dl.mean()
        shocks = dl - drift
        a, b = _fit(y, x)
        res = np.log(y) - (a + b * x)
        fy = np.arange(a1 + 1, h1 + 1)
        sims = np.empty((n_paths, len(fy)))
        for i in range(n_paths):  # residual bootstrap: refit on resampled data, then add a random walk of residuals
            yb = np.exp(a + b * x + rng.choice(res, len(x)))
            ab, bb = _fit(yb, x)
            if method == NAIVE:
                level = np.log(y[-1]) + np.cumsum(rng.choice(shocks, len(fy)))
            elif method == DRIFT:
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
        base = float(act.get(a1))
        rep, note = gmi.get(area, (None, "GMI reported no recurring saving for this area"))
        meta.append({"area": area, "method": method, "growth": float(np.exp(b) - 1), "backtest_mape": mape[method],
                     "trend_mape": mape[TREND], "naive_mape": mape[NAIVE], "drift_mape": mape[DRIFT], "baseline_fy2025": base,
                     "gmi_recurring": rep, "gmi_rate": rep / base if rep else None, "gmi_note": note})
    f = pd.DataFrame(rows)
    m = pd.DataFrame(meta)
    # General Fund share by area: agency GF share weighted by the agency's FY2025 spending in the area
    fu = f_fund[f_fund.fiscal_year == a1]
    is_gf = fu.fund_type_name.str.contains("General", case=False)
    gf = (fu[is_gf].groupby("agency_code").budget.sum() / fu.groupby("agency_code").budget.sum()).fillna(0)
    ag = f_code[f_code.fiscal_year == a1].groupby(["area", "agency_code"]).spend.sum().reset_index()
    ag["gf"] = ag.agency_code.map(gf).fillna(0)
    share = ag.groupby("area").apply(lambda d: (d.spend * d.gf).sum() / d.spend.sum() if d.spend.sum() else 0, include_groups=False)
    allgf = float(fu[is_gf].budget.sum() / fu.budget.sum())
    m["gf_share"] = m.area.map(share).fillna(allgf)
    for c in ("value", "p10", "p50", "p90", "plan"):
        f[c] = pd.to_numeric(f[c]).round(0)
    for c in ("growth", "backtest_mape", "trend_mape", "naive_mape", "drift_mape", "gmi_rate", "gf_share"):
        m[c] = pd.to_numeric(m[c]).round(5)
    return f, m, backtest(s, cfg)


def write(con, cfg=None):
    """Read the marts, build the three tables and store them in the mart schema."""
    f_code, f_scope, f_fund = (con.execute(f"SELECT * FROM mart.{t}").df() for t in ("f_code", "f_scope", "f_fund"))
    f, m, bt = build(f_code, f_scope, f_fund, cfg)
    for name, df in (("f_forecast", f), ("d_forecast_model", m), ("d_forecast_backtest", bt)):
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE mart.{name} AS SELECT * FROM _df")
        con.unregister("_df")
    return {"f_forecast": len(f), "d_forecast_model": len(m), "d_forecast_backtest": len(bt)}
