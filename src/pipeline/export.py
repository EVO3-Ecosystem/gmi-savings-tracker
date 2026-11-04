"""Phase 4: write the dashboard's data files from the marts.

    python -m src.pipeline.export [--carry ../gst/out]

Writes one CSV per dashboard dataset (config/dashboard.yaml) to data/export/<run_id>/ and points data/export/latest at
it. Files that have a mart come from the database, with the legacy file's column order and rounding (money to the
cent, shares and changes to 5 decimals). Files that don't have a mart yet (the Phase 5 analytics and the pipeline's own
run files) are copied from --carry and marked "carried" in manifest.csv, so the dashboard can be previewed whole while
Phase 5 is under way. Feedback loop: manifest.csv also records, per file, rows and whether it changed since the last
export (the roadmap's "exported files differ from last run" report).
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "data" / "export"
RATIO = ("_yoy", "_rate", "_mape", "_share", "growth", "share")
# Payment columns held back for a partial payments year until the page labels partial years (config: hold_partial_payments)
PARTIAL = {"totals_by_fy": "drop", "f_vendor": "drop", "f_payee_type": "drop", "f_vendor_year": "drop", "f_area": ["payee_spend"], "f_agency": ["payments"]}


def _round(df):
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].round(5 if c.endswith(RATIO) else 2)
    return df


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--carry", help="folder with the legacy files for datasets that have no mart yet")
    a = ap.parse_args(argv)
    files = sorted(set(v for v in yaml.safe_load((ROOT / "config" / "dashboard.yaml").read_text()).values()))
    con = duckdb.connect(str(ROOT / "data" / "md_transparency.duckdb"), read_only=True)
    run_id = con.execute("SELECT max(run_id) FROM ops.run_log").fetchone()[0]
    hold = True  # hold_partial_payments: the page has no partial-year label yet
    full = con.execute("SELECT max(fiscal_year) FROM core.fact_payment WHERE NOT partial_year").fetchone()[0]
    marts = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'mart'").fetchall()}
    out = EXP / run_id
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    prev = json.loads((EXP / "latest.json").read_text()) if (EXP / "latest.json").exists() else {}
    rows = []
    for name in files:
        carry = Path(a.carry) / f"{name}.csv" if a.carry else None
        if name in marts:
            df = con.execute(f"SELECT * FROM mart.{name}").df()
            if hold and name in PARTIAL:
                rule = PARTIAL[name]
                if rule == "drop":
                    df = df[df.fiscal_year <= full]
                else:
                    df.loc[df.fiscal_year > full, rule] = None
                    if name == "f_area":
                        df = df[~((df.fiscal_year > full) & df.spend.isna())]
            if carry and carry.exists():  # keep the dashboard's column order
                cols = list(pd.read_csv(carry, nrows=0).columns)
                df = df[[c for c in cols if c in df.columns] + [c for c in df.columns if c not in cols]]
            _round(df).to_csv(out / f"{name}.csv", index=False)
            src = "mart"
        elif carry and carry.exists():
            shutil.copy(carry, out / f"{name}.csv")
            src = "carried (no mart yet)"
        else:
            rows.append({"file": name, "source": "missing", "rows": 0, "changed": None})
            continue
        h = hashlib.sha256((out / f"{name}.csv").read_bytes()).hexdigest()[:16]
        rows.append({"file": name, "source": src, "rows": sum(1 for _ in open(out / f"{name}.csv")) - 1, "sha": h,
                     "changed": (h != prev.get(name)) if prev else None})
    con.close()
    man = pd.DataFrame(rows)
    man.to_csv(out / "manifest.csv", index=False)
    (EXP / "latest.json").write_text(json.dumps({r["file"]: r.get("sha") for r in rows}))
    latest = EXP / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(out.name)
    print(man.groupby("source").file.count().to_string())
    miss = man[man.source == "missing"].file.tolist()
    print(f"export: {len(man) - len(miss)} files to {out}" + (f"; missing: {miss}" if miss else ""))
    return 1 if miss else 0


if __name__ == "__main__":
    sys.exit(main())
