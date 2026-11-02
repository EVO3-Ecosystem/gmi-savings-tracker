"""Reconcile the API extract with the Maryland Transparency Portal's own downloads (mtp.maryland.gov/#!/view-data).

    python -m src.pipeline.reconcile [--reuse] [--strict]

For each dataset in config/datasets.yaml `website_downloads`, downloads the CSV the portal's Open Finance sites serve
("data as displayed on this website"), then compares row counts and totals for every fiscal year with the latest API
extract in the database (raw layer). Self-healing: each download retries with backoff, a truncated file (fewer rows than
the API copy in total) is downloaded again once, and --reuse skips downloading when a file is already there.
Feedback loop: results go to docs/reconciliation/by_year.csv and are appended to data/reconcile_history.csv.
The budget file also carries the site's own stage label per year, saved next to the confirmed stage (ref.budget_stage).
"""
import argparse
import datetime as dt
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "data" / "mtp"
OUT = ROOT / "docs" / "reconciliation"
DB = ROOT / "data" / "md_transparency.duckdb"
API_YEAR = {"budget": "fiscal_year", "fund": "fiscal_year", "payments": "fiscal_year", "grants": "fiscalyear"}
API_SUM = {"budget": "budget", "fund": "budget", "payments": "amount", "grants": "amount"}


def num(col):
    return f"try_cast(replace(replace(replace(\"{col}\", ',', ''), '$', ''), ' ', '') as double)"


def download(name, url, tries=4):
    WEB.mkdir(parents=True, exist_ok=True)
    f, tmp = WEB / f"{name}.csv", WEB / f"{name}.csv.part"
    for k in range(tries):
        try:
            with requests.get(url, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(tmp, "wb") as h:
                    for chunk in r.iter_content(1 << 20):
                        h.write(chunk)
            tmp.replace(f)
            return f
        except Exception as e:  # noqa: BLE001 - retried, then reported
            err = e
            time.sleep(5 * 2 ** k)
    raise RuntimeError(f"{name}: download failed after {tries} tries: {err}")


def compare(con, name, spec, f):
    w = con.execute(f"select try_cast(\"{spec['year_col']}\" as int) fiscal_year, count(*) rows_web, sum({num(spec['sum_col'])}) total_web "
                    f"from read_csv('{f}', all_varchar=true, header=true) group by 1").df()
    a = con.execute(f"select try_cast({API_YEAR[name]} as int) fiscal_year, count(*) rows_api, sum({API_SUM[name]}::double) total_api from raw.{name} group by 1").df()
    j = w.merge(a, on="fiscal_year", how="outer").sort_values("fiscal_year")
    j.insert(0, "dataset", name)
    j["total_difference"] = (j.total_web.fillna(0) - j.total_api.fillna(0)).round(2)
    j["match"] = (j.rows_web == j.rows_api) & (j.total_difference.abs() <= 1)
    return j


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true", help="use files already in data/mtp")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any year differs")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load((ROOT / "config" / "datasets.yaml").read_text())["website_downloads"]
    con = duckdb.connect(str(DB), read_only=True)
    parts = []
    for name, spec in cfg.items():
        f = WEB / f"{name}.csv"
        t0 = time.time()
        if not (a.reuse and f.exists()):
            f = download(name, spec["url"])
        j = compare(con, name, spec, f)
        if j.rows_web.sum() < j.rows_api.sum() and not a.reuse:  # self-heal: a short file is downloaded once more
            f = download(name, spec["url"])
            j = compare(con, name, spec, f)
        print(f"{name}: {int(j.rows_web.sum()):,} web rows vs {int(j.rows_api.sum()):,} API rows; {int((~j.match).sum())} years differ ({time.time() - t0:.0f}s)")
        parts.append(j)
        if name == "budget":
            st = con.execute(f"select try_cast(\"{spec['year_col']}\" as int) fiscal_year, any_value(\"Type\") site_stage from read_csv('{f}', all_varchar=true) group by 1").df()
            ref = con.execute("select try_cast(fiscal_year as int) fiscal_year, stage confirmed_stage, source from ref.budget_stage").df()
            st = st.merge(ref, on="fiscal_year", how="left").sort_values("fiscal_year")
            key = lambda v: next((w for w in ("actual", "working", "allowance", "appropriation") if w in str(v).lower()), None)  # noqa: E731
            st["agrees"] = [key(c) == key(s) for c, s in zip(st.confirmed_stage, st.site_stage)]
            OUT.mkdir(parents=True, exist_ok=True)
            st.to_csv(OUT / "budget_stage_labels.csv", index=False)
    con.close()
    res = pd.concat(parts, ignore_index=True)
    OUT.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT / "by_year.csv", index=False)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    summ = res.groupby("dataset").agg(rows_web=("rows_web", "sum"), rows_api=("rows_api", "sum"), years=("fiscal_year", "count"), years_differing=("match", lambda m: int((~m).sum()))).reset_index()
    hist = ROOT / "data" / "reconcile_history.csv"
    summ.assign(checked_utc=now).to_csv(hist, mode="a", header=not hist.exists(), index=False)
    summ.to_csv(OUT / "summary.csv", index=False)
    bad = int(summ.years_differing.sum())
    print(f"reconcile: {len(summ)} datasets, {bad} years differing")
    return 1 if a.strict and bad else 0


if __name__ == "__main__":
    sys.exit(main())
