"""Phase 1 — Extract: Maryland open data portal (SODA) -> data/raw/<run_id>/*.parquet + manifest.json

For each dataset in config/datasets.yaml:
  1. Read the portal's metadata (rowsUpdatedAt) and its own row count and per-year totals.
  2. Freshness check: if rowsUpdatedAt is unchanged since the last good run, reuse that run's Parquet file
     (hard link, or copy) instead of downloading again. --force always downloads.
  3. Otherwise download in 20,000-row pages ordered by :id, retrying each page with exponential backoff.
  4. Verify the file: row count = portal count(*). On a mismatch, re-download (self-healing) up to
     heal_attempts times; if it still does not match, the run fails.
  5. Write manifest.json: per dataset rows, portal count, match, rowsUpdatedAt, source (downloaded/reused),
     seconds, heal attempts, and the portal's per-year totals (saved for the Phase 2 totals check).

Every run is appended to data/runs.csv (the feedback loop), including failed ones. A run that fails a check
exits non-zero and is not marked good, so the next run cannot reuse its files.

Usage:  python -m src.pipeline.extract [--force] [--gate]
  --gate   Phase 1 gate: the last two runs both matched portal row counts for every dataset.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import yaml
from sodapy import Socrata

ROOT = Path(__file__).resolve().parents[2]
CFG = yaml.safe_load((ROOT / "config" / "datasets.yaml").read_text())
DATA = ROOT / "data"
RAW = DATA / "raw"
RUNS = DATA / "runs.csv"
FAULT = os.environ.get("EXTRACT_FAULT")  # test hook, e.g. EXTRACT_FAULT=fte


def log(msg):
    print(f"{dt.datetime.now(dt.timezone.utc):%H:%M:%S} {msg}", flush=True)


def client():
    return Socrata(CFG["domain"], os.environ.get("MD_SODA_APP_TOKEN") or None, timeout=300)


def call(fn, what, tries=None):
    """Run one SODA call with exponential backoff (self-healing for dropped connections and throttling)."""
    tries = tries or CFG["retries"]
    for i in range(tries):
        try:
            return fn()
        except (requests.exceptions.RequestException, ValueError) as e:
            if i == tries - 1:
                raise RuntimeError(f"gave up on {what} after {tries} tries: {type(e).__name__}: {e}") from e
            wait = CFG["backoff_seconds"] * 2 ** i
            log(f"  retry {i + 1} {what}: {type(e).__name__}; waiting {wait}s")
            time.sleep(wait)


def portal_facts(c, fid, spec):
    meta = call(lambda: c.get_metadata(fid), f"{fid} metadata")
    n = int(call(lambda: c.get(fid, select="count(*) as n"), f"{fid} count")[0]["n"])
    y, s = spec["year_col"], spec["sum_col"]
    tot = call(lambda: c.get(fid, select=f"{y} as fiscal_year, sum({s}) as total, count(*) as rows", group=y, order=y, limit=1000), f"{fid} totals")
    totals = [{"fiscal_year": int(float(r["fiscal_year"])), "total": float(r.get("total") or 0), "rows": int(r["rows"])} for r in tot if r.get("fiscal_year") is not None]
    return meta.get("rowsUpdatedAt"), n, totals


def download(c, fid, path):
    rows, off, size = [], 0, CFG["page_size"]
    while True:
        page = call(lambda o=off: c.get(fid, order=":id", limit=size, offset=o), f"{fid} offset {off}")
        rows += page
        if len(page) < size:
            break
        off += size
    pd.DataFrame.from_records(rows).to_parquet(path, index=False)
    return len(rows)


def parquet_rows(path):
    import pyarrow.parquet as pq
    return pq.ParquetFile(path).metadata.num_rows


def last_good_run():
    if not RUNS.exists():
        return None
    r = pd.read_csv(RUNS)
    r = r[r.status == "passed"]
    return None if r.empty else str(r.run_id.iloc[-1])


def reuse(prev_dir, name, dest):
    src = prev_dir / f"{name}.parquet"
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def run(force=False):
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RAW / run_id
    out.mkdir(parents=True)
    c = client()
    prev_id = last_good_run()
    prev = json.loads((RAW / prev_id / "manifest.json").read_text()) if prev_id else {"datasets": []}
    prev_by = {d["dataset"]: d for d in prev["datasets"]}
    entries, t_run = [], time.time()
    for name, spec in CFG["datasets"].items():
        fid, t = spec["id"], time.time()
        updated, expect, totals = portal_facts(c, fid, spec)
        dest = out / f"{name}.parquet"
        p = prev_by.get(name)
        fresh = (not force) and p and p.get("rowsUpdatedAt") == updated and p.get("match") and (RAW / prev_id / f"{name}.parquet").exists()
        heals = 0
        if fresh:
            reuse(RAW / prev_id, name, dest)
            source = f"reused from {prev_id} (portal unchanged)"
        else:
            download(c, fid, dest)
            source = "downloaded"
        if FAULT == name:  # test hook: drop half the rows to prove the re-download repairs it
            pd.read_parquet(dest).iloc[: expect // 2].to_parquet(dest, index=False)
            log(f"  test fault: dropped half of {name}")
        n = parquet_rows(dest)
        while n != expect and heals < CFG["heal_attempts"]:  # self-heal: re-download on a count mismatch
            heals += 1
            log(f"  {name}: {n:,} rows vs {expect:,} on portal; re-downloading (attempt {heals})")
            if dest.exists():
                dest.unlink()
            download(c, fid, dest)
            n = parquet_rows(dest)
            source = f"re-downloaded ({heals})"
            updated, expect, totals = portal_facts(c, fid, spec)  # the portal may have updated mid-run
        e = {"dataset": name, "id": fid, "rows": n, "portal_count": expect, "match": n == expect, "rowsUpdatedAt": updated,
             "rowsUpdatedAt_utc": dt.datetime.fromtimestamp(updated, dt.timezone.utc).isoformat() if updated else None,
             "source": source, "heal_attempts": heals, "secs": round(time.time() - t, 1), "portal_totals": totals}
        entries.append(e)
        log(f"{name:9s} {fid}  {n:>8,} rows  portal {expect:>8,}  {'OK' if e['match'] else 'MISMATCH'}  {source}  {e['secs']}s")
    from . import enrich  # context sources for the six recommendations; warnings never block the core extract
    extra = enrich.run_all(out, (RAW / prev_id) if prev_id else None, log)
    ok = all(e["match"] for e in entries)
    manifest = {"run": run_id, "status": "passed" if ok else "failed", "forced": force, "seconds": round(time.time() - t_run, 1),
                "domain": CFG["domain"], "page_size": CFG["page_size"], "app_token": bool(os.environ.get("MD_SODA_APP_TOKEN")), "datasets": entries, "enrichment": extra}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    row = {"run_id": run_id, "status": manifest["status"], "forced": force, "seconds": manifest["seconds"],
           "rows": sum(e["rows"] for e in entries), "downloaded": sum(not e["source"].startswith("reused") for e in entries),
           "reused": sum(e["source"].startswith("reused") for e in entries), "heals": sum(e["heal_attempts"] for e in entries),
           "mismatches": sum(not e["match"] for e in entries), "enrichment_warnings": sum(x["status"] != "pass" for x in extra)}
    hist = pd.read_csv(RUNS) if RUNS.exists() else pd.DataFrame()
    pd.concat([hist, pd.DataFrame([row])], ignore_index=True).to_csv(RUNS, index=False)
    log(f"run {run_id} {manifest['status']} in {manifest['seconds']}s -> {out}")
    return 0 if ok else 1


def gate():
    """Phase 1 gate: the last two runs both matched portal row counts for every dataset."""
    r = pd.read_csv(RUNS) if RUNS.exists() else pd.DataFrame()
    last = r.tail(2)
    ok = len(last) == 2 and (last.status == "passed").all() and (last.mismatches == 0).all()
    for _, x in last.iterrows():
        m = json.loads((RAW / x.run_id / "manifest.json").read_text())
        print(f"{x.run_id}: {x.status}; " + ", ".join(f"{d['dataset']} {d['rows']:,}/{d['portal_count']:,}" for d in m["datasets"]))
    print("PHASE 1 GATE:", "PASSED" if ok else "NOT PASSED")
    return 0 if ok else 1


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--force", action="store_true", help="download every dataset even if the portal has not changed")
    a.add_argument("--gate", action="store_true", help="check the Phase 1 gate")
    args = a.parse_args()
    sys.exit(gate() if args.gate else run(args.force))
