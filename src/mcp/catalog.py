"""Table and column descriptions for the MCP server, read from the governance files checked into the repository.

Sources (all written by src/pipeline/governance.py or hand-kept, so nothing here needs the database):
docs/schemas/warehouse_columns.csv (every warehouse table's columns, types and definitions), docs/schemas/dashboard_columns.csv
(the exported marts' columns), the sql/mart/*.sql headers and the Python model descriptions that site/catalog.html also uses.
"""
import csv
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import yaml

from src.pipeline import site_catalog

ROOT = Path(__file__).resolve().parents[2]
SCH = ROOT / "docs" / "schemas"


def _rows(path):
    return list(csv.DictReader(open(path))) if Path(path).exists() else []


@lru_cache(maxsize=1)
def column_definitions():
    """{qualified table: {column: definition}}; exported marts are keyed as mart.<name>."""
    out = defaultdict(dict)
    for r in _rows(SCH / "warehouse_columns.csv"):
        out[r["table"]][r["column"]] = r["definition"]
    for r in _rows(SCH / "dashboard_columns.csv"):
        out[f"mart.{r['table']}"].setdefault(r["column"], r["definition"])
    return dict(out)


@lru_cache(maxsize=1)
def table_descriptions():
    """{qualified table: one-line description}, the same wording as site/catalog.html."""
    ds = yaml.safe_load((ROOT / "config" / "datasets.yaml").read_text())["datasets"]
    raw = {f"raw.{k}": f"Rows of {d['id']} {d.get('portal_name', k)} as delivered by the portal." for k, d in ds.items()}
    raw |= {f"raw.{k}": f"Rows of {v} as delivered by the source." for k, v in site_catalog.CONTEXT.items()}
    sql = site_catalog.describe_sql()
    out = {}
    for t in set(column_definitions()) | set(sql) | set(raw) | {f"mart.{k}" for k in site_catalog.PY}:
        layer, name = t.split(".", 1)
        out[t] = sql.get(t) or (site_catalog.PY.get(name) if layer == "mart" else None) or raw.get(t) or site_catalog.LAYERS.get(layer, "")
    return out


def describe(qualified):
    layer = qualified.split(".", 1)[0]
    return table_descriptions().get(qualified) or site_catalog.LAYERS.get(layer, "")


def column_definition(qualified, column):
    return column_definitions().get(qualified, {}).get(column, "")
