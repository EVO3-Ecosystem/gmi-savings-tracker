"""Stage the published dataset: the export's Parquet marts, its manifest and a dataset card (README.md).

    python -m src.pipeline.publish --out DIR [--src site_data]
    python -m src.pipeline.publish --dry-run [--src site_data] [--out DIR]


Used by .github/workflows/publish_data.yml, which uploads DIR to the Hugging Face dataset thedatavigilante/maryland-gmi-spending
and attaches the Parquet files to a GitHub Release data-<run_id>. Builds from data/export/latest when present, else the
checked-in site_data/ snapshot (as site.py does). Prints the run id on the last line (`run_id=<id>`) for the workflow.
Every staging is validated (validate()): the dataset card's YAML header and its configs, the file list against the manifest
(names and row counts), file and total sizes, and the release tag; a problem stops the publish before any upload.
--dry-run stages into a temporary folder (or --out), validates, and prints the plan (Hugging Face repo, release tag and
title, every file with its size) without touching the network; exit 1 on a problem.
"""
import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pyarrow.parquet as pq
import yaml

from src.pipeline import site

ROOT = Path(__file__).resolve().parents[2]
REPO = site.REPO
HF_REPO = "thedatavigilante/maryland-gmi-spending"
RUN_ID = re.compile(r"^\d{8}T\d{6}Z$")
MAX_FILE = 100e6     # per file: well under the GitHub Release asset limit (2 GiB) and the Hub's per-file guidance
MAX_TOTAL = 1e9      # per release
CARD_KEYS = ("license", "pretty_name", "configs")


def release(rid):
    """(tag, title) of the GitHub Release for an export run id."""
    return f"data-{rid}", f"Data export {rid}"


def run_id(src):
    snap = Path(src) / "snapshot.json"
    if snap.exists():
        return json.loads(snap.read_text())["export"]
    return Path(src).resolve().name


def card(src, files, rid):
    cfg = yaml.safe_load((ROOT / "config" / "datasets.yaml").read_text())
    run, portal = site.as_of(Path(src))
    srcs = list(csv.DictReader(open(Path(src) / "sources.csv"))) if (Path(src) / "sources.csv").exists() else []
    upd = {r["dataset_id"]: r for r in srcs}
    lines = ["---", "license: other", "license_name: maryland-open-data-terms",
             "license_link: https://opendata.maryland.gov", "language: [en]",
             "pretty_name: Maryland GMI spending marts", "tags: [government, budget, procurement, maryland, open-data]",
             "configs:"]
    lines += [f"  - config_name: {f.stem}\n    data_files: parquet/{f.name}" for f in files]
    lines += ["---", "", "# Maryland GMI spending marts", "",
              f"{site.DISCLAIMER}. The tables behind the GMI Savings Tracker prototype ({REPO}), which checks Maryland's "
              "Government Modernization Initiative savings against the State's own budget and payments data.", "",
              f"**As of:** pipeline run {run or 'unknown'} (export `{rid}`); latest portal update of a source: {portal or 'unknown'}.", "",
              "## Source datasets (opendata.maryland.gov)", "", "| dataset | id | portal title | portal updated |", "|---|---|---|---|"]
    for k, d in cfg["datasets"].items():
        u = upd.get(d["id"], {})
        lines.append(f"| {k} | [{d['id']}](https://opendata.maryland.gov/d/{d['id']}) | {d.get('portal_name', '')} | {u.get('portal_updated', '')} |")
    lines += ["", "Context sources (CPI, population, federal awards, Managing for Results plans) are listed in the repository's "
              f"[data sources]({REPO}/blob/main/docs/data-sources.md).", "",
              "## Licence", "",
              "The source datasets are published on Maryland's open data portal (https://opendata.maryland.gov), whose metadata lists "
              "each of them as Public Domain; use follows the portal's open data terms. The derived tables add "
              "the pipeline's own groupings and screening assumptions (labeled in config/assumptions.yaml). Not an official State product.", "",
              "## Tables", "", "Every column is defined in the repository's data dictionary: "
              f"[docs/data-governance.md section 11.3]({REPO}/blob/main/docs/data-governance.md#113-dashboard-datasets) "
              f"and [docs/schemas/dashboard_columns.csv]({REPO}/blob/main/docs/schemas/dashboard_columns.csv).", "",
              "| table | rows | file |", "|---|---|---|"]
    lines += [f"| {f.stem} | {pq.ParquetFile(f).metadata.num_rows} | parquet/{f.name} |" for f in files]  # the file's own count
    lines += ["", "Payment screen tables (d_payment_screen, d_payment_screen_summary) are leads to review, not errors: "
              f"see [docs/models/payment_screen.md]({REPO}/blob/main/docs/models/payment_screen.md).", ""]
    return "\n".join(lines)


