"""Shared helpers for the GMI Savings Tracker pipeline: paths, HTTP with retries, run log and checks."""
import datetime as dt
import io
import json
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW, STAGED, MODEL, OUT = (ROOT / d for d in ("raw", "staged", "model", "out"))
for d in (RAW, STAGED, MODEL, OUT):
    d.mkdir(exist_ok=True)

DOMAIN = "https://opendata.maryland.gov"
RETRIES = 4
PAGE = 50000


class Run:
    """Collects checks and events for one pipeline run."""

    def __init__(self):
        self.started = dt.datetime.now(dt.timezone.utc)
        self.run_id = self.started.strftime("%Y%m%dT%H%M%SZ")
        self.checks, self.events, self.repairs = [], [], 0

    def check(self, stage, name, ok, detail, warn=False):
        status = "pass" if ok else ("warn" if warn else "fail")
        self.checks.append({"run_id": self.run_id, "stage": stage, "check": name, "status": status, "detail": detail})
        return ok

    def event(self, msg):
        self.events.append(f"{dt.datetime.now(dt.timezone.utc):%H:%M:%S} {msg}")

    @property
    def failed(self):
        return sum(c["status"] == "fail" for c in self.checks)


RUN = Run()


def get(url, params=None, timeout=180):
    """GET with exponential backoff; raises after RETRIES attempts."""
    for i in range(RETRIES):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:  # network or server error
            wait = 2 ** i
            RUN.event(f"retry {i + 1} {url} {params or ''}: {e}; waiting {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"gave up after {RETRIES} attempts: {url} {params}")


def soql(dataset, **params):
    return get(f"{DOMAIN}/resource/{dataset}.json", {f"${k}": v for k, v in params.items()}).json()


def download_csv(dataset, where=None, select=None):
    """Download a whole dataset (or a filtered part) as a DataFrame, paging by :id."""
    parts, off = [], 0
    while True:
        p = {"$order": ":id", "$limit": PAGE, "$offset": off}
        if where:
            p["$where"] = where
        if select:
            p["$select"] = select
        r = get(f"{DOMAIN}/resource/{dataset}.csv", p)
        df = pd.read_csv(io.StringIO(r.text), dtype=str, keep_default_na=False)
        parts.append(df)
        if len(df) < PAGE:
            break
        off += PAGE
    return pd.concat(parts, ignore_index=True)


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1, default=str))
