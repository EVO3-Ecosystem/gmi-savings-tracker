"""Phase 5 gate: compare the 44-file dashboard export with the CSVs the original pipeline published.

    python -m src.pipeline.parity_published [--export data/export/latest] [--legacy legacy/gst/out]

For each of the 30 exports that has a legacy file of the same name (legacy/README.md), rows are matched on the file's
key (its grain, KEYS below; keys are normalised as in parity.py: trimmed, upper case, leading zeros and a trailing ".0"
dropped, an empty part kept as ""). Column order and row order do not matter. Every shared non-key column is compared cell by cell:

- numeric on both sides: equal within $0.01 for money, 1e-5 for ratios (a name ending in one of RATIO, the export's
  5-decimal columns), exactly for integer columns; empty equals empty;
- otherwise as trimmed text; empty equals empty.

A column on one side only, a key on one side only, a duplicate key and every column with a differing cell are each a
*difference aspect* ("rows_only_legacy", "rows_only_export", "column_only_legacy:<col>", "column_only_export:<col>",
"cells:<col>", "duplicate_keys"). A file is "equivalent" with no aspects, "difference explained" when every aspect is
listed in the `covers` column of its row in docs/parity/published_explanations.csv, and "difference to explain"
otherwise; the uncovered aspects are printed and written to the summary, never hidden. A reviewed explanation therefore
stops covering a file as soon as a new kind of difference appears in it.

The 14 exports with no legacy file are listed as "no legacy counterpart" with the test or check that covers each
(NO_COUNTERPART). Output: docs/parity/published_summary.csv (one row per file) and published_differences.csv (up to
SAMPLE differing rows per file and aspect). Exit 1 while any file is unexplained.

    python -m src.pipeline.parity_published --crosschecks     # the State-site cross-checks (needs network)

ports the original pipeline's independent cross-checks (legacy/gst/scripts/run.py): the budget total for FY2025-FY2027
against operatingbudget.maryland.gov and payments for FY2024-FY2026 (plus the partial FY2027) against
vendorpayments.maryland.gov, each within $10, and the DBM Governor's budget Volume 2 program comparison (FY2021 from the
FY2023 book, FY2022 from the FY2024 book; more than 60% of programs equal to the dollar). The legacy pipeline read the
program comparison from its stored evidence; here the books are downloaded and parsed again (pdftotext -raw, cached in
data/crosscheck/). A host that cannot be reached is recorded as "unreachable from build environment" and the check
stays open; it is never passed. Output: docs/reconciliation/crosschecks_<date>.csv; exit 1 unless every check passed.
"""
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from .parity import norm_key as _base_norm_key

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "parity"
RATIO = ("_yoy", "_rate", "_mape", "_share", "growth", "share", "progress")
MONEY_TOL, RATIO_TOL = 0.01, 1e-5
SAMPLE = 10

# Grain of each published file (the columns that identify a row)
KEYS = {
    "agency_master": ["agency_code"], "d_agency": ["agency_code"], "d_bid_list": ["vendor"], "d_forecast_model": ["area"],
    "d_master_quality": ["measure"], "d_opps": ["detector", "agency_code", "area", "spending_code"], "d_plan50": ["step"],
    "d_rec_status": ["rec"], "d_savings": ["saving_id"], "d_savings_status": ["check_id"], "d_vendor_moves": ["vendor"],
    "d_vendor_names": ["vendor", "payee_name"], "f_agency": ["agency_code", "fiscal_year"], "f_area": ["fiscal_year", "agency_code", "area"],
    "f_code": ["fiscal_year", "agency_code", "area", "code"], "f_forecast": ["area", "fiscal_year", "kind"],
    "f_function": ["fiscal_year", "agency_code", "category_title"], "f_fund": ["fiscal_year", "agency_code", "fund_type_name"],
    "f_object": ["fiscal_year", "agency_code", "object_name"], "f_savings_check": ["check_id", "fiscal_year", "agency_code"],
    "f_scope": ["fiscal_year", "agency_code", "scope"], "f_vendor": ["fiscal_year", "agency_code", "area", "vendor"],
    "f_vendor_detail": ["vendor", "agency_code", "fiscal_year"], "measures": ["table", "measure"], "pipeline_runs": ["run_id"],
    "run_checks": ["run_id", "stage", "check"], "sources": ["source"], "stage_evidence": ["fiscal_year", "evidence_url"],
    "totals_by_fy": ["fiscal_year"], "vendor_families": ["family"],
}

