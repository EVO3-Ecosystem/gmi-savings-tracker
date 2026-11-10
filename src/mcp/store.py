"""Read-only data access for the MCP server.

Opens data/md_transparency.duckdb read-only when it exists (every layer: raw, ref, core, mart, ops). Otherwise loads the
exported marts (data/export/latest, else the checked-in site_data/ snapshot; Parquet when present, else the CSVs) into an
in-memory DuckDB as schema `mart`. Either way the connection is then locked: external access (files, network, ATTACH)
disabled, configuration locked, and every statement runs under a timeout. Every answer carries a provenance block.
"""
import csv
import datetime as dt
import decimal
import json
import math
import re
import threading
from pathlib import Path

import duckdb

from . import catalog, guard

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "md_transparency.duckdb"
EXPORTS = (ROOT / "data" / "export" / "latest", ROOT / "site_data")
SEARCH_PATH = ("mart", "core", "ref", "ops", "raw")
MAX_LIMIT = 500


class ToolInputError(ValueError):
    """A request the tools refuse (bad argument, rejected SQL, timeout); the message is meant for the caller."""


def _json(v):
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    if isinstance(v, dict):
        return {k: _json(x) for k, x in v.items()}
    return v


def _export_dir():
    for d in EXPORTS:
        if (d / "manifest.csv").exists():
            return d
    return None


