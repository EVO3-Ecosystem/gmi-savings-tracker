"""Publishing (src/pipeline/publish.py, .github/workflows/publish_data.yml) is checked without network: the dry run stages
and validates the dataset card, the file list against the manifest, sizes and the release tag; the workflow is valid YAML
with pinned actions and packages."""
import re
import shutil
import socket
from pathlib import Path

import pytest
import yaml

from src.pipeline import publish

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "site_data"
WF = ROOT / ".github" / "workflows"
needs_snapshot = pytest.mark.skipif(not (SNAP / "parquet").exists(), reason="no site_data/parquet snapshot")


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the dry run opened a network connection")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def staged(tmp_path):
    out = tmp_path / "stage"
    publish.stage(out, SNAP)
    return out, publish.run_id(SNAP)


@needs_snapshot
def test_the_dry_run_validates_and_prints_the_plan_without_network(no_network, capsys):
    assert publish.main(["--dry-run", "--src", str(SNAP)]) == 0
    out = capsys.readouterr().out
    rid = publish.run_id(SNAP)
    assert re.fullmatch(r"\d{8}T\d{6}Z", rid)
    assert f"tag data-{rid}" in out and publish.HF_REPO in out and "validated" in out
    assert out.count("| parquet/") == len(list((SNAP / "parquet").glob("*.parquet")))


@needs_snapshot
def test_a_clean_staging_has_no_problems_and_the_card_counts_the_files_rows(staged):
    out, rid = staged
    assert publish.validate(out, rid) == []
    card = (out / "README.md").read_text()
    import pyarrow.parquet as pq
    n = pq.ParquetFile(out / "parquet" / "f_grants.parquet").metadata.num_rows
    assert f"| f_grants | {n} | parquet/f_grants.parquet |" in card


@needs_snapshot
@pytest.mark.parametrize("damage,expect", [
    ("yaml", "YAML does not parse"),
    ("no header", "no YAML header"),
    ("drop config", "no config for parquet/d_agency.parquet"),
    ("extra file", "zz_extra.parquet is not in manifest.csv"),
    ("no manifest", "manifest.csv missing"),
    ("no disclaimer", "lacks the disclaimer"),
    ("no license", "lacks license"),
])
def test_validation_catches_a_damaged_staging(staged, damage, expect):
    out, rid = staged
    card = out / "README.md"
    text = card.read_text()
    if damage == "yaml":
        card.write_text(text.replace("configs:", "configs: [unclosed", 1))
    elif damage == "no header":
        card.write_text(text.split("---\n", 2)[2])
    elif damage == "drop config":
        card.write_text(text.replace("  - config_name: d_agency\n    data_files: parquet/d_agency.parquet\n", ""))
    elif damage == "extra file":
        shutil.copy(out / "parquet" / "d_agency.parquet", out / "parquet" / "zz_extra.parquet")
    elif damage == "no manifest":
        (out / "manifest.csv").unlink()
    elif damage == "no disclaimer":
        card.write_text(text.replace(publish.site.DISCLAIMER, "A dataset"))
    elif damage == "no license":
        card.write_text(text.replace("license: other\n", "", 1))
    assert any(expect in p for p in publish.validate(out, rid)), publish.validate(out, rid)


@needs_snapshot
def test_sizes_and_the_release_tag_are_checked(staged, monkeypatch):
    out, rid = staged
    assert any("not a pipeline run id" in p for p in publish.validate(out, "site_data"))
    monkeypatch.setattr(publish, "MAX_FILE", 1000)
    assert any("limit" in p and "MB" in p for p in publish.validate(out, rid))
    monkeypatch.setattr(publish, "MAX_FILE", 100e6)
    monkeypatch.setattr(publish, "MAX_TOTAL", 1000)
    assert any("total" in p for p in publish.validate(out, rid))
    assert publish.release("20261109T154457Z") == ("data-20261109T154457Z", "Data export 20261109T154457Z")


@needs_snapshot
def test_a_failed_validation_stops_the_dry_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(publish, "MAX_FILE", 10)
    assert publish.main(["--dry-run", "--src", str(SNAP), "--out", str(tmp_path / "s")]) == 1
    assert "publish refused" in capsys.readouterr().err


def test_manifest_line_counts_are_a_warning_not_a_blocker(tmp_path):
    """export.py counts CSV lines; a text field with line breaks makes its rows larger than the file's records."""
    if not (SNAP / "parquet").exists():
        pytest.skip("no snapshot")
    out = tmp_path / "s"
    publish.stage(out, SNAP)
    man = (out / "manifest.csv").read_text().splitlines()
    man = [re.sub(r"^(d_agency,mart,)\d+", r"\g<1>99999", ln) for ln in man]
    (out / "manifest.csv").write_text("\n".join(man) + "\n")
    warns = []
    assert publish.validate(out, publish.run_id(SNAP), warns) == []
    assert any("99999 rows for d_agency" in w for w in warns)


def _workflow(name):
    return yaml.safe_load((WF / name).read_text())


def test_the_publish_workflow_is_valid_yaml_and_validates_before_uploading():
    wf = _workflow("publish_data.yml")
    assert wf["name"] == "Publish data" and set(wf[True]) == {"push", "workflow_dispatch"}  # YAML reads the key `on` as True
    steps = wf["jobs"]["publish"]["steps"]
    runs = [s.get("run", "") for s in steps]
    dry = next(i for i, r in enumerate(runs) if "--dry-run" in r)
    upload = next(i for i, s in enumerate(steps) if s.get("name") == "Upload to Hugging Face")
    assert dry < upload and "src.pipeline.publish" in runs[dry]
    assert wf["permissions"] == {"contents": "write"}
    assert "${{ secrets.HF_TOKEN }}" in (WF / "publish_data.yml").read_text()


def test_actions_are_pinned_like_the_other_workflows():
    pins = {}
    for f in sorted(WF.glob("*.yml")):
        text = f.read_text()
        for action, sha, comment in re.findall(r"uses:\s*([\w./-]+)@(\S+)(?:\s*#\s*(\S+))?", text):
            assert re.fullmatch(r"[0-9a-f]{40}", sha), f"{f.name}: {action}@{sha} is not pinned to a commit"
            assert comment, f"{f.name}: {action} pin has no version comment"
            pins.setdefault(action, set()).add(sha)
    assert pins["actions/checkout"] and all(len(v) == 1 for v in pins.values()), pins
    installs = [s["run"] for s in _workflow("publish_data.yml")["jobs"]["publish"]["steps"] if s.get("run", "").startswith("pip install")]
    extra = [p for r in installs for p in re.findall(r'"([^"]+)"', r)]
    assert extra and all(re.fullmatch(r"[A-Za-z0-9_.-]+==\d+(\.\d+)*", p) for p in extra), f"pip packages not pinned exactly: {extra}"
