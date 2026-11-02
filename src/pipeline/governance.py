"""Data governance: schemas for every table, from the sources themselves, plus drift and coverage checks.

    python -m src.pipeline.governance [--dashboard ../gst/out] [--strict]

1. Source schemas come from the Socrata Discovery API (api/catalog/v1?ids=...): each dataset's columns, types, portal
   descriptions, owner, licence, update dates. If the API cannot be reached, the last saved snapshot is reused and the
   document says so (self-healing).
2. Warehouse schemas come from DuckDB's information_schema, with row counts.
3. Dashboard schemas come from the published CSVs (when --dashboard is given; otherwise the saved list is kept).
4. Every column gets its definition from reference/column_dictionary.csv. Columns without one are listed.
5. Feedback loop: the catalog snapshot is compared with the previous one; added, removed or retyped columns and changed
   titles are reported and appended to docs/schemas/drift_history.csv. --strict exits 1 on drift or gaps.
Generated sections of docs/data-governance.md sit between <!-- gen:NAME --> and <!-- /gen:NAME --> markers.
"""
import argparse
import datetime as dt
import fnmatch
import json
import re
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCH = ROOT / "docs" / "schemas"
DOC = ROOT / "docs" / "data-governance.md"
DB = ROOT / "data" / "md_transparency.duckdb"
DICT = ROOT / "reference" / "column_dictionary.csv"
SNAP = SCH / "catalog_snapshot.json"


def catalog(cfg):
    ids = ",".join(d["id"] for d in cfg["datasets"].values())
    url = f"https://{cfg['domain']}/api/catalog/v1"
    err = "incomplete result"
    for attempt in range(3):
        try:
            r = requests.get(url, params={"ids": ids}, timeout=60)
            r.raise_for_status()
            res = r.json()["results"]
            if len(res) == len(cfg["datasets"]):
                return res, f"Discovery API, read {dt.date.today():%b %d, %Y}"
        except Exception as e:  # noqa: BLE001 - any failure falls back to the snapshot
            err = e
        time.sleep(2 ** attempt)
    if SNAP.exists():
        return json.loads(SNAP.read_text())["results"], f"saved snapshot (Discovery API unreachable: {err})"
    raise SystemExit("Discovery API unreachable and no saved snapshot")


def define(dic, table, col):
    got = _define(dic, table, col)
    if not got[0] and table.startswith("mart."):  # a dashboard-file mart reuses that file's definitions
        got = _define(dic, table[5:], col)
    if not got[0]:  # the one change measure (legacy measures.yoy, src/pipeline/marts.py)
        for suf, text in (("_prior", "{b} in the previous fiscal year for the same keys"), ("_yoy", "Change in {b} from the previous fiscal year, as a share of the previous year (blank when that year is missing or zero)")):
            if col.endswith(suf):
                return text.format(b=col[: -len(suf)]), "derived"
        if col == "stage_pair":
            return "Stages compared by the change, e.g. 'Actual vs Actual' or 'Working budget vs Actual'", "derived"
    return got


def _define(dic, table, col):
    rows = dic[dic.column == col]
    for _, r in rows.iterrows():
        if r.applies_to and any(fnmatch.fnmatch(table, p.strip()) for p in r.applies_to.split(",")):
            return r.definition, r.origin
    g = rows[rows.applies_to == ""]
    return (g.definition.iloc[0], g.origin.iloc[0]) if len(g) else ("", "")


def drift(old, new):
    o = {r["resource"]["id"]: r for r in old}
    out = []
    for r in new:
        R, i = r["resource"], r["resource"]["id"]
        if i not in o:
            out.append((i, "dataset", "new in catalog"))
            continue
        P = o[i]["resource"]
        a, b = dict(zip(P["columns_field_name"], P["columns_datatype"])), dict(zip(R["columns_field_name"], R["columns_datatype"]))
        out += [(i, c, "column added") for c in b.keys() - a.keys()]
        out += [(i, c, "column removed") for c in a.keys() - b.keys()]
        out += [(i, c, f"type {a[c]} -> {b[c]}") for c in a.keys() & b.keys() if a[c] != b[c]]
        if P["name"] != R["name"]:
            out.append((i, "title", f"'{P['name']}' -> '{R['name']}'"))
    return out


def md(df):
    cols = list(df.columns)
    esc = lambda v: "" if pd.isna(v) else str(v).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + ["| " + " | ".join(esc(v) for v in r) + " |" for r in df.itertuples(index=False)])


