"""Read-only MCP server over the GMI Savings Tracker data (Model Context Protocol, official Python SDK).

    python -m src.mcp.server [--db PATH] [--export DIR] [--backend auto|duckdb|export] [--timeout SECONDS]

Speaks MCP over stdio. Opens data/md_transparency.duckdb read-only when present, else the exported marts
(data/export/latest or the checked-in site_data/) in an in-memory DuckDB. Tools: list_tables, describe_table, query,
agency_spending, vendor_payments, get_sources; resource catalog://tables (the catalog as markdown). Every answer has a
`provenance` block (tables used, run_id, as_of). Setup and guardrails: docs/mcp.md.
"""
import argparse
import os
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import tools
from .store import MAX_LIMIT, Store, ToolInputError

INSTRUCTIONS = (
    "Read-only access to the GMI Savings Tracker: an independent prototype by Sierra Napier that checks Maryland's Government "
    "Modernization Initiative savings against the State's own open budget and payments data (opendata.maryland.gov). Not an "
    "official State of Maryland product. Start with list_tables or the catalog://tables resource, use agency_spending and "
    "vendor_payments for common questions, and query for anything else (one SELECT/WITH statement, at most "
    f"{MAX_LIMIT} rows). Quote the provenance block (tables, run_id, as_of) with any figure. Dollars are nominal unless a column says otherwise."
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def build(store=None):
    """The MCPServer with every tool bound to one Store (created lazily on first use when store is None)."""
    state = {"store": store}

    def st():
        if state["store"] is None:
            state["store"] = Store(db=os.environ.get("GMI_MCP_DB"), export_dir=os.environ.get("GMI_MCP_EXPORT"),
                                   prefer=os.environ.get("GMI_MCP_BACKEND", "auto"), timeout=float(os.environ.get("GMI_MCP_TIMEOUT", "10")))
        return state["store"]

    def call(fn, *a, **k):
        try:
            return fn(st(), *a, **k)
        except ToolInputError as e:
            raise ToolError(str(e)) from None

    server = MCPServer("gmi-savings-tracker", title="GMI Savings Tracker data (read-only)", instructions=INSTRUCTIONS, version="0.1.0")

    @server.tool(annotations=READ_ONLY)
    def list_tables() -> dict[str, Any]:
        """List every table with its layer (raw, ref, core, mart, ops), row count and a one-line description."""
        return call(tools.list_tables)

    @server.tool(annotations=READ_ONLY)
    def describe_table(name: str) -> dict[str, Any]:
        """Columns of one table with their types and definitions (from docs/data-governance.md). name: e.g. mart.f_agency or f_agency."""
        return call(tools.describe_table, name)

    @server.tool(annotations=READ_ONLY)
    def query(sql: str, limit: int = 100) -> dict[str, Any]:
        """Run one read-only SQL query (DuckDB dialect; SELECT or WITH only) and return up to `limit` rows (max 500).
        Bare table names resolve on the search path mart, core, ref, ops, raw. The result lists the source tables and the data's as-of date."""
        return call(tools.query, sql, limit)

    @server.tool(annotations=READ_ONLY)
    def agency_spending(agency: str, fiscal_year: int | None = None) -> dict[str, Any]:
        """One agency's operating spending, controllable purchases, budgeted positions and payments by fiscal year.
        agency: a three-character code (R00) or a name or part of one; fiscal_year: optional (e.g. 2025)."""
        return call(tools.agency_spending, agency, fiscal_year)

    @server.tool(annotations=READ_ONLY)
    def vendor_payments(vendor: str, fiscal_year: int | None = None, top_agencies: int = 10) -> dict[str, Any]:
        """Payments to one private vendor by year, and the agencies that paid it most.
        vendor: the vendor name or part of one (case-insensitive); fiscal_year: optional."""
        return call(tools.vendor_payments, vendor, fiscal_year, top_agencies)

    @server.tool(annotations=READ_ONLY)
    def get_sources() -> dict[str, Any]:
        """Source datasets: portal ids and links, portal update dates, row counts, and reconciliation status (portal count and website download)."""
        return call(tools.get_sources)

    @server.resource("catalog://tables", name="catalog", title="Data catalog", description="Every table with layer, rows and description",
                     mime_type="text/markdown")
    def catalog() -> str:
        return tools.catalog_markdown(st())

    return server


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db")
    ap.add_argument("--export")
    ap.add_argument("--backend", choices=["auto", "duckdb", "export"], default="auto")
    ap.add_argument("--timeout", type=float, default=10.0)
    a = ap.parse_args(argv)
    store = Store(db=a.db, export_dir=a.export, prefer=a.backend, timeout=a.timeout)
    print(f"gmi-savings-tracker MCP: {store.backend} backend, {len(store.tables)} tables, run {store.run.get('run_id')}", file=sys.stderr)
    build(store).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
