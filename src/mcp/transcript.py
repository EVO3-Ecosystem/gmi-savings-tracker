"""Example transcript for docs/mcp.md, produced by calling the tools through the real stdio server.

    python -m src.mcp.transcript [--write] [server args, e.g. --backend export --export site_data]

Starts `python -m src.mcp.server` as a subprocess, calls each tool over MCP, and prints the exchanges as markdown (long
lists cut to three items). --write replaces the block between the transcript markers in docs/mcp.md.
"""
import json
import re
import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "mcp.md"
CALLS = [("get_sources", {}),
         ("agency_spending", {"agency": "Department of Transportation", "fiscal_year": 2025}),
         ("vendor_payments", {"vendor": "grainger", "fiscal_year": 2025, "top_agencies": 3}),
         ("query", {"sql": "SELECT fiscal_year, round(total_payments / 1e9, 2) AS payments_billion FROM totals_by_fy "
                           "WHERE fiscal_year >= 2023 ORDER BY 1", "limit": 10}),
         ("query", {"sql": "DROP TABLE mart.f_agency"}),
         ("query", {"sql": "SELECT * FROM read_csv('/etc/passwd')"}),
         ("agency_spending", {"agency": "Department"})]


def _trim(o):
    if isinstance(o, dict):
        return {k: _trim(v) for k, v in o.items() if k not in ("definitions", "disclaimer")}
    if isinstance(o, list):
        return [_trim(x) for x in o[:3]] + ([f"... {len(o) - 3} more"] if len(o) > 3 else [])
    return o


async def _run(server_args):
    params = StdioServerParameters(command=sys.executable, args=["-m", "src.mcp.server", *server_args], cwd=str(ROOT))
    out = []
    async with Client(params) as c:
        for name, args in CALLS:
            r = await c.call_tool(name, args)
            out.append(f"**Call** `{name}` `{json.dumps(args)}`\n")
            if r.is_error:
                text = r.content[0].text
                out.append("**Error:** `" + (text if len(text) <= 300 else text[:297] + "...") + "`\n")
            else:
                out.append("```json\n" + json.dumps(_trim(r.structured_content), indent=1) + "\n```\n")
    return "\n".join(out)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    write = "--write" in argv
    argv = [a for a in argv if a != "--write"]
    md = anyio.run(_run, argv)
    if write:
        doc = DOC.read_text()
        DOC.write_text(re.sub(r"(<!-- transcript -->\n).*?(<!-- /transcript -->)", lambda m: m.group(1) + md.rstrip() + "\n" + m.group(2), doc, flags=re.S))
        print(f"wrote the transcript to {DOC}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
