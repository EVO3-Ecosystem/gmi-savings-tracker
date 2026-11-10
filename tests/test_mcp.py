"""MCP server golden set: 30 questions (tests/fixtures/mcp_golden.yaml) asked through the MCP protocol in-process, each
checked against an independent SQL query run on its own connection straight against the same data.

Runs on the checked-in export (site_data/, Parquet backend) always, and on data/md_transparency.duckdb when it exists.
Without the `mcp` SDK installed (`pip install -e ".[mcp]"`), the tool functions are called directly instead.
"""
import importlib.util
import json
import re
from pathlib import Path

import duckdb
import pytest
import yaml

from src.mcp import tools
from src.mcp.store import DB, Store

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = yaml.safe_load((ROOT / "tests" / "fixtures" / "mcp_golden.yaml").read_text())
SNAP = ROOT / "site_data"
HAS_SDK = importlib.util.find_spec("mcp") is not None and importlib.util.find_spec("mcp.server.mcpserver") is not None
BACKENDS = ["export"] + (["duckdb"] if DB.exists() else [])
_stores = {}


def store(backend):
    if backend not in _stores:
        _stores[backend] = Store(export_dir=SNAP, prefer="export") if backend == "export" else Store(db=DB, prefer="duckdb")
    return _stores[backend]


def call(st, tool, args):
    """Call a tool through an in-process MCP client (the SDK's Client(server)); structured result as a dict."""
    if not HAS_SDK:
        return getattr(tools, tool)(st, **args)
    import anyio
    from mcp import Client

    from src.mcp.server import build

    async def go():
        async with Client(build(st)) as c:
            r = await c.call_tool(tool, args)
            assert not r.is_error, r.content[0].text
            return r.structured_content

    return anyio.run(go)


def pick(obj, path):
    if path.startswith("len:"):
        return len(pick(obj, path[4:]))
    parts = re.findall(r"[^.\[\]]+|\[[^\]]+\]", path)
    cur = obj
    for i, p in enumerate(parts):
        if p.startswith("["):
            k, v = p[1:-1].split("=", 1)
            cur = next(x for x in cur if str(x.get(k)) == v)
        elif p == "*":
            rest = ".".join(parts[i + 1:])
            return [pick(x, rest) if rest else x for x in cur]
        elif isinstance(cur, list):
            cur = cur[int(p)]
        else:
            cur = cur[p]
    return cur


def expected(backend, sql, as_list=False):
    con = duckdb.connect(":memory:")
    if backend == "duckdb":
        con.execute(f"ATTACH '{DB}' AS md (READ_ONLY)")
        src = lambda t: f"md.mart.{t}"  # noqa: E731
    else:
        src = lambda t: f"read_parquet('{SNAP / 'parquet' / (t + '.parquet')}')"  # noqa: E731
    rows = con.execute(re.sub(r"\{(\w+)\}", lambda m: src(m.group(1)), sql)).fetchall()
    con.close()
    vals = [r[0] for r in rows]
    if as_list:
        return vals
    assert len(vals) == 1, f"expected_sql must return one row, got {len(vals)}"
    return vals[0]


def same(got, want, tol):
    if isinstance(want, list):
        return isinstance(got, list) and len(got) == len(want) and all(same(g, w, tol) for g, w in zip(got, want))
    if want is None or got is None:
        return got is None and want is None
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        return abs(float(got) - float(want)) <= tol
    return str(got) == str(want)


def test_the_golden_set_has_30_distinct_questions_over_every_tool():
    assert len(GOLDEN) == 30 and len({q["id"] for q in GOLDEN}) == 30
    assert {q["tool"] for q in GOLDEN} == {"list_tables", "describe_table", "query", "agency_spending", "vendor_payments", "get_sources"}


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("q", GOLDEN, ids=[q["id"] for q in GOLDEN])
def test_golden(backend, q):
    st = store(backend)
    res = call(st, q["tool"], q["args"])
    got = pick(res, q["answer"])
    want = expected(backend, q["expected_sql"], q.get("expect") == "list")
    assert same(got, want, q.get("tol", 0.005)), f"{q['id']} {q['question']}: got {got!r}, expected {want!r}"
    prov = res["provenance"]
    assert prov["run_id"] and prov["as_of"] and prov["backend"] == st.backend
    if q["tool"] != "list_tables":
        assert prov["tables"], "every answer names the tables it used"


@pytest.mark.parametrize("backend", BACKENDS)
def test_query_provenance_names_the_tables_read(backend):
    res = call(store(backend), "query", {"sql": "WITH a AS (SELECT * FROM f_agency) SELECT a.agency, d.agency_code FROM a "
                                                "JOIN mart.d_agency d ON a.agency_code = d.agency_code", "limit": 2})
    assert res["provenance"]["tables"] == ["mart.d_agency", "mart.f_agency"]
    assert res["row_count"] == 2 and res["truncated"] is True and res["columns"] == ["agency", "agency_code"]


@pytest.mark.parametrize("backend", BACKENDS)
def test_every_table_has_a_description_and_the_catalog_resource_lists_them(backend):
    st = store(backend)
    res = call(st, "list_tables", {})
    assert res["count"] == len(st.tables) > 40
    assert all(t["description"] for t in res["tables"])
    md = tools.catalog_markdown(st)
    assert "`mart.f_agency`" in md and "not an official State of Maryland product" in md
    json.dumps(res)  # JSON-safe


def test_ambiguous_and_unknown_names_are_reported_not_guessed():
    st = store("export")
    with pytest.raises(tools.ToolInputError, match="matches .* agencies"):
        tools.agency_spending(st, "Department")
    with pytest.raises(tools.ToolInputError, match="no agency"):
        tools.agency_spending(st, "Department of Unicorns")
    with pytest.raises(tools.ToolInputError, match="matches"):
        tools.vendor_payments(st, "health")
    with pytest.raises(tools.ToolInputError, match="unknown table"):
        tools.describe_table(st, "mart.nope")


@pytest.mark.skipif(not HAS_SDK, reason="mcp SDK not installed")
def test_the_server_lists_six_read_only_tools_and_the_catalog_resource():
    import anyio
    from mcp import Client

    from src.mcp.server import build

    async def go():
        async with Client(build(store("export"))) as c:
            ts = (await c.list_tools()).tools
            rs = (await c.list_resources()).resources
            text = (await c.read_resource("catalog://tables")).contents[0].text
            err = await c.call_tool("agency_spending", {"agency": "Department"})
            return ts, rs, text, err

    ts, rs, text, err = anyio.run(go)
    assert sorted(t.name for t in ts) == ["agency_spending", "describe_table", "get_sources", "list_tables", "query", "vendor_payments"]
    assert all(t.annotations.read_only_hint for t in ts)
    assert [str(r.uri) for r in rs] == ["catalog://tables"] and text.startswith("# GMI Savings Tracker data catalog")
    assert err.is_error and "use a code" in err.content[0].text
