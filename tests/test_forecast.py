"""Forecast models on small synthetic series (no data/ needed)."""
import numpy as np
import pandas as pd
import pytest

from src.models import forecast as F

YEARS = list(range(2017, 2028))


def _stage(y):
    return "Actual" if y <= 2025 else ("Working budget" if y == 2026 else "Legislative appropriation")


def _inputs(growth_a=1.05, level_a=1_000_000.0, shock_b=(1.0, 1.3, 0.8, 1.2, 0.9, 1.1, 1.4, 0.7, 1.2, 1.0, 1.0)):
    """Two areas: A grows exactly 5% a year; B is noisy. Plus controllable purchases for the 'Other' series."""
    code = []
    for i, y in enumerate(YEARS):
        code.append({"fiscal_year": y, "stage": _stage(y), "agency_code": "D01", "area": "A", "spend": level_a * growth_a ** i})
        code.append({"fiscal_year": y, "stage": _stage(y), "agency_code": "D02", "area": "B", "spend": 500_000.0 * shock_b[i]})
    scope = [{"fiscal_year": y, "stage": _stage(y), "agency_code": "D01", "scope": "Controllable purchases", "budget": 9_000_000.0 * 1.02 ** i}
             for i, y in enumerate(YEARS)]
    fund = [{"fiscal_year": y, "stage": _stage(y), "agency_code": a, "fund_type_name": ft, "budget": b}
            for y in YEARS for a, ft, b in (("D01", "General Fund", 60.0), ("D01", "Federal Fund", 40.0), ("D02", "General Fund", 10.0), ("D02", "Special Fund", 90.0))]
    return pd.DataFrame(code), pd.DataFrame(scope), pd.DataFrame(fund)


@pytest.fixture(scope="module")
def built():
    f_code, f_scope, f_fund = _inputs()
    return F.build(f_code, f_scope, f_fund)


def test_gmi_savings_come_from_the_reference_csv_and_match_the_legacy_constants():
    g = F.gmi_recurring()
    assert g["Fleet & fuel"][0] == 0.8e6 + 1.3e6
    assert g["Telecom"][0] == 0.5e6 + 2.2e6 + 1.55e6  # midpoints of S11 and S12
    assert g["IT hardware, software & services"][0] == 1.5e6 + 1.5e6 + 1.9e6
    assert g["Print, copy & mail"][0] == 0.8e6
    assert g[F.OTHER][0] == 18e6


def test_predict_formulas():
    x = np.arange(2017.0, 2023.0)
    y = 100 * 1.1 ** (x - 2017)
    new = np.array([2023.0, 2024.0])
    assert F.predict(F.NAIVE, x, y, new).tolist() == [y[-1], y[-1]]
    assert np.allclose(F.predict(F.TREND, x, y, new), 100 * 1.1 ** (new - 2017))
    assert np.allclose(F.predict(F.DRIFT, x, y, new), 100 * 1.1 ** (new - 2017))


def test_shapes_years_and_plan(built):
    f, m, bt = built
    assert sorted(f.area.unique()) == ["A", "B", F.OTHER] and len(m) == 3
    for _area, g in f.groupby("area"):
        assert list(g[g.kind == "Actual"].fiscal_year) == list(range(2017, 2026))
        fc = g[g.kind == "Forecast"]
        assert list(fc.fiscal_year) == list(range(2026, 2032))
        assert fc.plan.notna().tolist() == [True, True, False, False, False, False]  # the State's plan only for FY2026-27


def test_ranges_are_ordered_and_widen_with_the_horizon(built):
    f, _, _ = built
    fc = f[f.kind == "Forecast"]
    assert (fc.p10 <= fc.p50).all() and (fc.p50 <= fc.p90).all()
    for area, g in fc.groupby("area"):
        width = (g.p90 - g.p10).values
        assert (np.diff(width) >= -1e-6).all(), area  # never narrows
    noisy = (fc[fc.area == "B"].p90 - fc[fc.area == "B"].p10).values
    assert noisy[-1] > noisy[0]  # a noisy series is less certain further out (an exactly exponential one has no noise to resample)


def test_same_seed_same_result_and_different_seed_differs():
    f_code, f_scope, f_fund = _inputs()
    a = F.build(f_code, f_scope, f_fund)[0]
    b = F.build(f_code, f_scope, f_fund)[0]
    pd.testing.assert_frame_equal(a, b)
    cfg = F.assumptions()
    cfg["forecast"]["seed"] = 12
    c = F.build(f_code, f_scope, f_fund, cfg)[0]
    assert not a.p50.dropna().equals(c.p50.dropna())


