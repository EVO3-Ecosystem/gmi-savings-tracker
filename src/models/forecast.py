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
METHODS = (TREND, NAIVE, DRIFT)  # the models a forecast can be kept from
COMBINATION = "Equal-weight combination"  # scored in the backtest only, to show whether averaging earns a place; never kept


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


def interval_score(lo, hi, outcome, alpha=0.2):
    """Interval score of a central (1 - alpha) range (Gneiting and Raftery 2007): its width plus a penalty of 2/alpha
    times how far the outcome falls outside it. Lower is better; it rewards narrow ranges that still cover."""
    return (hi - lo) + (2 / alpha) * np.maximum(lo - outcome, 0) + (2 / alpha) * np.maximum(outcome - hi, 0)


def backtest(s, cfg=None):
    """Rolling-origin backtest: every method, every area, origins from the smallest training window to the last actual.

    One row per area, method, origin and horizon (forecast year = origin + horizon, up to `rolling_score_through_fy`).
    A forecast year up to the last actual is scored against actual spending (target = "actual"); a later year (FY2026
    working budget, FY2027 legislative appropriation) is scored against the State's plan (target = "plan"), which is
    a budget, not an outcome. Forecasts never use a year after their origin, and never use the plan.
    mase = absolute error / mean absolute one-step naive error inside that origin's training window.
    p10, p50, p90 = the bootstrap range simulated at that origin; covered = the outcome fell inside p10-p90 (nominal
    80%); interval_score = the interval score of that range in dollars.
    """
    cfg = (cfg or assumptions())["forecast"]
    a0, a1, min_train, max_h = cfg["first_actual_fy"], cfg["last_actual_fy"], cfg["rolling_min_train_years"], cfg["rolling_max_horizon"]
    through, n_paths = cfg["rolling_score_through_fy"], cfg["backtest_bootstrap_paths"]
    rng = np.random.default_rng(cfg["seed"] + 1)  # separate stream: the published forecasts do not depend on the backtest
    rows = []
    for area, g in s.groupby("area"):
        act = _actuals(g, a0, a1)
        plan = g[g.stage != "Actual"].set_index("fiscal_year").spend
        x, y = act.index.values.astype(float), act.values
        for origin in range(a0 + min_train - 1, a1 + 1):
            tr = x <= origin
            scale = float(np.mean(np.abs(np.diff(y[tr]))))
            years = np.arange(origin + 1, min(origin + max_h, through) + 1)
            sims = {m: simulate(m, x[tr], y[tr], years, n_paths, rng) for m in METHODS}
            points = {m: predict(m, x[tr], y[tr], years) for m in METHODS}
            sims[COMBINATION] = np.mean([sims[m] for m in METHODS], axis=0)  # path by path, so its range is the range of the average
            points[COMBINATION] = np.mean([points[m] for m in METHODS], axis=0)
            for m in (*METHODS, COMBINATION):
                p10, p50, p90 = np.percentile(sims[m], [10, 50, 90], axis=0)
                f = points[m]
                for k, fy in enumerate(years):
                    fy = int(fy)
                    if fy <= a1:
                        target, outcome = "actual", float(y[x == fy][0])
                    elif fy in plan.index:
                        target, outcome = "plan", float(plan.loc[fy])
                    else:
                        continue
                    err = abs(float(f[k]) - outcome)
                    rows.append({"area": area, "method": m, "origin_fy": origin, "horizon": fy - origin, "forecast_fy": fy, "target": target,
                                 "outcome": outcome, "forecast": float(f[k]), "abs_error": err, "ape": err / outcome,
                                 "mase": err / scale if scale > 0 else None, "p10": p10[k], "p50": p50[k], "p90": p90[k],
                                 "covered": bool(p10[k] <= outcome <= p90[k]), "interval_score": float(interval_score(p10[k], p90[k], outcome))})
    out = pd.DataFrame(rows)
    for c in ("outcome", "forecast", "abs_error", "p10", "p50", "p90", "interval_score"):
        out[c] = out[c].round(0)
    for c in ("ape", "mase"):
        out[c] = pd.to_numeric(out[c]).round(5)
    return out


