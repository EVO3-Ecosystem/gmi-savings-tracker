"""Extra sources pulled with each extract run (Phase 1), for the six recommendations and real-dollar views.

  cpi              BLS CPI-U, U.S. city average, all items (CUUR0000SA0), monthly        -> inflation-adjusted trends
  federal_awards   USAspending: federal grants to governments in Maryland, by federal FY  -> federal vs General Fund savings
  population       Census Population Estimates, Maryland, July 1 each year              -> spending per resident
  mfr              DBM Managing for Results strategic plans (one PDF per agency), latest  -> recommendation 6: tie spending to results

Each source retries transient errors with backoff, checks its own result, and reports "pass" or "warn".
A warning never blocks the core extract: these sources add context, the five portal datasets are the record.
Optional keys (environment): BLS_API_KEY raises BLS limits.
"""
import datetime as dt
import json
import os
import re
import shutil
import time
from pathlib import Path

import pandas as pd
import requests

UA = {"User-Agent": "gmi-savings-tracker (public data pipeline)"}


def _get(url, method="GET", tries=5, headers=None, **kw):
    for i in range(tries):
        try:
            r = requests.request(method, url, timeout=120, headers=UA if headers is None else headers, **kw)
            if r.status_code == 429:  # throttled: wait as long as the server asks, then retry
                time.sleep(min(int(r.headers.get("Retry-After") or 30 * (i + 1)), 300))
                raise requests.exceptions.HTTPError("HTTP 429")
            if r.status_code in (500, 502, 503, 504):
                raise requests.exceptions.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException:
            if i == tries - 1:
                raise
            time.sleep(5 * 2 ** i)


