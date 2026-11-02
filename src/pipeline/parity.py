"""Phase 4 gate: compare every dashboard-file mart with the legacy pipeline's file.

    python -m src.pipeline.parity --legacy ../gst/out [--strict]

For each file: rows on each side, keys only on one side, missing columns, and for every shared numeric column the
rows that differ (money within $1; *_yoy within 0.0001, the legacy rounding; counts exactly). Results go to
docs/parity/summary.csv and docs/parity/differences.csv (up to 25 example rows per file and column) and are appended to
data/parity_history.csv (feedback loop). A difference is acceptable only once docs/parity/explanations.csv explains it;
--strict exits 1 while any file has an unexplained difference.
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "parity"
KEYS = {
    "totals_by_fy": ["fiscal_year"], "budget_by_function": ["fiscal_year", "category_title"], "budget_by_fund": ["fiscal_year", "fund_type_name"],
    "budget_by_object": ["fiscal_year", "object_name"], "spending_scope": ["fiscal_year", "scope"], "agency_year": ["agency_code", "fiscal_year"],
    "agency_master": ["agency_code"], "vendor_families": ["family"], "area_year": ["fiscal_year", "area"],
    "area_agency_year": ["fiscal_year", "area", "agency_code"], "area_code_year": ["fiscal_year", "area", "code"],
    "area_vendor_year": ["fiscal_year", "area", "vendor"], "f_function": ["fiscal_year", "agency_code", "category_title"],
    "f_object": ["fiscal_year", "agency_code", "object_name"], "f_scope": ["fiscal_year", "agency_code", "scope"],
    "f_fund": ["fiscal_year", "agency_code", "fund_type_name"], "f_code": ["fiscal_year", "agency_code", "area", "code"],
    "f_area": ["fiscal_year", "agency_code", "area"], "f_vendor": ["fiscal_year", "agency_code", "area", "vendor"],
    "f_agency": ["agency_code", "fiscal_year"], "d_agency": ["agency_code"],
}
COUNTS = {"payment_records", "agencies", "vendors", "codes", "payee_names", "payment_names"}


def norm_key(s):
    s = s.astype(str).str.strip().str.upper()
    return s.str.replace(r"\.0$", "", regex=True).str.replace(r"^0+(\d)", r"\1", regex=True).replace({"NAN": "", "NONE": "", "<NA>": ""})


def tol(col):
    return 1e-4 if col.endswith("_yoy") else 0.0 if col in COUNTS else 1.0


def compare(name, legacy, mart):
    k = KEYS[name]
    L, M = legacy.copy(), mart.copy()
    for d in (L, M):
        d["_k"] = norm_key(d[k[0]])
        for c in k[1:]:
            d["_k"] = d["_k"] + "|" + norm_key(d[c])
    dupL, dupM = int(L._k.duplicated().sum()), int(M._k.duplicated().sum())
    L, M = L.drop_duplicates("_k").set_index("_k"), M.drop_duplicates("_k").set_index("_k")
    only_l, only_m = L.index.difference(M.index), M.index.difference(L.index)
    both = L.index.intersection(M.index)
    num = [c for c in L.columns if c in M.columns and c not in k and pd.api.types.is_numeric_dtype(L[c]) and pd.api.types.is_numeric_dtype(M[c])]
    diffs, rows = {}, []
    for c in num:
        a, b = L.loc[both, c].astype(float), M.loc[both, c].astype(float)
        bad = ~(((a - b).abs() <= tol(c)) | (a.isna() & b.isna()))
        if bad.any():
            diffs[c] = int(bad.sum())
            ex = pd.DataFrame({"file": name, "key": a[bad].index, "column": c, "legacy": a[bad].values, "mart": b[bad].values})
            rows.append(ex.assign(diff=ex.mart - ex.legacy).reindex(ex["legacy"].sub(ex["mart"]).abs().sort_values(ascending=False).index).head(25))
    for side, idx, src in (("only in legacy", only_l, L), ("only in mart", only_m, M)):
        if len(idx):
            val = next((c for c in ("spend", "budget", "total_payments", "operating_spending", "payee_spend") if c in src.columns), None)
            rows.append(pd.DataFrame({"file": name, "key": idx[:25], "column": side, "legacy": src.loc[idx[:25], val].values if val and side == "only in legacy" else np.nan,
                                      "mart": src.loc[idx[:25], val].values if val and side == "only in mart" else np.nan}))
    summ = {"file": name, "legacy_rows": len(legacy), "mart_rows": len(mart), "keys_only_legacy": len(only_l), "keys_only_mart": len(only_m),
            "duplicate_keys": dupL + dupM, "missing_columns": ", ".join(c for c in legacy.columns if c not in mart.columns),
            "columns_differing": "; ".join(f"{c} ({n} rows)" for c, n in diffs.items())}
    summ["matches"] = not (len(only_l) or len(only_m) or diffs or summ["missing_columns"] or summ["duplicate_keys"])
    return summ, rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", required=True, help="folder with the legacy pipeline's CSV files")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    con = duckdb.connect(str(ROOT / "data" / "md_transparency.duckdb"), read_only=True)
    sums, rows = [], []
    for name in KEYS:
        f = Path(a.legacy) / f"{name}.csv"
        if not f.exists():
            sums.append({"file": name, "matches": False, "missing_columns": "legacy file not found"})
            continue
        s, r = compare(name, pd.read_csv(f, low_memory=False), con.execute(f"SELECT * FROM mart.{name}").df())
        sums.append(s)
        rows += r
    con.close()
    OUT.mkdir(parents=True, exist_ok=True)
    summ = pd.DataFrame(sums)
    ex_path = OUT / "explanations.csv"
    ex = pd.read_csv(ex_path) if ex_path.exists() else pd.DataFrame(columns=["file", "explanation", "source"])
    summ["explained"] = summ.file.isin(ex.file)
    summ["status"] = np.where(summ.matches, "reproduced", np.where(summ.explained, "difference explained", "difference to explain"))
    summ.to_csv(OUT / "summary.csv", index=False)
    (pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["file", "key", "column", "legacy", "mart", "diff"])).to_csv(OUT / "differences.csv", index=False)
    hist = ROOT / "data" / "parity_history.csv"
    summ[["file", "status", "keys_only_legacy", "keys_only_mart", "columns_differing"]].assign(
        checked_utc=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")).to_csv(hist, mode="a", header=not hist.exists(), index=False)
    for r in summ.itertuples():
        print(f"{r.status:22s} {r.file:20s} legacy {r.legacy_rows!s:>6} mart {r.mart_rows!s:>6}  only-legacy {r.keys_only_legacy!s:>4} only-mart {r.keys_only_mart!s:>4}  {r.missing_columns or ''} {r.columns_differing or ''}")
    open_ = int((summ.status == "difference to explain").sum())
    print(f"parity: {int(summ.matches.sum())} of {len(summ)} reproduced; {open_} to explain")
    return 1 if a.strict and open_ else 0


if __name__ == "__main__":
    sys.exit(main())
