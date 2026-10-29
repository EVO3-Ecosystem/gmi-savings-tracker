"""Checks on the latest extract run (Phase 1). Run after `make extract`: pytest -q tests"""
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
pytestmark = pytest.mark.skipif(not RAW.exists() or not any(RAW.glob("*/manifest.json")), reason="no extract run in data/ (CI)")


def latest():
    runs = sorted(p for p in RAW.iterdir() if (p / "manifest.json").exists())
    return runs[-1], json.loads((runs[-1] / "manifest.json").read_text())


def test_every_dataset_matches_portal_count():
    d, m = latest()
    assert m["status"] == "passed"
    for e in m["datasets"]:
        assert pq.ParquetFile(d / f"{e['dataset']}.parquet").metadata.num_rows == e["portal_count"], e["dataset"]


def test_portal_totals_saved_for_phase2():
    _, m = latest()
    by = {e["dataset"]: e for e in m["datasets"]}
    assert len(by["budget"]["portal_totals"]) >= 11 and len(by["payments"]["portal_totals"]) >= 20
    for e in m["datasets"]:
        assert sum(t["rows"] for t in e["portal_totals"]) == e["portal_count"], e["dataset"]