def cpi(out):
    """BLS API first; if BLS refuses (daily request limit is shared per IP without a key), the same series from FRED."""
    year = dt.date.today().year
    try:
        df, src = _cpi_bls(year), "BLS"
    except Exception as e:
        t = pd.read_csv(pd.io.common.StringIO(_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCNS", headers={}).text))
        t.columns = ["date", "cpi"]
        t["date"] = pd.to_datetime(t.date)
        df = pd.DataFrame({"year": t.date.dt.year, "month": t.date.dt.month, "cpi": pd.to_numeric(t.cpi, errors="coerce")}).dropna()
        df = df[df.year >= 2007]
        src = f"FRED CPIAUCNS (BLS unavailable: {str(e)[:80]})"
    df = df.drop_duplicates(["year", "month"]).sort_values(["year", "month"])
    df.to_parquet(out / "cpi.parquet", index=False)
    last = df.iloc[-1]
    gaps = len(pd.period_range(f"{df.year.min()}-01", f"{int(last.year)}-{int(last.month):02d}", freq="M")) - len(df)
    return {"rows": len(df), "detail": f"{src}: {df.year.min()}-01 to {int(last.year)}-{int(last.month):02d}, {gaps} missing months",
            "ok": gaps <= 2 and last.year >= year - 1}  # BLS skipped Oct 2025 (federal shutdown)


def _cpi_bls(year):
    rows = []
    for start in range(2007, year + 1, 10):
        body = {"seriesid": ["CUUR0000SA0"], "startyear": str(start), "endyear": str(min(start + 9, year))}
        if os.environ.get("BLS_API_KEY"):
            body["registrationkey"] = os.environ["BLS_API_KEY"]
        j = _get("https://api.bls.gov/publicAPI/v2/timeseries/data/", "POST", json=body).json()
        if j.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS: {j.get('message')}")
        for d in j["Results"]["series"][0]["data"]:
            if d["period"].startswith("M") and d["period"] != "M13" and d["value"].replace(".", "", 1).isdigit():  # "-" = not published
                rows.append({"year": int(d["year"]), "month": int(d["period"][1:]), "cpi": float(d["value"])})
    return pd.DataFrame(rows)


def federal_awards(out):
    today = dt.date.today()
    last_fy = today.year if today.month >= 10 else today.year - 1  # last complete federal FY
    rows = []
    for fy in range(2008, last_fy + 2):
        start, end = f"{fy - 1}-10-01", min(f"{fy}-09-30", today.isoformat())
        if start > today.isoformat():
            break
        body = {"scope": "recipient_location", "geo_layer": "state", "geo_layer_filters": ["MD"],
                "filters": {"time_period": [{"start_date": start, "end_date": end}], "award_type_codes": ["02", "03", "04", "05"], "recipient_type_names": ["government"]}}
        r = _get("https://api.usaspending.gov/api/v2/search/spending_by_geography/", "POST", json=body).json()["results"]
        rows.append({"federal_fy": fy, "amount": r[0]["aggregated_amount"] if r else 0.0, "partial": end < f"{fy}-09-30"})
    df = pd.DataFrame(rows)
    # USAspending reporting lags: a closed year far below the year before is flagged as still being reported
    df["reporting_incomplete"] = df.partial | (df.amount < 0.6 * df.amount.shift(1))
    df.to_parquet(out / "federal_awards.parquet", index=False)
    full = df[~df.reporting_incomplete]
    return {"rows": len(df), "detail": f"FY{df.federal_fy.min()}-FY{df.federal_fy.max()}; latest full year ${full.amount.iloc[-1] / 1e9:,.1f}B",
            "ok": bool((full.amount > 0).all())}


def population(out):
    base = "https://www2.census.gov/programs-surveys/popest/datasets"
    newest = None
    for v in range(dt.date.today().year, 2023, -1):  # newest vintage first
        url = f"{base}/2020-{v}/state/totals/NST-EST{v}-ALLDATA.csv"
        if requests.head(url, timeout=60, headers=UA).status_code == 200:
            newest = (v, url)
            break
    frames = []
    for url, vintage in [(f"{base}/2010-2020/state/totals/nst-est2020-alldata.csv", 2020), (newest[1], newest[0])]:
        t = pd.read_csv(pd.io.common.StringIO(_get(url).text), dtype={"STATE": str})
        md = t[t.STATE.astype(str).str.zfill(2) == "24"].iloc[0]
        for c in [c for c in t.columns if c.startswith("POPESTIMATE") and c[-4:].isdigit()]:
            frames.append({"year": int(c[-4:]), "population": int(md[c]), "vintage": vintage})
    df = pd.DataFrame(frames).sort_values(["year", "vintage"]).drop_duplicates("year", keep="last")  # newest vintage wins
    df.to_parquet(out / "population.parquet", index=False)
    return {"rows": len(df), "detail": f"{df.year.min()}-{df.year.max()}, vintage {newest[0]}", "ok": df.year.max() >= dt.date.today().year - 2}


def mfr(out, prev_dir):
    """Download every agency's Managing for Results PDF from the newest strategic-plans page; reuse unchanged files."""
    yy = dt.date.today().year % 100 + 2
    page = None
    for y in range(yy, yy - 4, -1):
        r = requests.get(f"https://dbm.maryland.gov/Pages/MFR_StrategicPlansFY{y}.aspx", timeout=60, headers=UA)
        if r.status_code == 200 and ".pdf" in r.text.lower():
            page, fy = r, 2000 + y
            break
    links = sorted(set(re.findall(r'href="(/Documents/MFR_documents/\d{4}/[^"]+\.pdf)"', page.text, flags=re.I)))
    d = out / "mfr"
    d.mkdir()
    prev_idx = {}
    if prev_dir and (prev_dir / "mfr_index.parquet").exists():
        prev_idx = pd.read_parquet(prev_dir / "mfr_index.parquet").set_index("url").to_dict("index")
    rows, reused = [], 0
    for path in links:
        url = "https://dbm.maryland.gov" + path
        name = path.rsplit("/", 1)[1]
        time.sleep(PACE)  # DBM throttles bursts (HTTP 429 seen from GitHub runners)
        h = _get(url, "HEAD", tries=7).headers
        lm, size = h.get("Last-Modified"), int(h.get("Content-Length") or 0)
        p = prev_idx.get(url)
        if p and p["last_modified"] == lm and p["bytes"] == size and (prev_dir / "mfr" / name).exists():
            try:
                os.link(prev_dir / "mfr" / name, d / name)
            except OSError:
                shutil.copy2(prev_dir / "mfr" / name, d / name)
            reused += 1
        else:
            (d / name).write_bytes(_get(url, tries=7).content)
        ok = (d / name).read_bytes()[:4] == b"%PDF"
        rows.append({"fiscal_year": fy, "agency_file": name, "url": url, "bytes": (d / name).stat().st_size, "last_modified": lm, "is_pdf": ok})
    idx = pd.DataFrame(rows)
    idx.to_parquet(out / "mfr_index.parquet", index=False)
    return {"rows": len(idx), "detail": f"FY{fy}: {len(idx)} agency PDFs ({reused} unchanged and reused), {idx.bytes.sum() / 1e6:,.0f} MB",
            "ok": len(idx) >= 50 and bool(idx.is_pdf.all())}


PACE = float(os.environ.get("MFR_PACE_SECONDS", "1.0"))


def mfr_reuse(out, prev_dir):
    """Self-healing fallback: if DBM refuses this run, carry the last run's plans forward (they change once a year)."""
    if not (prev_dir and (prev_dir / "mfr_index.parquet").exists()):
        raise RuntimeError("no earlier run to reuse")
    shutil.copytree(prev_dir / "mfr", out / "mfr", copy_function=os.link, dirs_exist_ok=True)
    shutil.copy2(prev_dir / "mfr_index.parquet", out / "mfr_index.parquet")
    n = len(pd.read_parquet(out / "mfr_index.parquet"))
    return {"rows": n, "detail": f"DBM unavailable; reused {n} plans from {prev_dir.name}", "ok": False}


SOURCES = {"cpi": cpi, "federal_awards": federal_awards, "population": population, "mfr": mfr}


def run_all(out, prev_dir, log):
    entries = []
    for name, fn in SOURCES.items():
        t = time.time()
        try:
            res = fn(out, prev_dir) if name == "mfr" else fn(out)
            status = "pass" if res["ok"] else "warn"
        except Exception as e:  # a context source never blocks the core extract
            res, status = {"rows": 0, "detail": f"{type(e).__name__}: {e}"[:300]}, "warn"
            if name == "mfr":
                try:
                    res = mfr_reuse(out, prev_dir)
                except Exception as e2:  # nothing to reuse either
                    res["detail"] += f"; reuse failed: {e2}"[:200]
        e = {"source": name, "status": status, "rows": res["rows"], "detail": res["detail"], "secs": round(time.time() - t, 1)}
        entries.append(e)
        log(f"{name:15s} {status:4s} {e['rows']:>6,} rows  {e['detail']}  {e['secs']}s")
    (out / "enrichment.json").write_text(json.dumps(entries, indent=1))
    return entries


if __name__ == "__main__":  # quick manual test: python -m src.pipeline.enrich <dir>
    import sys
    o = Path(sys.argv[1])
    o.mkdir(parents=True, exist_ok=True)
    run_all(o, None, print)