def calibration(bt, model, alpha=0.2):
    """How far the published p10-p90 ranges are from their nominal 80%, measured on the rolling backtest against actuals,
    for each area's chosen model, plus the pooled factor that would have made them cover 80%.

    widen_by: the (1 - alpha) quantile (with the usual finite-sample rank correction) of how many times wider than its
    own range each outcome's miss was, on the log scale around the median; 1 = already calibrated, above 1 = too narrow.
    It is measured in-sample on a handful of points, so it is a size of the problem, not a validated correction.
    """
    chosen = bt.merge(model[["area", "method"]], on=["area", "method"])
    chosen = chosen[chosen.target == "actual"].copy()
    lo, mid, hi, out = (np.log(chosen[c].astype(float)) for c in ("p10", "p50", "p90", "outcome"))
    up = (hi - mid).clip(lower=1e-9)
    down = (mid - lo).clip(lower=1e-9)
    chosen["miss"] = np.where(out >= mid, (out - mid) / up, (mid - out) / down)
    n = len(chosen)
    k = float(np.sort(chosen.miss.values)[min(n - 1, int(np.ceil((n + 1) * (1 - alpha))) - 1)]) if n else float("nan")
    rows = [{"area": a, "method": g.method.iloc[0], "scored": len(g), "covered_share": float(g.covered.mean()), "nominal": 1 - alpha,
             "widen_by": k} for a, g in chosen.groupby("area")]
    rows.append({"area": "All areas", "method": "chosen model of each area", "scored": n, "covered_share": float(chosen.covered.mean()) if n else None,
                 "nominal": 1 - alpha, "widen_by": k})
    out_df = pd.DataFrame(rows)
    for c in ("covered_share", "widen_by"):
        out_df[c] = pd.to_numeric(out_df[c]).round(4)
    return out_df


def simulate(method, x, y, fy, n_paths, rng):
    """Bootstrap paths of spending in the years `fy` from one training window: array (n_paths, len(fy)).

    Residual bootstrap: refit on resampled data, then add a random walk of resampled residuals (trend) or resampled
    yearly changes (naive, drift), so ranges widen with the horizon.
    """
    dl = np.diff(np.log(y))
    drift = dl.mean()
    shocks = dl - drift
    a, b = _fit(y, x)
    res = np.log(y) - (a + b * x)
    fy = np.asarray(fy)
    sims = np.empty((n_paths, len(fy)))
    for i in range(n_paths):
        yb = np.exp(a + b * x + rng.choice(res, len(x)))
        ab, bb = _fit(yb, x)
        if method == NAIVE:
            level = np.log(y[-1]) + np.cumsum(rng.choice(shocks, len(fy)))
        elif method == DRIFT:
            level = np.log(y[-1]) + np.cumsum(drift + rng.choice(shocks, len(fy)))
        else:
            level = ab + bb * fy + rng.choice(res, len(fy)) * np.sqrt(np.arange(1, len(fy) + 1)) / np.sqrt(2)
        sims[i] = np.exp(level)
    return sims


def choose(area_scores, rule, legacy_mape):
    """The model kept for one area. `rolling_origin_mase`: lowest mean MASE over the rolling origins (a tie goes to the
    naive baseline); `legacy_single_split`: lowest MAPE on the single fit-through-FY2022 split (the legacy rule)."""
    if rule == "legacy_single_split":
        return min(legacy_mape, key=legacy_mape.get)
    order = (NAIVE, TREND, DRIFT)  # strict '<' below, so the first listed wins a tie
    best = order[0]
    for m in order[1:]:
        if area_scores[m] < area_scores[best]:
            best = m
    return best


def build(f_code, f_scope, f_fund, cfg=None, reference=None):
    cfg = cfg or assumptions()
    p = cfg["forecast"]
    a0, a1, h1, n_paths, fit_end = p["first_actual_fy"], p["last_actual_fy"], p["horizon_fy"], p["bootstrap_paths"], p["selection_fit_end_fy"]
    gmi = gmi_recurring(cfg, reference)
    rng = np.random.default_rng(p["seed"])
    s = series(f_code, f_scope)
    bt = backtest(s, cfg)
    rolling = bt[bt.target == "actual"].groupby(["area", "method"]).mase.mean()
    rows, meta = [], []
    for area, g in s.groupby("area"):
        act = _actuals(g, a0, a1)
        plan = g[g.stage != "Actual"].set_index("fiscal_year").spend
        x, y = act.index.values.astype(float), act.values
        # single split (legacy): fit through the cut-off year, score the years after it
        tr, te = x <= fit_end, x > fit_end
        mape = {m: float(np.mean(np.abs(predict(m, x[tr], y[tr], x[te]) - y[te]) / y[te])) for m in METHODS}
        method = choose({m: rolling[(area, m)] for m in METHODS}, p.get("selection", "rolling_origin_mase"), mape)
        a, b = _fit(y, x)
        fy = np.arange(a1 + 1, h1 + 1)
        p10, p50, p90 = np.percentile(simulate(method, x, y, fy, n_paths, rng), [10, 50, 90], axis=0)
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
    return f, m, bt


def write(con, cfg=None):
    """Read the marts, build the three tables and store them in the mart schema."""
    f_code, f_scope, f_fund = (con.execute(f"SELECT * FROM mart.{t}").df() for t in ("f_code", "f_scope", "f_fund"))
    f, m, bt = build(f_code, f_scope, f_fund, cfg)
    cal = calibration(bt, m)
    for name, df in (("f_forecast", f), ("d_forecast_model", m), ("d_forecast_backtest", bt), ("d_forecast_calibration", cal)):
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE mart.{name} AS SELECT * FROM _df")
        con.unregister("_df")
    return {"f_forecast": len(f), "d_forecast_model": len(m), "d_forecast_backtest": len(bt), "d_forecast_calibration": len(cal)}
