"""Raw layer: download each state dataset and reconcile it, year by year, with the portal's own counts and totals.

A year that does not match is downloaded again (up to HEAL attempts). The portal's last-update
time is recorded so the dashboard can say how fresh each source is.
"""
import datetime as dt
import sys

import pandas as pd

from common import RAW, RUN, DOMAIN, get, soql, download_csv

HEAL = 2
SOURCES = {
    "payments": {"id": "7syw-q4cy", "title": "State of Maryland Payments Data", "year": "fiscal_year", "value": "amount",
                 "years": range(2008, 2027), "per_year_files": True,
                 "use": "Payments to vendors of $25,000 or more, by agency and payee, per fiscal year"},
    "budget": {"id": "yu65-jmmv", "title": "Maryland Operating Budget", "year": "fiscal_year", "value": "budget",
               "use": "Operating budget and actuals by agency, program and Comptroller spending code"},
    "fund": {"id": "gy87-e27x", "title": "Maryland Operating Budget - Funding Source", "year": "fiscal_year", "value": "budget",
             "use": "Operating budget by fund type and fund source"},
    "fte": {"id": "x8qy-486w", "title": "State of Maryland Full Time Equivalents", "year": "fiscal_year", "value": "count",
            "use": "Budgeted full-time-equivalent positions by agency and program"},
    "grants": {"id": "absk-avps", "title": "State of Maryland Grant and Loan Data", "year": "fiscalyear", "value": "amount",
               "use": "State grants and loans of $50,000 or more to non-government recipients"},
}


def portal_by_year(s):
    rows = soql(s["id"], select=f"{s['year']},count(*) as n,sum({s['value']}) as v", group=s["year"], order=s["year"])
    return {int(float(r[s["year"]])): (int(r["n"]), float(r.get("v") or 0)) for r in rows if r.get(s["year"])}


def local_by_year(df, s):
    v = pd.to_numeric(df[s["value"]], errors="coerce").fillna(0)
    y = pd.to_numeric(df[s["year"]], errors="coerce")
    g = pd.DataFrame({"y": y, "v": v}).dropna(subset=["y"]).groupby("y")
    return {int(k): (int(n), float(t)) for k, n, t in zip(g.size().index, g.size().values, g.v.sum().values)}


def matches(a, b):
    return a[0] == b[0] and abs(a[1] - b[1]) <= max(1.0, 1e-7 * abs(b[1]))


def meta(s):
    m = get(f"{DOMAIN}/api/views/{s['id']}.json").json()
    ts = m.get("rowsUpdatedAt")
    return {"portal_name": m.get("name"), "portal_updated": dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat() if ts else None}


def load(key, fresh=False, inject_fault=False):
    s = SOURCES[key]
    truth = portal_by_year(s)
    if "years" in s:  # FY2027 payments are partial and left out
        truth = {y: v for y, v in truth.items() if y in s["years"]}
    info = {"source": key, "dataset_id": s["id"], "title": s["title"], "use": s["use"], **meta(s)}
    if s.get("per_year_files"):
        frames = []
        for fy in s["years"]:
            path = RAW / f"fy{fy}.csv"
            for attempt in range(HEAL + 1):
                if fresh or not path.exists() or attempt > 0:
                    download_csv(s["id"], where=f"{s['year']}={fy}").to_csv(path, index=False)
                df = pd.read_csv(path, dtype=str, keep_default_na=False)
                if inject_fault and fy == 2015 and attempt == 0:
                    df = df.iloc[: len(df) // 2]
                got = local_by_year(df, s).get(fy, (0, 0.0))
                ok = matches(got, truth.get(fy, (0, 0.0)))
                if ok:
                    break
                RUN.repairs += 1
                RUN.event(f"{key} FY{fy} did not match the portal ({got[0]:,} vs {truth.get(fy, (0,))[0]:,} rows); downloading again")
            note = (" (test fault injected and repaired)" if inject_fault and fy == 2015 else " (repaired)") if attempt else ""
            RUN.check("raw", f"Payments FY{fy} match the portal", ok, f"{got[0]:,} rows, ${got[1]:,.0f}{note}")
            frames.append(df)
        df = pd.concat(frames, ignore_index=True)
    else:
        path = RAW / f"{s['id']}.csv"
        if fresh or not path.exists():
            download_csv(s["id"]).to_csv(path, index=False)
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        for attempt in range(HEAL + 1):
            got = local_by_year(df, s)
            bad = [y for y in truth if not matches(got.get(y, (0, 0.0)), truth[y])]
            if not bad:
                break
            RUN.repairs += 1
            RUN.event(f"{key}: years {bad} did not match the portal; downloading them again")
            keep = df[~pd.to_numeric(df[s["year"]], errors="coerce").isin(bad)]
            fresh_rows = download_csv(s["id"], where=f"{s['year']} in({','.join(map(str, bad))})")
            df = pd.concat([keep, fresh_rows], ignore_index=True)
            df.to_csv(path, index=False)
        n_api = sum(v[0] for v in truth.values())
        RUN.check("raw", f"{s['title']} ({s['id']}) matches the portal", not bad,
                  f"{len(df):,} of {n_api:,} rows across {len(truth)} years" + (f"; mismatched years {bad}" if bad else ""))
    info.update({"rows_portal": sum(v[0] for v in truth.values()), "rows_downloaded": len(df),
                 "years": f"FY{min(truth)}–FY{max(truth)}",
                 "reconciled": all(c["status"] == "pass" for c in RUN.checks if c["stage"] == "raw" and (s["title"] in c["check"] or (key == "payments" and c["check"].startswith("Payments FY"))))})
    return df, info