# Exports added after the original pipeline (legacy/README.md): what checks each instead of a legacy file. "Build check"
# names a check in src/pipeline/checks.py (run by make build); "page tests" are the dashboard's 34 tests run by preview.py.
NO_COUNTERPART = {
    "d_vendors": "build check 'Vendors tab: vendor pages add up to the vendor list (FY2026)'; build check 'Every vendor has a payee type'; page tests",
    "f_vendor_pay": "build check 'Vendors tab: vendor pages add up to the vendor list (FY2026)'; page tests",
    "f_payee_type": "build check 'Vendors tab: payments by payee type = core payments (every year)'; page tests",
    "f_vendor_year": "page tests only (loaded by the page; no total check of its own): gap",
    "d_multi": "build checks 'Vendors tab: every multi-agency vendor is paid by 15+ agencies' and '15+ agency count on both bases (FY2026)'; page tests",
    "d_multi_basis": "build check 'Vendors tab: 15+ agency count on both bases (FY2026)'; page tests",
    "f_concentration": "tests/test_concentration.py (HHI and top-5 share on constructed cases); build checks 'concentration shares and HHI within bounds' and "
                       "'concentration spend = private focus-area payments (every area and year)'; page tests",
    "d_area_top": "page tests only (Vendors tab table; no total check of its own): gap",
    "d_families": "build check 'Vendors tab: every company listed has two or more payee names'; vendor_families parity (this gate); page tests",
    "f_budget_vs_pay": "build check 'Budget vs payments: budget and payments = core totals (every year)'; page tests",
    "f_fund_source": "build check 'Where it's going = how it's funded (budget by program = budget by fund source, every year)'; page tests",
    "f_program": "build check 'Where it's going = how it's funded (budget by program = budget by fund source, every year)'; DBM Volume 2 cross-check; page tests",
    "f_grants": "build check 'Grants as listed = core grants (rows and dollars, every year)'; page tests",
    "f_overlap": "build check 'Grants whose grantee is also a payee that year (name match)'; page tests",
}


def tolerance(col, a, b):
    """Allowed absolute difference for a numeric column."""
    if col.endswith(RATIO):
        return RATIO_TOL
    if pd.api.types.is_integer_dtype(a) and pd.api.types.is_integer_dtype(b):
        return 0.0
    return MONEY_TOL


def _numeric(s):
    """The column as floats if every non-empty value is a number, else None."""
    if pd.api.types.is_bool_dtype(s):
        return s.astype(float)
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)
    t = s.astype("string").str.strip().replace({"True": "1", "False": "0", "true": "1", "false": "0"})
    n = pd.to_numeric(t, errors="coerce")
    return n.astype(float) if (n.notna() | t.isna() | (t == "")).all() else None


def _text(s):
    t = s.astype("string").str.strip()
    return t.fillna("").replace({"nan": "", "None": "", "<NA>": ""})


def norm_key(s):
    """parity.norm_key, with an empty key part kept as "" (pandas 3 keeps NaN through astype(str), which would make the whole key NaN)."""
    return _base_norm_key(s.astype(object).where(s.notna(), "")).fillna("")


def _keyed(df, keys):
    d = df.copy()
    d["_k"] = norm_key(d[keys[0]])
    for c in keys[1:]:
        d["_k"] = d["_k"] + "|" + norm_key(d[c])
    return d


