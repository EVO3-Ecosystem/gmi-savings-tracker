"""Opportunity detectors and the bid list on small constructed cases (no data/ needed)."""
import pandas as pd
import pytest

from src.models import opportunities as O


def _budget(rows):
    """rows: (agency, code, fy, budget). Controllable actual spending."""
    return pd.DataFrame([{"fiscal_year": fy, "stage": "Actual", "agency_code": a, "object_name": "Obj", "code": code,
                          "comptroller_subobject_name": f"Code {code}", "controllable": True, "area": "Fleet & fuel", "budget": b}
                         for a, code, fy, b in rows])


def _agencies(codes, fte=100.0):
    return pd.DataFrame([{"agency_code": a, "agency": f"Agency {a}", "fiscal_year": fy, "fte": fte} for a in codes for fy in (2024, 2025)])


def _pay(rows):
    """rows: (agency, vendor, area, amount, fy, government). Payments to vendors."""
    return pd.DataFrame([{"fiscal_year": fy, "agency_code": a, "vendor": v, "area": area, "amount": amt, "is_government": gov, "passthrough": False}
                         for a, v, area, amt, fy, gov in rows])


NO_PAY = _pay([("A01", "X", None, 1.0, 2026, False)])
TEN = [f"D{i:02d}" for i in range(1, 11)]


def _peer_gap_case():
    rows = [(a, "0801", 2025, 1_000_000.0) for a in TEN[:-1]] + [("D10", "0801", 2025, 10_000_000.0)]
    return _budget(rows), _agencies(TEN)


def test_peer_gap_counts_only_the_excess_over_the_75th_percentile_and_caps_it():
    d = O.detect(*_peer_gap_case()[:2], NO_PAY)
    r = d[d.detector == "Peer gap"]
    assert list(r.agency_code) == ["D10"] and r.agency.iloc[0] == "Agency D10"
    # per position: 100,000 vs a 75th percentile of 10,000; the excess is $9M, 5-15% of it is $450k-$1.35M, capped at 3-10% of $10M
    assert r.low.iloc[0] == 300_000 and r.high.iloc[0] == 1_000_000 and r.likely.iloc[0] == 650_000
    assert "$100,000 per position vs $10,000 at the 75th percentile of 10 agencies" in r.evidence.iloc[0]
    assert r.spending_code.iloc[0] == "Code 0801 (0801)"


def test_peer_gap_needs_enough_agencies_positions_and_spending():
    budget, ay = _peer_gap_case()
    assert O.detect(budget[budget.agency_code.isin(TEN[:6] + ["D10"])], ay, NO_PAY).query("detector == 'Peer gap'").empty  # 7 agencies < 8
    assert O.detect(budget, _agencies(TEN, fte=40.0), NO_PAY).query("detector == 'Peer gap'").empty  # fewer than 50 positions
    small = budget.assign(budget=budget.budget / 100)
    assert O.detect(small, ay, NO_PAY).query("detector == 'Peer gap'").empty  # under $250k


def _growth_case(old=1_000_000.0):
    rows = [(a, "0902", 2022, 1_000_000.0) for a in TEN[:5]] + [("D06", "0902", 2022, old)]
    rows += [(a, "0902", 2025, 1_000_000.0) for a in TEN[:5]] + [("D06", "0902", 2025, 3_000_000.0)]
    return _budget(rows), _agencies(TEN)


def _legacy_cfg():
    cfg = O.assumptions()
    cfg["growth"]["min_base_budget"] = 0  # the constructed cases use small round bases; the default $1M minimum has its own test
    return cfg


def test_growth_counts_only_growth_above_the_states_pace():
    d = O.detect(*_growth_case()[:2], NO_PAY, _legacy_cfg())
    r = d[d.detector == "Growth above trend"]
    assert list(r.agency_code) == ["D06"]
    state = 8_000_000 / 6_000_000 - 1
    excess = 3_000_000 - 1_000_000 * (1 + state)
    assert r.low.iloc[0] == round(0.10 * excess) and r.high.iloc[0] == round(0.30 * excess)
    assert r.evidence.iloc[0] == f"grew +200% over FY2022-FY2025 vs {state:+.0%} statewide"


def test_a_minimum_base_removes_growth_from_a_tiny_starting_point():
    budget, ay = _growth_case(old=10_000.0)
    assert len(O.detect(budget, ay, NO_PAY, _legacy_cfg()).query("detector == 'Growth above trend'")) == 1  # legacy: any positive base
    assert O.detect(budget, ay, NO_PAY).query("detector == 'Growth above trend'").empty  # default: the prior year must exceed $1M
    cfg = O.assumptions()
    cfg["growth"]["min_base_budget"] = 100_000
    assert O.detect(budget, ay, NO_PAY, cfg).query("detector == 'Growth above trend'").empty


