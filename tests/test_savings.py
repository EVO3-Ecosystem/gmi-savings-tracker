"""GMI's reported savings and their payment checks on small constructed cases (no data/ needed)."""
import importlib.util
from pathlib import Path

import duckdb
import pandas as pd

from src.models import savings as V

ROOT = Path(__file__).resolve().parents[1]


def _pay(rows):
    """rows: (agency, payee, amount, fiscal_year[, government, passthrough, area])."""
    out = []
    for r in rows:
        a, payee, amt, fy = r[:4]
        gov, pas, area = (r[4:] + (False, False, None)[len(r) - 4:])[:3] if len(r) > 4 else (False, False, None)
        out.append({"fiscal_year": fy, "agency_code": a, "vendor": payee, "vendor_name": payee, "area": area, "amount": amt, "is_government": gov, "passthrough": pas})
    return pd.DataFrame(out)


def test_the_reference_file_still_equals_the_legacy_items():
    spec = importlib.util.spec_from_file_location("legacy_savings", ROOT / "legacy" / "gst" / "scripts" / "savings.py")
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    new = V.items()
    assert [i["id"] for i in new] == [f"S{n:02d}" for n in range(1, 19)]
    for old, cur in zip(legacy.ITEMS, new):
        assert (old["id"], old["ws"], old["item"], old["type"], old["status"], old["check"], old["page"], old["quote"]) == \
               (cur["id"], cur["ws"], cur["item"], cur["type"], cur["status"], cur["check"], cur["page"], cur["quote"])
        assert (old["lo"], old["hi"]) == (cur["lo"], cur["hi"])


def test_each_kind_of_payee_check_matches_what_it_should():
    pay = _pay([
        ("D50", "FORD MOTOR CO", 100.0, 2025), ("D50", "FORD MOTOR CO", 60.0, 2026), ("D26", "TOYOTA OF BEL AIR", 10.0, 2026),   # S06, any agency
        ("D50", "FORD MOTOR CO", 999.0, 2021),                                                                                    # before FY2022
        ("D50", "FORD CREDIT GOV", 999.0, 2026, True),                                                                            # government payees never count
        ("F50", "MOTOROLA SOLUTIONS", 40.0, 2025), ("D01", "MOTOROLA SOLUTIONS", 7.0, 2025),                                     # S03 only at F50
        ("Q00", "ARAMARK CORRECTIONAL", 30.0, 2026),                                                                              # S02, so part of the S01 union
        ("D01", "ANYWHERE LLC", 5.0, 2026, False, False, "Real estate & leases"), ("D01", "PASS THRU", 8.0, 2026, False, True, "Real estate & leases"),
    ])
    d, f = V.check_payments(pay)
    paid = f.groupby(["check_id", "fiscal_year"]).paid.sum()
    assert paid[("S06", 2025)] == 100.0 and paid[("S06", 2026)] == 70.0 and ("S06", 2021) not in paid.index
    assert paid[("S03", 2025)] == 40.0  # the D01 Motorola payment is outside the F50 check
    assert paid[("S02", 2026)] == 30.0
    assert paid[("S01", 2025)] == 40.0 and paid[("S01", 2026)] == 30.0  # S01 is S02-S05 together (Motorola at F50 + Aramark at Q00)
    assert paid[("S17", 2026)] == 5.0  # the pass-through payee is left out of a focus-area check


def test_related_items_are_checked_together_and_unchecked_items_say_so():
    pay = _pay([("D50", "FORD MOTOR CO", 100.0, 2025), ("D50", "FORD MOTOR CO", 80.0, 2026), ("D50", "WEX FLEET", 50.0, 2026)])
    d, _ = V.check_payments(pay)
    d = d.set_index("saving_id")
    assert d.loc["S09", "check_id"] == "S08" and d.loc["S11", "check_id"] == "S10"  # "same:" items point at their partner's check
    assert pd.isna(d.loc["S07", "check_id"]) and pd.isna(d.loc["S18", "check_id"])  # sale proceeds and cost avoidance have no payment line
    assert d.loc["S06", "check_note"].endswith("Payees: Ford Motor Co")  # the top FY2026 payees that matched
    assert d.loc["S09", "check_note"]  # never blank


def test_status_rules_with_and_without_a_reported_saving():
    d = pd.DataFrame({"saving_id": ["A", "B", "C", "D", "E"], "item": list("abcde"), "reported_low": [1e6, 1e6, 1e6, None, None],
                      "reported_high": [1e6, 1e6, 1e6, None, None], "check_id": list("ABCDE")})
    f = pd.DataFrame({"check_id": list("AABBCCDDEE"), "fiscal_year": [2025, 2026] * 5, "agency_code": "X",
                      "paid": [10e6, 9.4e6,   10e6, 9.7e6,   10e6, 10.5e6,   5e6, 4e6,   5e6, 6e6]})
    st = V.status(d, f, "R1").set_index("check_id")
    assert dict(st.status) == {"A": "Seen", "B": "Partly seen", "C": "Not seen yet", "D": "Payments fell", "E": "Payments did not fall"}
    assert st.loc["A", "before"] == 10e6 and st.loc["A", "after"] == 9.4e6 and st.loc["A", "reported"] == 1e6
    assert V.status(d, f, "R1").previous_status.isna().all() and not V.status(d, f, "R1").changed.any()  # no history yet