def compare(name, legacy, export, keys):
    """Compare one file. Returns (summary dict, set of difference aspects, DataFrame of sample differing rows)."""
    L, E = _keyed(legacy, keys), _keyed(export, keys)
    dup = int(L._k.duplicated().sum() + E._k.duplicated().sum())
    L, E = L.drop_duplicates("_k").set_index("_k"), E.drop_duplicates("_k").set_index("_k")
    both = L.index.intersection(E.index)
    only_l, only_e = L.index.difference(E.index), E.index.difference(L.index)
    cols_l = [c for c in legacy.columns if c not in export.columns]
    cols_e = [c for c in export.columns if c not in legacy.columns]
    shared = [c for c in legacy.columns if c in export.columns and c not in keys]
    aspects, samples, per_col = set(), [], {}
    max_diff, max_col, cells = 0.0, "", 0
    for c in shared:
        a, b = L.loc[both, c], E.loc[both, c]
        na, nb = _numeric(a), _numeric(b)
        if na is not None and nb is not None:
            d = (na - nb).abs()
            bad = ~((d <= tolerance(c, a, b) + 1e-9) | (na.isna() & nb.isna()))
            if bad.any() and d[bad].notna().any():
                m = float(d[bad].max())
                if m > max_diff:
                    max_diff, max_col = m, c
        else:
            bad = _text(a) != _text(b)
        n = int(bad.sum())
        if n:
            per_col[c] = n
            cells += n
            aspects.add(f"cells:{c}")
            ex = pd.DataFrame({"file": name, "key": a[bad].index, "aspect": f"cells:{c}", "legacy": a[bad].astype(str).values, "export": b[bad].astype(str).values})
            if na is not None and nb is not None:
                ex["abs_diff"] = d[bad].values
                ex = ex.sort_values("abs_diff", ascending=False, na_position="first")
            samples.append(ex.head(SAMPLE))
    for side, idx in (("rows_only_legacy", only_l), ("rows_only_export", only_e)):
        if len(idx):
            aspects.add(side)
            samples.append(pd.DataFrame({"file": name, "key": idx[:SAMPLE], "aspect": side}))
    aspects |= {f"column_only_legacy:{c}" for c in cols_l} | {f"column_only_export:{c}" for c in cols_e}
    if dup:
        aspects.add("duplicate_keys")
    summ = {"file": name, "keys": "+".join(keys), "legacy_rows": len(legacy), "export_rows": len(export), "matched_keys": len(both),
            "keys_only_legacy": len(only_l), "keys_only_export": len(only_e), "duplicate_keys": dup,
            "columns_only_legacy": ", ".join(cols_l), "columns_only_export": ", ".join(cols_e),
            "cells_compared": len(both) * len(shared), "cells_differing": cells,
            "columns_differing": "; ".join(f"{c} ({n})" for c, n in per_col.items()),
            "max_abs_diff": round(max_diff, 6) if max_col else np.nan, "max_abs_diff_column": max_col}
    return summ, aspects, (pd.concat(samples, ignore_index=True) if samples else pd.DataFrame())


def classify(aspects, covers):
    """Status and the aspects an explanation does not cover. covers: set of aspects, or None when there is no explanation."""
    if not aspects:
        return "equivalent", []
    if covers is None:
        return "difference to explain", sorted(aspects)
    left = sorted(a for a in aspects if a not in covers and "*" not in covers)
    return ("difference explained" if not left else "difference to explain"), left


def load_explanations(path):
    if not Path(path).exists():
        return {}
    ex = pd.read_csv(path)
    return {r.file: {a.strip() for a in str(r.covers).split(";") if a.strip()} for r in ex.itertuples()}


def run(export_dir, legacy_dir, explanations):
    sums, diffs = [], []
    files = sorted(p.stem for p in Path(export_dir).glob("*.csv") if p.stem != "manifest")
    for name in files:
        lf = Path(legacy_dir) / f"{name}.csv"
        if not lf.exists():
            sums.append({"file": name, "status": "no legacy counterpart", "covered_by": NO_COUNTERPART.get(name, "")})
            continue
        if name not in KEYS:
            sums.append({"file": name, "status": "difference to explain", "uncovered": "no key defined for this file"})
            continue
        s, aspects, d = compare(name, pd.read_csv(lf, low_memory=False), pd.read_csv(Path(export_dir) / f"{name}.csv", low_memory=False), KEYS[name])
        s["status"], left = classify(aspects, explanations.get(name))
        s["aspects"], s["uncovered"] = "; ".join(sorted(aspects)), "; ".join(left)
        sums.append(s)
        if len(d):
            diffs.append(d)
    for name in NO_COUNTERPART:
        if name not in files:
            sums.append({"file": name, "status": "missing from export", "covered_by": NO_COUNTERPART[name]})
    cols = ["file", "status", "keys", "legacy_rows", "export_rows", "matched_keys", "keys_only_legacy", "keys_only_export", "duplicate_keys",
            "columns_only_legacy", "columns_only_export", "cells_compared", "cells_differing", "columns_differing", "max_abs_diff",
            "max_abs_diff_column", "aspects", "uncovered", "covered_by"]
    summ = pd.DataFrame(sums).reindex(columns=cols)
    for c in ("legacy_rows", "export_rows", "matched_keys", "keys_only_legacy", "keys_only_export", "duplicate_keys", "cells_compared", "cells_differing"):
        summ[c] = summ[c].astype("Int64")
    dcols = ["file", "key", "aspect", "legacy", "export", "abs_diff"]
    diff = pd.concat(diffs, ignore_index=True).reindex(columns=dcols) if diffs else pd.DataFrame(columns=dcols)
    return summ, diff