def test_one_finding_per_agency_and_code_the_larger_wins():
    rows = [(a, "0803", 2022, 1_000_000.0) for a in TEN] + [(a, "0803", 2025, 1_000_000.0) for a in TEN[:-1]] + [("D10", "0803", 2025, 10_000_000.0)]
    d = O.detect(_budget(rows), _agencies(TEN), NO_PAY, _legacy_cfg())
    r = d[(d.agency_code == "D10") & d.spending_code.str.contains("0803")]
    assert len(r) == 1  # flagged by both the peer-gap and the growth detector, listed once
    # peer gap is worth $650k likely; growth is 10-30% of $8.1M above the state's pace = $1.62M likely, so growth is kept
    assert r.detector.iloc[0] == "Growth above trend" and r.likely.iloc[0] == 1_620_000


def test_tail_spend_and_leverage_come_from_private_vendor_payments():
    big = [("A01", f"V{i:02d}", "Fleet & fuel", 10e6, 2026, False) for i in range(1, 11)]
    tail = [("A01", "V11", "Fleet & fuel", 600e3, 2026, False), ("A01", "V12", "Fleet & fuel", 600e3, 2026, False)]
    acme = [(f"A{i:02d}", "ACME", None, 600e3, 2026, False) for i in range(1, 11)]  # 10 agencies, $6M
    gov = [(f"A{i:02d}", "STATE COLLEGE", None, 600e3, 2026, True) for i in range(1, 11)]  # government payees never count
    d = O.detect(_budget([("D01", "0801", 2025, 1.0)]), _agencies(["D01"]), _pay(big + tail + acme + gov))
    t = d[d.detector == "Tail spend"].iloc[0]
    assert t.baseline == 1_200_000 and t.low == 36_000 and t.high == 120_000 and t.spending_code == "2 smaller vendors" and t.agency == "Statewide"
    lv = d[d.detector == "Leverage"]
    assert list(lv.spending_code) == ["Acme"] and lv.low.iloc[0] == 120_000 and lv.high.iloc[0] == 300_000
    assert "paid by 10 agencies separately in FY2026" in lv.evidence.iloc[0]


def test_ids_are_sequential_and_ordered_by_likely_saving():
    d = O.detect(*_peer_gap_case()[:2], _pay([(f"A{i:02d}", "ACME", None, 700e3, 2026, False) for i in range(1, 11)]))
    assert list(d.opp_id) == [f"O{i:03d}" for i in range(1, len(d) + 1)]
    assert d.likely.is_monotonic_decreasing and d.likely.ge(0).all() and (d.low <= d.high).all()


def test_bid_list_ranks_biddable_private_vendors_paid_by_ten_agencies():
    rows = [(f"A{i:02d}", "ACME INC", None, 600e3, fy, False) for i in range(1, 11) for fy in (2025, 2026)]
    rows += [(f"A{i:02d}", "STATE HEALTH MCO", None, 900e3, 2026, False) for i in range(1, 11)]  # a service provider: not biddable
    rows += [("D06", "OTHER CO", None, 20e6, 2026, False)]  # excluded agency, and too few agencies
    ay = pd.DataFrame([{"agency_code": f"A{i:02d}", "agency": f"Agency {i}", "fiscal_year": 2026, "fte": 1.0} for i in range(1, 11)])
    b = O.bid_list(_pay(rows), ay)
    assert list(b.vendor) == ["Acme Inc"] and b["rank"].iloc[0] == 1 and b.agencies.iloc[0] == 10
    assert b.fy2025.iloc[0] == 6e6 and b.fy2026.iloc[0] == 6e6 and b.low.iloc[0] == 120_000 and b.high.iloc[0] == 300_000
    assert b.top_agencies.iloc[0].count(",") == 2 and b.top_agencies.iloc[0].startswith("Agency ")


def test_an_agency_name_is_its_latest_not_the_first_row_met():
    ay = pd.DataFrame([{"agency_code": "D01", "agency": "New name", "fiscal_year": 2025, "fte": 100.0},
                       {"agency_code": "D01", "agency": "Old name", "fiscal_year": 2019, "fte": 100.0}])
    assert O._latest_names(ay)["D01"] == "New name"
    assert O._latest_names(ay.iloc[::-1])["D01"] == "New name"  # whatever the row order


def test_every_threshold_comes_from_the_assumptions_file():
    cfg = O.assumptions()
    for section, keys in {"peer_gap": ("min_agencies", "min_budget", "percentile"), "growth": ("points_above_state", "min_base_budget"),
                          "tail_spend": ("top_vendors",), "leverage": ("min_agencies",), "bid_list": ("min_agencies", "not_biddable")}.items():
        for k in keys:
            assert k in cfg[section], (section, k)
    assert cfg["current_fy"] == 2025 and cfg["payments_fy"] == 2026


@pytest.mark.parametrize("column", O.COLUMNS)
def test_findings_have_the_documented_columns(column):
    d = O.detect(*_peer_gap_case()[:2], NO_PAY)
    assert column in d.columns
