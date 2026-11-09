"""Stage the published dataset: the export's Parquet marts, its manifest and a dataset card (README.md).

    python -m src.pipeline.publish --out DIR [--src site_data]

Used by .github/workflows/publish_data.yml, which uploads DIR to the Hugging Face dataset thedatavigilante/maryland-gmi-spending
and attaches the Parquet files to a GitHub Release data-<run_id>. Builds from data/export/latest when present, else the
checked-in site_data/ snapshot (as site.py does). Prints the run id on the last line (`run_id=<id>`) for the workflow.
"""
import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import yaml

from src.pipeline import site

ROOT = Path(__file__).resolve().parents[2]
REPO = site.REPO
HF_REPO = "thedatavigilante/maryland-gmi-spending"


def run_id(src):
    snap = Path(src) / "snapshot.json"
    if snap.exists():
        return json.loads(snap.read_text())["export"]
    return Path(src).resolve().name


def card(src, files, rid):
    cfg = yaml.safe_load((ROOT / "config" / "datasets.yaml").read_text())
    run, portal = site.as_of(Path(src))
    man = {r["file"]: r for r in csv.DictReader(open(Path(src) / "manifest.csv"))}
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
    lines += [f"| {f.stem} | {man.get(f.stem, {}).get('rows', '')} | parquet/{f.name} |" for f in files]
    lines += ["", "Payment screen tables (d_payment_screen, d_payment_screen_summary) are leads to review, not errors: "
              f"see [docs/models/payment_screen.md]({REPO}/blob/main/docs/models/payment_screen.md).", ""]
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
    size = sum(f.stat().st_size for f in files)
    print(f"staged {len(files)} Parquet files ({size / 1e6:.1f} MB), manifest and dataset card in {out}")
    print(f"run_id={rid}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--src")
    a = ap.parse_args(argv)
    stage(a.out, a.src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