def validate(out, rid, warnings=None):
    """Problems with a staged folder (empty list when it can be published). Non-blocking findings go to `warnings`."""
    out = Path(out)
    probs = []
    warnings = [] if warnings is None else warnings
    files = sorted((out / "parquet").glob("*.parquet"))
    if not files:
        return [f"no Parquet files in {out}/parquet"]
    readme = out / "README.md"
    if not readme.exists():
        probs.append("README.md (dataset card) missing")
    else:
        text = readme.read_text()
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        meta = None
        if not m:
            probs.append("dataset card has no YAML header")
        else:
            try:
                meta = yaml.safe_load(m.group(1))
            except yaml.YAMLError as e:
                probs.append(f"dataset card YAML does not parse: {e}")
        if isinstance(meta, dict):
            probs += [f"dataset card YAML lacks {k}" for k in CARD_KEYS if not meta.get(k)]
            cfg = {c.get("config_name"): c.get("data_files") for c in meta.get("configs") or []}
            for f in files:
                if cfg.get(f.stem) != f"parquet/{f.name}":
                    probs.append(f"dataset card has no config for parquet/{f.name}")
            for name, df in cfg.items():
                if not (out / str(df)).exists():
                    probs.append(f"dataset card config {name} points at a missing file {df}")
        if site.DISCLAIMER not in text:
            probs.append("dataset card lacks the disclaimer")
        if "**As of:** pipeline run unknown" in text:
            probs.append("dataset card has no as-of date (no pipeline_runs.csv in the export)")
    man = out / "manifest.csv"
    rows = {r["file"]: r for r in csv.DictReader(open(man))} if man.exists() else None
    if rows is None:
        probs.append("manifest.csv missing")
    else:
        for f in files:
            r = rows.get(f.stem)
            n = pq.ParquetFile(f).metadata.num_rows
            if r is None:
                probs.append(f"{f.name} is not in manifest.csv")
            elif str(r.get("rows")) != str(n):  # export.py counts CSV lines, so a text field with line breaks over-counts
                warnings.append(f"manifest.csv says {r.get('rows')} rows for {f.stem}, the Parquet file has {n} "
                                "(the export counts CSV lines; a quoted text field contains line breaks); the card uses the file's count")
    for f in files:
        if f.stat().st_size > MAX_FILE:
            probs.append(f"{f.name} is {f.stat().st_size / 1e6:.1f} MB (limit {MAX_FILE / 1e6:.0f} MB)")
    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    if total > MAX_TOTAL:
        probs.append(f"staged files total {total / 1e6:.1f} MB (limit {MAX_TOTAL / 1e6:.0f} MB)")
    if not RUN_ID.match(str(rid or "")):
        probs.append(f"run id {rid!r} is not a pipeline run id (YYYYMMDDTHHMMSSZ), so the release tag {release(rid)[0]!r} would be wrong")
    return probs


def plan(out, rid):
    out = Path(out)
    tag, title = release(rid)
    files = sorted(p for p in out.rglob("*") if p.is_file())
    lines = [f"Hugging Face dataset: {HF_REPO} (upload_folder of {out.name}/, replaces parquet/*.parquet)",
             f"GitHub Release: tag {tag}, title {title!r}, assets: {len([f for f in files if f.suffix == '.parquet'])} Parquet files + manifest.csv",
             "", "| file | bytes |", "|---|---|"]
    lines += [f"| {f.relative_to(out)} | {f.stat().st_size:,} |" for f in files]
    lines.append(f"| total | {sum(f.stat().st_size for f in files):,} |")
    return "\n".join(lines)


def stage(out, src=None):
    src = Path(src) if src else site.source_dir()
    files = site.parquet_files(src)
    if not files:
        raise SystemExit(f"no Parquet files in {src}/parquet: run `python -m src.pipeline.export` (and `make site-snapshot`)")
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "parquet").mkdir(parents=True)
    for f in files:
        shutil.copy(f, out / "parquet" / f.name)
    shutil.copy(src / "manifest.csv", out / "manifest.csv")
    rid = run_id(src)
    (out / "README.md").write_text(card(src, files, rid))
    warns = []
    probs = validate(out, rid, warns)
    for w in warns:
        print(f"warning: {w}")
    if probs:
        raise SystemExit("publish refused:\n  - " + "\n  - ".join(probs))
    size = sum(f.stat().st_size for f in files)
    print(f"staged {len(files)} Parquet files ({size / 1e6:.1f} MB), manifest and dataset card in {out}; validated")
    print(f"run_id={rid}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out")
    ap.add_argument("--src")
    ap.add_argument("--dry-run", action="store_true", help="stage and validate without network, print the plan")
    a = ap.parse_args(argv)
    if not a.dry_run:
        if not a.out:
            ap.error("--out is required (or use --dry-run)")
        stage(a.out, a.src)
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(a.out) if a.out else Path(tmp) / "hf_stage"
        try:
            stage(out, a.src)
            rid = run_id(Path(a.src) if a.src else site.source_dir())
        except SystemExit as e:
            print(f"dry run: {e}", file=sys.stderr)
            return 1
        print("dry run (no network): the publish would do this\n")
        print(plan(out, rid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