def test_previous_status_and_changed_come_from_the_last_other_run():
    d = pd.DataFrame({"saving_id": ["A"], "item": ["a"], "reported_low": [1e6], "reported_high": [1e6], "check_id": ["A"]})
    f = pd.DataFrame({"check_id": ["A", "A"], "fiscal_year": [2025, 2026], "agency_code": "X", "paid": [10e6, 9e6]})  # fell by the whole saving: Seen
    hist = pd.DataFrame({"run_id": ["R0", "R1", "R2"], "check_id": ["A"] * 3, "status": ["Not seen yet", "Partly seen", "Seen"], "after": [0, 0, 0]})
    now = V.status(d, f, "R3", hist).iloc[0]
    assert now.previous_status == "Seen" and not now.changed  # the latest earlier run, unchanged
    same_run = V.status(d, f, "R2", hist).iloc[0]
    assert same_run.previous_status == "Partly seen" and same_run.changed  # a rerun is compared with the run before it, never with itself


def test_history_is_recorded_once_per_run_and_replaced_on_a_rerun(tmp_path):
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA mart")
    con.execute("CREATE TABLE mart.d_savings_status AS SELECT 'S06' AS check_id, 'Seen' AS status, 9.0 AS after")
    assert V.record(con, "R1", tmp_path) == 1
    con.execute("CREATE OR REPLACE TABLE mart.d_savings_status AS SELECT 'S06' AS check_id, 'Partly seen' AS status, 9.5 AS after")
    V.record(con, "R1", tmp_path)  # the same run again
    V.record(con, "R2", tmp_path)
    h = V.read_history(tmp_path)
    assert list(h.run_id) == ["R1", "R2"] and list(h.status) == ["Partly seen", "Partly seen"]  # one row per run; R1 was replaced, not duplicated
    assert V.read_history(tmp_path / "missing").empty


def test_vendor_moves_keeps_only_decreases_by_widely_paid_procurement_vendors():
    ag = [f"A{i}" for i in range(5)]
    rows = [(a, "BIG VENDOR", 600e3, 2025) for a in ag] + [(a, "BIG VENDOR", 100e3, 2026) for a in ag]  # -$2.5M, five agencies
    rows += [(a, "GROWING INC", 500e3, 2025) for a in ag] + [(a, "GROWING INC", 900e3, 2026) for a in ag]  # an increase
    rows += [(a, "FEW AGENCIES", 600e3, 2025) for a in ag[:4]] + [(a, "FEW AGENCIES", 100e3, 2026) for a in ag[:4]]  # only four agencies
    rows += [(a, "STATE HEALTH PLAN", 600e3, 2025) for a in ag] + [(a, "STATE HEALTH PLAN", 100e3, 2026) for a in ag]  # not a procurement contract
    rows += [(a, "SMALL VENDOR", 100e3, 2025) for a in ag] + [(a, "SMALL VENDOR", 10e3, 2026) for a in ag]  # under $1M before
    rows += [("CAPITAL", "CAPITAL ONLY", 9e6, 2025), ("CAPITAL", "CAPITAL ONLY", 1e6, 2026)]  # operating spending only
    rows += [(a, "BIG VENDOR", 1e6, 2024) for a in ag[:1]]
    mv = V.vendor_moves(_pay(rows))
    assert list(mv.vendor) == ["Big Vendor"] and mv.change.iloc[0] == -2_500_000 and mv.agencies.iloc[0] == 5
    assert mv.fy2024.iloc[0] == 1e6 and mv.fy2025.iloc[0] == 3e6 and mv.fy2026.iloc[0] == 500e3
    assert list(mv.columns) == ["vendor", "fy2024", "fy2025", "fy2026", "change", "agencies"]


def test_vendor_moves_are_sorted_largest_decrease_first_and_capped():
    ag = [f"A{i}" for i in range(5)]
    rows = []
    for k in range(1, 4):  # three vendors falling by $3M, $5M and $7M (no FY2024 payments at all: a missing year counts as zero)
        rows += [(a, f"V{k}", (k + 1) * 400e3, 2025) for a in ag] + [(a, f"V{k}", 200e3, 2026) for a in ag]
    cfg = V.assumptions()
    cfg["vendor_moves"]["top"] = 2
    mv = V.vendor_moves(_pay(rows), cfg)
    assert list(mv.vendor) == ["V3", "V2"] and list(mv.change) == [-7_000_000, -5_000_000] and (mv.fy2024 == 0).all()
