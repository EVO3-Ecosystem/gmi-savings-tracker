"""Detector backtest (src/models/backtest.py) on constructed cases: the flags are exactly detect()'s, nothing after the next
year is read, cohorts are counted and followed as defined. No data/ needed."""
import pandas as pd

from src.models import backtest as B
from src.models import opportunities as O

TEN = [f"D{i:02d}" for i in range(1, 11)]


def _world():
    """Peer gap on code 0801 every year (D10 spends ten times its peers); D06 grows fast on 0902 from FY2022;
    vendor V is paid by twelve agencies every year; areas get tail vendors."""
    rows = []
    for fy in range(2019, 2026):
        rows += [(a, "0801", fy, 1_000_000.0) for a in TEN[:-1]] + [("D10", "0801", fy, 10_000_000.0 if fy < 2024 else 2_000_000.0)]
        rows += [(a, "0902", fy, 2_000_000.0) for a in TEN[:5]] + [("D06", "0902", fy, 2_000_000.0 * (2 ** max(0, fy - 2021)))]
    budget = pd.DataFrame([{"fiscal_year": fy, "stage": "Actual", "agency_code": a, "object_name": "Obj", "code": c,
                            "comptroller_subobject_name": f"Code {c}", "controllable": True, "area": "Fleet & fuel", "budget": b} for a, c, fy, b in rows])
    ay = pd.DataFrame([{"agency_code": a, "agency": f"Agency {a}", "fiscal_year": fy, "fte": 100.0} for a in TEN for fy in range(2019, 2026)])
    pay = []
    for fy in range(2019, 2026):
        pay += [(a, "V", "Telecom", 600_000.0, fy) for a in TEN + ["A11", "A12"]]
        pay += [("A01", f"S{i}", "Telecom", 200_000.0, fy) for i in range(20)]
    payments = pd.DataFrame([{"fiscal_year": fy, "agency_code": a, "vendor": v, "area": ar, "amount": m, "is_government": False, "passthrough": False}
                             for a, v, ar, m, fy in pay])
    return budget, ay, payments


def _cfg():
    cfg = O.assumptions()
    cfg["growth"]["min_base_budget"] = 0
    return cfg


def test_screen_flags_are_exactly_the_detectors_findings():
    budget, ay, pay = _world()
    for t in B.AS_OF:
        cfg = B._cfg(_cfg(), t)
        s, d = B.screen(budget, ay, pay, cfg), O.detect(budget, ay, pay, cfg)
        flagged = pd.concat([s["Peer gap"], s["Growth above trend"]]).query("flag")
        assert set(zip(flagged.agency_code, flagged.code)) == set(zip(d.agency_code.dropna(), d[d.agency_code.notna()].spending_code.str.extract(r"\((\w+)\)$")[0]))
        assert set(s["Tail spend"].query("flag").area) == set(d[d.detector == "Tail spend"].area)
        assert set(s["Leverage"].query("flag").vendor.str.title()) == set(d[d.detector == "Leverage"].spending_code)


def test_rows_cohorts_and_follow_up():
    budget, ay, pay = _world()
    r = B.run(budget, ay, pay, _cfg())
    assert list(r.columns) == B.COLUMNS and len(r) == len(B.DETECTORS) * len(B.AS_OF) * 2
    pg = r[(r.detector == "Peer gap") & (r.cohort == "Flagged")].set_index("as_of_fy")
    assert (pg.units == 1).all()  # D10 only
    assert pg.loc[2022, "flagged_next"] == 1 and pg.loc[2023, "spend_next"] == 2_000_000.0 and pg.loc[2023, "pooled_change"] == -0.8
    lv = r[(r.detector == "Leverage") & (r.cohort == "Flagged")]
    assert (lv.units == 1).all() and (lv.flagged_next_share == 1).all() and (lv.pooled_change == 0).all()
    tail = r[(r.detector == "Tail spend") & (r.cohort == "Flagged")]
    assert (tail.units == 1).all() and (tail.spend_as_of == 11 * 200_000.0).all()  # 21 vendors in Telecom; the ten largest (V and nine S) left out


def test_only_data_up_to_the_next_year_is_read():
    budget, ay, pay = _world()
    base = B.run(budget, ay, pay, _cfg(), as_of=(2022,))
    later = budget.fiscal_year > 2023
    noisy = budget.assign(budget=budget.budget.where(~later, budget.budget * 50))
    pd.testing.assert_frame_equal(base, B.run(noisy, ay, pay.assign(amount=pay.amount.where(pay.fiscal_year <= 2023, 1e9)), _cfg(), as_of=(2022,)))