def put(doc, name, body):
    pat = re.compile(rf"(<!-- gen:{name} -->)(.*?)(<!-- /gen:{name} -->)", re.S)
    if not pat.search(doc):
        raise SystemExit(f"marker gen:{name} missing from {DOC.name}")
    return pat.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", doc)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", help="folder of published dashboard CSVs")
    ap.add_argument("--strict", action="store_true", help="exit 1 on schema drift or undocumented columns")
    a = ap.parse_args(argv)
    SCH.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "config" / "datasets.yaml").read_text())
    short = {d["id"]: k for k, d in cfg["datasets"].items()}
    dic = pd.read_csv(DICT, dtype=str).fillna("")

    # 1. sources
    res, how = catalog(cfg)
    changes = drift(json.loads(SNAP.read_text())["results"], res) if SNAP.exists() else []
    if how.startswith("Discovery"):
        SNAP.write_text(json.dumps({"read": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "results": res}, indent=1))
    reg, src = [], []
    for r in sorted(res, key=lambda r: short[r["resource"]["id"]]):
        R, M, C = r["resource"], r["metadata"], r["classification"]
        meta = {m["key"]: m["value"] for m in C.get("domain_metadata", [])}
        reg.append({"dataset": short[R["id"]], "id": f"[{R['id']}]({r['permalink']})", "portal title": R["name"], "publisher": R.get("attribution"),
                    "maintained by": meta.get("Agency_State-Agency-Performing-Data-Updates"), "licence": M.get("license"),
                    "update frequency": meta.get("Time-Period_Update-Frequency"), "period (portal)": meta.get("Time-Period_Time-Period-of-Content"),
                    "data updated": R["data_updated_at"][:10], "columns": len(R["columns_field_name"])})
        for f, n, t, d in zip(R["columns_field_name"], R["columns_name"], R["columns_datatype"], R["columns_description"]):
            de, _ = define(dic, f"raw.{short[R['id']]}", f)
            src.append({"dataset": short[R["id"]], "dataset_id": R["id"], "field_name": f, "display_name": n, "datatype": t,
                        "portal_description": d or "(none)", "definition": de})
    src = pd.DataFrame(src)
    src.to_csv(SCH / "source_columns.csv", index=False)

    # 2. warehouse
    con = duckdb.connect(str(DB), read_only=True)
    wh = con.execute("select table_schema||'.'||table_name t, column_name c, data_type ty, ordinal_position o from information_schema.columns "
                     "where table_schema in ('raw','ref','core','mart','ops') order by 1, 4").df()
    nrows = {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in wh.t.unique()}
    con.close()
    wh = pd.DataFrame([{"table": r.t, "column": r.c, "type": r.ty, "table_rows": nrows[r.t], **dict(zip(("definition", "origin"), define(dic, r.t, r.c)))}
                       for r in wh.itertuples()])
    wh.to_csv(SCH / "warehouse_columns.csv", index=False)

    # 3. dashboard
    dpath = SCH / "dashboard_columns.csv"
    if a.dashboard:
        rows = []
        pub = yaml.safe_load((ROOT / "config" / "dashboard.yaml").read_text())
        missing = [v for v in pub.values() if not (Path(a.dashboard) / f"{v}.csv").exists()]
        if missing:
            raise SystemExit(f"published dashboard files missing: {missing}")
        for f in sorted(Path(a.dashboard) / f"{v}.csv" for v in set(pub.values())):
            d = pd.read_csv(f, low_memory=False)
            for c in d.columns:
                ty = "number" if pd.api.types.is_numeric_dtype(d[c]) else "boolean" if d[c].dropna().astype(str).isin(["True", "False"]).all() and d[c].notna().any() else "text"
                de, og = define(dic, f.stem, c)
                rows.append({"table": f.stem, "column": c, "type": ty, "table_rows": len(d), "definition": de, "origin": og})
        pd.DataFrame(rows).to_csv(dpath, index=False)
    db = pd.read_csv(dpath).fillna("") if dpath.exists() else pd.DataFrame(columns=["table", "column", "type", "table_rows", "definition", "origin"])

    # 4. coverage
    gaps = pd.concat([src.assign(table="raw." + src.dataset, column=src.field_name)[["table", "column", "definition"]],
                      wh[["table", "column", "definition"]], db[["table", "column", "definition"]]])
    gaps = gaps[gaps.definition == ""][["table", "column"]]
    total = len(src) + len(wh) + len(db)

    # 5. drift history
    hist = SCH / "drift_history.csv"
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    if changes:
        pd.DataFrame(changes, columns=["dataset_id", "item", "change"]).assign(seen_utc=now).to_csv(hist, mode="a", header=not hist.exists(), index=False)

    # write the document
    doc = DOC.read_text()
    doc = put(doc, "stamp", f"_Generated {now} by `python -m src.pipeline.governance`. Source schemas from the {how}._")
    doc = put(doc, "registry", md(pd.DataFrame(reg)))
    doc = put(doc, "sources", "\n\n".join(f"**{k}** ({g.dataset_id.iloc[0]}, {len(g)} columns)\n\n" + md(g[["field_name", "display_name", "datatype", "portal_description", "definition"]])
                                         for k, g in src.groupby("dataset", sort=True)))
    doc = put(doc, "warehouse", "\n\n".join(f"**{t}** ({g.table_rows.iloc[0]:,} rows)\n\n" + md(g[["column", "type", "origin", "definition"]]) for t, g in wh.groupby("table", sort=True)))
    doc = put(doc, "dashboard", "\n\n".join(f"**{t}** ({int(g.table_rows.iloc[0]):,} rows)\n\n" + md(g[["column", "type", "origin", "definition"]]) for t, g in db.groupby("table", sort=True))
              if len(db) else "_No dashboard schema recorded yet; run with `--dashboard`._")
    doc = put(doc, "coverage", f"{total - len(gaps):,} of {total:,} columns documented ({len(src)} source, {len(wh)} warehouse, {len(db)} dashboard)."
              + ("" if gaps.empty else "\n\nMissing a definition:\n\n" + md(gaps)))
    doc = put(doc, "drift", "No change in source schemas since the last snapshot." if not changes else md(pd.DataFrame(changes, columns=["dataset_id", "item", "change"])))
    DOC.write_text(doc)
    print(f"governance: {total - len(gaps)}/{total} columns documented; {len(changes)} schema changes; sources from {how}")
    return 1 if a.strict and (changes or not gaps.empty) else 0


if __name__ == "__main__":
    sys.exit(main())