# ---------------------------------------------------------------- independent cross-checks against the State's own sites
SITE_TOL = 10.0
BUDGET_URL = "https://operatingbudget.maryland.gov/api/opex/totals.json?year={y}"
PAY_URL = "https://vendorpayments.maryland.gov/api/opex/totals.json?year={y}"
BOOKS = {2021: "https://dbm.maryland.gov/budget/Documents/operbudget/2023/proposed/FY2023-Volume2.pdf",
         2022: "https://dbm.maryland.gov/budget/Documents/operbudget/2024/proposed/FY2024-Volume2.pdf"}
MIN_EXACT = 0.6
UNREACHABLE = "unreachable from build environment"
PROG = re.compile(r"^([A-Z]\d{2}[A-Z]\d{2}\.\d{2})\s+\S")
TOTAL = re.compile(r"^Total Expenditure\s+(-?[\d,]+)\s+(-?[\d,]+)\s+(-?[\d,]+)$")


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "gmi-savings-tracker crosscheck"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def site_status(site, ours, tol=SITE_TOL):
    """pass / fail for a site total against the pipeline's total; an unreachable site never passes."""
    if site is None:
        return UNREACHABLE
    return "pass" if abs(site - ours) <= tol else "fail"


def parse_programs(text):
    """Program code -> the first column (the Actual year) of its first 'Total Expenditure' line, from pdftotext -raw output of a Volume 2 book."""
    out, cur = {}, None
    for line in text.splitlines():
        line = line.strip()
        if PROG.match(line):
            cur = line.split()[0]
            continue
        m = TOTAL.match(line)
        if m and cur:
            out.setdefault(cur, float(m.group(1).replace(",", "")))
            cur = None
    return out


def program_match(book, db):
    """Compare the book's program actuals with the database's totals (dicts program -> dollars). Returns (compared, equal to the dollar)."""
    both = [k for k in book if k in db]
    return len(both), sum(abs(book[k] - db[k]) <= 0.5 for k in both)


