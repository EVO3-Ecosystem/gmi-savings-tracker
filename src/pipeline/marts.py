"""Phase 4: build the mart layer from sql/mart/*.sql, in file order (one table per file; grain and checks in each header).

A file whose first line is
    -- yoy: keys=<col,col|none> values=<col,col> [stage] [good=lower]
holds only the base SELECT. The runner wraps it with the dashboard's one change measure (legacy measures.yoy):
for each value v it adds v_prior (same keys, previous fiscal year) and v_yoy = (v - v_prior) / |v_prior| (blank when the
prior year is missing or zero); with `stage` it adds stage_pair ("Actual vs Actual", "Working budget vs Actual", ...).
Columns come out in the legacy order: base columns, every v_prior, every v_yoy, then stage_pair.
Other files are run as written (CREATE OR REPLACE TABLE ...).

The same headers define the `measures` catalog (`catalog()`): one row per value of every file with a header, saying what the
`_yoy` column means; `good=lower` marks a cost (a lower value is better), anything else is neutral context. `stage_evidence`
is the hand-kept reference/stage_evidence.csv, loaded as a table so the dashboard can show how each year's stage was confirmed.
"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SQL = ROOT / "sql" / "mart"
HEAD = re.compile(r"--\s*yoy:\s*keys=(\S+)\s+values=(\S+)(\s+stage)?(?:\s+good=(\w+))?")


def yoy_sql(name, base, keys, values, stage):
    k = [] if keys == "none" else keys.split(",")
    v = values.split(",")
    on = " AND ".join([f"b.{c} IS NOT DISTINCT FROM p.{c}" for c in k] + ["b.fiscal_year = p.fiscal_year"])
    prior_cols = ", ".join([f"{c}" for c in k] + ["fiscal_year + 1 AS fiscal_year"] + [f"{x} AS {x}_prior" for x in v] + (["stage AS stage_prior"] if stage else []))
    sel = ["b.*"] + [f"p.{x}_prior" for x in v]
    sel += [f"CASE WHEN p.{x}_prior IS NOT NULL AND p.{x}_prior <> 0 THEN (b.{x} - p.{x}_prior) / abs(p.{x}_prior) END AS {x}_yoy" for x in v]
    if stage:
        sel.append("CASE WHEN p.stage_prior IS NULL THEN NULL ELSE b.stage || ' vs ' || p.stage_prior END AS stage_pair")
    return (f"CREATE OR REPLACE TABLE mart.{name} AS WITH b AS ({base}), p AS (SELECT {prior_cols} FROM b) "
            f"SELECT {', '.join(sel)} FROM b LEFT JOIN p ON {on}")


def catalog(sql_dir=SQL):
    """The dashboard's measures: what each year-over-year column means, from the `-- yoy:` headers (file order)."""
    rows = []
    for f in sorted(Path(sql_dir).glob("*.sql")):
        m = HEAD.match(f.read_text().lstrip())
        if not m:
            continue
        keys = [] if m.group(1) == "none" else m.group(1).split(",")
        for v in m.group(2).split(","):
            rows.append({"table": f.stem.split("_", 1)[1], "measure": f"{v}_yoy",
                         "definition": f"Change in {v} from the previous fiscal year, as a share of the previous year",
                         "grouped_by": ", ".join(keys) or "fiscal year", "higher_is": m.group(4) or "neutral"})
    return pd.DataFrame(rows, columns=["table", "measure", "definition", "grouped_by", "higher_is"]).drop_duplicates(["table", "measure"])


def stage_evidence(root=ROOT):
    """How each budget year's stage was confirmed (reference/stage_evidence.csv, the legacy file carried over unchanged)."""
    return pd.read_csv(Path(root) / "reference" / "stage_evidence.csv")


def build(con):
    con.execute("CREATE SCHEMA IF NOT EXISTS mart")
    done = []
    for f in sorted(SQL.glob("*.sql")):
        text = f.read_text()
        try:
            m = HEAD.match(text.lstrip())
            if m:
                name = f.stem.split("_", 1)[1]
                body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--")).strip().rstrip(";")
                con.execute(yoy_sql(name, body, m.group(1), m.group(2), bool(m.group(3))))
            else:
                con.execute(text)
        except Exception as e:  # name the file so a broken mart is easy to find
            raise RuntimeError(f"{f.name}: {e}") from e
        done.append(f.stem)
    for name, df in (("measures", catalog()), ("stage_evidence", stage_evidence())):
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE mart.{name} AS SELECT * FROM _df")
        con.unregister("_df")
        done.append(name)
    return done