class Store:
    def __init__(self, db=None, export_dir=None, timeout=10.0, prefer="auto"):
        """prefer: "auto" (database file if present, else export), "duckdb" or "export"."""
        self.timeout = float(timeout)
        db = Path(db) if db else DB
        exp = Path(export_dir) if export_dir else _export_dir()
        cfg = {"enable_external_access": False, "lock_configuration": True, "threads": 2}
        if prefer in ("auto", "duckdb") and db.exists():
            self.backend, self.source = "duckdb", db
            self.con = duckdb.connect(str(db), read_only=True, config=cfg)
        elif prefer in ("auto", "export") and exp is not None:
            self.source = exp
            self.con = duckdb.connect(":memory:")
            self.con.execute("CREATE SCHEMA mart")
            pq = sorted((exp / "parquet").glob("*.parquet")) if (exp / "parquet").exists() else []
            if pq:
                self.backend = "parquet"
                for f in pq:
                    self.con.execute(f'CREATE TABLE mart."{f.stem}" AS SELECT * FROM read_parquet(?)', [str(f)])
            else:
                self.backend = "csv"
                for f in sorted(exp.glob("*.csv")):
                    if f.name != "manifest.csv":
                        self.con.execute(f'CREATE TABLE mart."{f.stem}" AS SELECT * FROM read_csv_auto(?)', [str(f)])
            self.con.execute("SET enable_external_access = false")
            self.con.execute("SET lock_configuration = true")
        else:
            raise SystemExit(f"no data: neither {db} nor an export ({', '.join(str(e) for e in EXPORTS)}) exists")
        self._search_path = "SET search_path = '" + ",".join(SEARCH_PATH if self.backend == "duckdb" else ("mart",)) + "'"
        self.tables = self._tables()
        self.run = self._run()

    # ---------------------------------------------------------------- internals
    def _exec(self, sql, params=None, limit=None):
        """Run one statement on its own cursor under the timeout; return (columns, rows, truncated)."""
        cur = self.con.cursor()
        timer = threading.Timer(self.timeout, cur.interrupt)
        timer.start()
        try:
            cur.execute(self._search_path)  # per connection: a cursor does not inherit it
            cur.execute(sql, params or [])
            cols = [d[0] for d in cur.description] if cur.description else []
            if limit is None:
                rows, truncated = cur.fetchall(), False
            else:
                rows = cur.fetchmany(limit + 1)
                truncated = len(rows) > limit
                rows = rows[:limit]
        except duckdb.InterruptException:
            raise ToolInputError(f"query stopped after the {self.timeout:g} s statement timeout") from None
        except duckdb.Error as e:
            raise ToolInputError(f"query failed: {str(e).splitlines()[0]}") from None
        finally:
            timer.cancel()
            cur.close()
        return cols, [dict(zip(cols, (_json(v) for v in r))) for r in rows], truncated

    def _tables(self):
        _, rows, _ = self._exec("SELECT table_schema AS s, table_name AS t, table_type AS k FROM information_schema.tables "
                                "WHERE table_schema IN ('raw','ref','core','mart','ops') ORDER BY 1, 2")
        out = {}
        for r in rows:
            q = f"{r['s']}.{r['t']}"
            n = self._exec(f'SELECT count(*) AS n FROM {r["s"]}."{r["t"]}"')[1][0]["n"]
            out[q] = {"layer": r["s"], "rows": n, "kind": "view" if r["k"] == "VIEW" else "table"}
        return out

    def _run(self):
        run = {"run_id": None, "as_of": None, "portal_updated": None}
        if "mart.pipeline_runs" in self.tables:
            r = self._exec("SELECT run_id, started_utc FROM mart.pipeline_runs WHERE status = 'passed' ORDER BY started_utc DESC LIMIT 1")[1]
            if r:
                run["run_id"], run["as_of"] = r[0]["run_id"], str(r[0]["started_utc"])[:10]
        if self.backend == "duckdb" and "ops.run_log" in self.tables:
            r = self._exec("SELECT run_id, built_utc FROM ops.run_log ORDER BY run_id DESC LIMIT 1")[1]
            if r:
                run["run_id"], run["as_of"] = r[0]["run_id"], str(r[0]["built_utc"])[:10]
        elif (self.source / "snapshot.json").exists():
            run["export"] = json.loads((self.source / "snapshot.json").read_text()).get("export")
        if "mart.sources" in self.tables:
            r = self._exec("SELECT max(portal_updated) AS p FROM mart.sources")[1]
            run["portal_updated"] = str(r[0]["p"])[:10] if r and r[0]["p"] else None
        run["partial_payment_years"] = []
        if "core.fact_payment" in self.tables:  # the export holds partial years back (export.PARTIAL); the database keeps them
            run["partial_payment_years"] = [r["fiscal_year"] for r in self._exec(
                "SELECT DISTINCT fiscal_year FROM core.fact_payment WHERE partial_year ORDER BY 1")[1]]
        return run

    def resolve(self, name):
        """Qualified name of a table given as schema.table or a bare name (first match on the search path)."""
        name = str(name).strip().strip('"').lower()
        name = re.sub(r"\s+as\s+.*$", "", name).replace('"', "")
        if name in self.tables:
            return name
        if "." not in name:
            for s in SEARCH_PATH:
                if f"{s}.{name}" in self.tables:
                    return f"{s}.{name}"
        return None

    def provenance(self, tables):
        used = sorted({t for t in (self.resolve(x) for x in tables) if t})
        p = {"tables": used, "run_id": self.run.get("run_id"), "as_of": self.run.get("as_of"),
             "portal_updated": self.run.get("portal_updated"), "partial_payment_years": self.run.get("partial_payment_years", []),
             "backend": self.backend,
             "source": str(self.source.relative_to(ROOT)) if self.source.is_relative_to(ROOT) else str(self.source)}
        if self.run.get("export"):
            p["export"] = self.run["export"]
        p["disclaimer"] = "Independent prototype by Sierra Napier, built from Maryland's open data; not an official State of Maryland product"
        return p

    # ---------------------------------------------------------------- public
    def close(self):
        """Release the database file (DuckDB allows one configuration per file per process)."""
        try:
            self.con.close()
        except duckdb.Error:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def sql(self, sql, params=None):
        """Trusted internal query (the convenience tools' own fixed SQL, parameters bound): returns rows as dicts."""
        return self._exec(sql, params)[1]

    def query(self, sql, limit=100):
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ToolInputError("limit must be an integer") from None
        if not 1 <= limit <= MAX_LIMIT:
            raise ToolInputError(f"limit must be between 1 and {MAX_LIMIT}")
        try:
            clean = guard.check(sql)
        except guard.QueryRejected as e:
            raise ToolInputError(f"query rejected: {e}") from None
        try:
            cur = self.con.cursor()
            cur.execute(self._search_path)
            used = cur.get_table_names(clean, qualified=True)
        except duckdb.Error as e:
            raise ToolInputError(f"query failed: {str(e).splitlines()[0]}") from None
        cols, rows, truncated = self._exec(clean, limit=limit)
        return {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": truncated, "limit": limit,
                "provenance": self.provenance(used)}

    def columns(self, qualified):
        s, t = qualified.split(".", 1)
        return self.sql("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = ? AND table_name = ? "
                        "ORDER BY ordinal_position", [s, t])

    def describe_table_short(self, qualified):
        """First sentence of the table's description, at most 200 characters."""
        d = catalog.describe(qualified)
        first = re.split(r"(?<=[.;])\s", d, maxsplit=1)[0]
        return first if len(first) <= 200 else first[:197] + "..."

    def describe_table(self, qualified):
        return {"name": qualified, "layer": self.tables[qualified]["layer"], "rows": self.tables[qualified]["rows"],
                "description": catalog.describe(qualified),
                "columns": [{"name": c["column_name"], "type": c["data_type"], "description": catalog.column_definition(qualified, c["column_name"])}
                            for c in self.columns(qualified)]}

    def reconciliation(self):
        """The website/API reconciliation summary checked into docs/reconciliation/summary.csv (make reconcile)."""
        p = ROOT / "docs" / "reconciliation" / "summary.csv"
        return {r["dataset"]: r for r in csv.DictReader(open(p))} if p.exists() else {}