def crosschecks(con, cache):
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    rows = []

    def row(check, host, url, fy, site, ours, status, detail=""):
        diff = (ours - site) if site is not None and ours is not None else None
        rows.append({"checked_utc": today, "check": check, "host": host, "url": url, "fiscal_year": fy, "site_total": site, "pipeline_total": ours,
                     "difference": diff, "status": status, "detail": detail})

    bud = dict(con.execute("SELECT fiscal_year, sum(budget) FROM core.fact_budget GROUP BY 1").fetchall())
    pay = dict(con.execute("SELECT fiscal_year, sum(amount) FROM core.fact_payment GROUP BY 1").fetchall())
    partial = {r[0] for r in con.execute("SELECT DISTINCT fiscal_year FROM core.fact_payment WHERE partial_year").fetchall()}
    run_id = con.execute("SELECT max(run_id) FROM ops.run_log").fetchone()[0]
    for name, host, url, years, ours in (("budget", "operatingbudget.maryland.gov", BUDGET_URL, (2025, 2026, 2027), bud),
                                         ("payments", "vendorpayments.maryland.gov", PAY_URL, (2024, 2025, 2026, 2027), pay)):
        for y in years:
            verb = "matches" if name == "budget" else "match"
            check, u, mine = f"FY{y} {name} {verb} {host} (within ${SITE_TOL:,.0f})", url.format(y=y), float(ours.get(y, 0.0))
            try:
                site = float(json.loads(_get(u))[0]["amount"])
            except Exception as e:  # noqa: BLE001
                row(check, host, u, y, None, mine, UNREACHABLE, f"{type(e).__name__}: {e}"[:200])
                continue
            note = f"database extract {run_id}" + ("; partial year: the site can move ahead of the extract until the year closes" if name == "payments" and y in partial else "")
            row(check, host, u, y, site, mine, site_status(site, mine), note)
    stored = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT fiscal_year, programs_compared, programs_exact FROM mart.stage_evidence WHERE programs_compared IS NOT NULL").fetchall()}
    for fy, url in BOOKS.items():
        check, host = f"FY{fy} programs match DBM's published actuals (Governor's budget Volume 2, more than {MIN_EXACT:.0%} equal)", "dbm.maryland.gov"
        pdf = Path(cache) / url.rsplit("/", 1)[1]
        try:
            if not pdf.exists():
                pdf.parent.mkdir(parents=True, exist_ok=True)
                pdf.write_bytes(_get(url, timeout=300))
        except Exception as e:  # noqa: BLE001
            row(check, host, url, fy, None, None, UNREACHABLE, f"{type(e).__name__}: {e}"[:200])
            continue
        if not shutil.which("pdftotext"):
            row(check, host, url, fy, None, None, "not run", "pdftotext (poppler) is not installed")
            continue
        text = subprocess.run(["pdftotext", "-raw", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
        db = dict(con.execute("SELECT agency_code || unit_code || '.' || program_code, sum(budget) FROM core.fact_budget WHERE fiscal_year = ? GROUP BY 1",
                              [fy]).fetchall())
        n, exact = program_match(parse_programs(text), db)
        s = stored.get(fy)
        row(check, host, url, fy, None, None, "pass" if n and exact / n > MIN_EXACT else "fail",
            f"{exact} of {n} programs equal to the dollar ({exact / n:.1%})" + (f"; stored evidence (legacy parse): {int(s[1])} of {int(s[0])}" if s else ""))
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", default=str(ROOT / "data" / "export" / "latest"))
    ap.add_argument("--legacy", default=str(ROOT / "legacy" / "gst" / "out"))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--crosschecks", action="store_true", help="run the State-site cross-checks instead of the file comparison")
    a = ap.parse_args(argv)
    if a.crosschecks:
        import duckdb
        con = duckdb.connect(str(ROOT / "data" / "md_transparency.duckdb"), read_only=True)
        res = crosschecks(con, ROOT / "data" / "crosscheck")
        con.close()
        path = ROOT / "docs" / "reconciliation" / f"crosschecks_{dt.datetime.now(dt.timezone.utc):%Y-%m-%d}.csv"
        res.to_csv(path, index=False)
        for r in res.itertuples():
            print(f"{r.status:34s} {r.check:95s} {r.detail}")
        print(f"cross-checks: {int((res.status == 'pass').sum())} of {len(res)} passed; written to {path}")
        return 0 if (res.status == "pass").all() else 1
    out = Path(a.out)
    summ, diff = run(a.export, a.legacy, load_explanations(out / "published_explanations.csv"))
    out.mkdir(parents=True, exist_ok=True)
    summ.to_csv(out / "published_summary.csv", index=False)
    diff.to_csv(out / "published_differences.csv", index=False)
    for r in summ.itertuples():
        extra = f"  uncovered: {r.uncovered}" if isinstance(r.uncovered, str) and r.uncovered else ""
        print(f"{r.status:22s} {r.file:18s} legacy {r.legacy_rows!s:>6} export {r.export_rows!s:>6} matched {r.matched_keys!s:>6} cells differing {r.cells_differing!s:>6}{extra}")
    st = summ.status.value_counts()
    open_ = int(st.get("difference to explain", 0) + st.get("missing from export", 0))
    print(f"published parity: {int(st.get('equivalent', 0))} equivalent, {int(st.get('difference explained', 0))} explained, "
          f"{int(st.get('difference to explain', 0))} to explain, {int(st.get('no legacy counterpart', 0))} without a legacy file")
    return 1 if open_ else 0


if __name__ == "__main__":
    sys.exit(main())
