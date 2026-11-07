"""The stage evidence: the legacy file carried over, and consistent with the other reference data (no data/ needed)."""
from pathlib import Path

import pandas as pd

from src.pipeline import marts

ROOT = Path(__file__).resolve().parents[1]
STAGES = {"Actual", "Working budget", "Legislative appropriation"}


def test_the_reference_file_equals_the_legacy_file_it_replaces():
    legacy = pd.read_csv(ROOT / "legacy" / "gst" / "stage_evidence.csv")
    pd.testing.assert_frame_equal(marts.stage_evidence(), legacy)


def test_columns_are_the_documented_dashboard_columns():
    doc = pd.read_csv(ROOT / "docs" / "schemas" / "dashboard_columns.csv")
    assert list(marts.stage_evidence().columns) == list(doc[doc.table == "stage_evidence"].column)


def test_every_row_is_well_formed():
    ev = marts.stage_evidence()
    assert len(ev) == 4 and set(ev.official_stage) <= STAGES
    assert ev.evidence.str.len().gt(0).all() and ev.evidence_url.str.startswith("https://").all()
    compared = ev[ev.programs_compared.notna()]
    assert len(compared) == 2 and (compared.programs_exact <= compared.programs_compared).all() and compared.dbm_actual_total.notna().all()
    assert ev[ev.programs_compared.isna()].file_total.notna().all()  # a whole-file total, which the build checks against the database


def test_it_agrees_with_the_stage_reference_for_every_year_it_covers():
    stage = pd.read_csv(ROOT / "reference" / "budget_stage.csv").set_index("fiscal_year").stage
    ev = marts.stage_evidence()
    assert set(ev.fiscal_year) <= set(stage.index)
    for r in ev.itertuples():
        assert stage[r.fiscal_year] == r.official_stage, r.fiscal_year