def test_method_choice_is_the_lowest_backtest_error(built):
    _, m, _ = built
    for r in m.itertuples():
        errs = {"Log-linear trend": r.trend_mape, "Naive (last actual)": r.naive_mape, "Drift (average yearly growth)": r.drift_mape}
        assert errs[r.method] == min(errs.values())
    a = m.set_index("area").loc["A"]
    assert a.method in ("Log-linear trend", "Drift (average yearly growth)")  # both fit exact growth; a tie at about zero error
    assert a.backtest_mape < 1e-4 and abs(a.growth - 0.05) < 1e-4  # exact 5% growth is recovered, and beats naive
    assert a.naive_mape > 0.05  # standing still misses 5% growth a year (about 9% over FY2023-FY2025)


def test_gmi_rate_is_savings_over_the_fy2025_baseline(built):
    _, m, _ = built
    o = m.set_index("area").loc[F.OTHER]
    assert o.gmi_recurring == 18e6 and o.gmi_rate == round(18e6 / o.baseline_fy2025, 5)
    assert pd.isna(m.set_index("area").loc["A"].gmi_rate)


def test_general_fund_share_is_weighted_by_agency_spend(built):
    _, m, _ = built
    s = m.set_index("area").gf_share
    assert s["A"] == 0.6 and s["B"] == 0.1


def test_rolling_backtest_has_one_row_per_area_method_origin_horizon(built):
    _, _, bt = built
    assert len(bt) == 3 * 3 * 14  # origins FY2021-FY2025 with horizons 3, 3, 3, 3, 2 (scored through FY2027)
    assert bt.forecast_fy.max() == 2027 and (bt.forecast_fy == bt.origin_fy + bt.horizon).all()
    assert set(bt.method) == set(F.METHODS)


def test_years_after_the_last_actual_are_scored_against_the_plan_and_labelled(built):
    _, _, bt = built
    assert set(bt[bt.forecast_fy <= 2025].target) == {"actual"}
    assert set(bt[bt.forecast_fy > 2025].target) == {"plan"} and set(bt[bt.forecast_fy > 2025].forecast_fy) == {2026, 2027}
    b = bt[(bt.area == "B") & (bt.method == F.NAIVE) & (bt.origin_fy == 2025) & (bt.horizon == 1)].iloc[0]
    assert b.target == "plan" and b.outcome == 500_000.0 * 1.0 and b.forecast == 500_000.0 * 1.2  # FY2026 plan vs the FY2025 actual
    fy27 = bt[(bt.area == "B") & (bt.method == F.NAIVE) & (bt.origin_fy == 2025) & (bt.horizon == 2)].iloc[0]
    assert fy27.outcome == 500_000.0 * 1.0 and fy27.abs_error == abs(fy27.forecast - fy27.outcome)


def test_forecasts_never_use_the_plan():
    f_code, f_scope, f_fund = _inputs()
    changed = f_code.copy()
    changed.loc[changed.fiscal_year >= 2026, "spend"] *= 50  # a wild State plan
    a, b = F.backtest(F.series(f_code, f_scope)), F.backtest(F.series(changed, f_scope))
    pd.testing.assert_series_equal(a.forecast, b.forecast)  # every forecast is unchanged
    plan = a.target == "plan"
    assert not a[plan].outcome.equals(b[plan].outcome)  # only the plan rows' outcomes (and errors) move
    pd.testing.assert_series_equal(a[~plan].abs_error, b[~plan].abs_error)


def test_mase_scale_comes_from_the_origins_own_training_history():
    s = pd.DataFrame({"area": "A", "fiscal_year": YEARS[:9], "stage": "Actual",
                      "spend": [100.0, 110.0, 105.0, 120.0, 130.0, 125.0, 140.0, 150.0, 160.0]})
    bt = F.backtest(s)
    r = bt[(bt.method == F.NAIVE) & (bt.origin_fy == 2021) & (bt.horizon == 1)].iloc[0]
    scale = np.mean(np.abs(np.diff([100.0, 110.0, 105.0, 120.0, 130.0])))  # FY2017-FY2021 only
    assert r.forecast == 130.0 and r.outcome == 125.0 and r.target == "actual" and r.mase == round(5.0 / scale, 5)


def test_rolling_backtest_never_uses_the_future():
    f_code, f_scope, f_fund = _inputs()
    s1 = F.series(f_code, f_scope)
    changed = f_code.copy()
    changed.loc[(changed.area == "B") & (changed.fiscal_year == 2025), "spend"] = 5e6  # a wild last actual
    s2 = F.series(changed, f_scope)
    a, b = F.backtest(s1), F.backtest(s2)
    key = (a.area == "B") & (a.forecast_fy <= 2024)  # nothing scored on or before FY2024 may depend on FY2025
    pd.testing.assert_frame_equal(a[key].reset_index(drop=True), b[key].reset_index(drop=True))
