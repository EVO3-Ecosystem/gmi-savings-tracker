"""MCP server guardrails: only one read-only SELECT/WITH runs; writes, ATTACH, COPY, extensions, settings and file reads are
refused by the SQL check, and the connection itself refuses them even when the check is bypassed; statements time out."""
import importlib.util
from pathlib import Path

import pytest

from src.mcp import guard
from src.mcp.store import DB, Store, ToolInputError

ROOT = Path(__file__).resolve().parents[1]
HAS_SDK = importlib.util.find_spec("mcp") is not None and importlib.util.find_spec("mcp.server.mcpserver") is not None
BACKENDS = ["export"] + (["duckdb"] if DB.exists() else [])

REJECT = {
    "drop": "DROP TABLE mart.f_agency",
    "drop after select": "SELECT 1; DROP TABLE mart.f_agency",
    "drop hidden after comment": "SELECT 1 /* harmless */ ; DROP TABLE mart.f_agency",
    "delete": "DELETE FROM mart.f_agency",
    "insert": "INSERT INTO mart.f_agency SELECT * FROM mart.f_agency",
    "update": "UPDATE mart.f_agency SET payments = 0",
    "create": "CREATE TABLE mart.x AS SELECT 1",
    "create view": "CREATE VIEW v AS SELECT 1",
    "alter": "ALTER TABLE mart.f_agency RENAME TO y",
    "attach": "ATTACH 'other.duckdb' AS o",
    "attach url": "ATTACH 'https://example.com/x.duckdb'",
    "detach": "DETACH md",
    "copy out": "COPY mart.f_agency TO 'out.csv'",
    "copy query out": "COPY (SELECT * FROM mart.f_agency) TO '/tmp/x.parquet' (FORMAT parquet)",
    "export database": "EXPORT DATABASE '/tmp/dump'",
    "install": "INSTALL httpfs",
    "load": "LOAD httpfs",
    "pragma": "PRAGMA database_list",
    "set": "SET enable_external_access = true",
    "reset": "RESET lock_configuration",
    "call": "CALL pragma_version()",
    "checkpoint": "CHECKPOINT",
    "read_csv": "SELECT * FROM read_csv('/etc/passwd')",
    "read_text": "SELECT * FROM read_text('/etc/hostname')",
    "file path as table": "SELECT * FROM '/etc/passwd'",
    "glob": "SELECT * FROM glob('/home/*')",
    "parquet_scan": "SELECT * FROM parquet_scan('site_data/parquet/f_agency.parquet')",
    "query()": "SELECT * FROM query('SELECT 1')",
    "from shorthand": "FROM mart.f_agency",
    "explain": "EXPLAIN SELECT 1",
    "describe": "DESCRIBE mart.f_agency",
    "empty": "   ",
    "two selects": "SELECT 1; SELECT 2",
    "file in a join": "SELECT * FROM mart.d_agency a JOIN \"data/payee_names.txt\" p ON true",
    "url as table": "SELECT * FROM 'https://example.com/x.csv'",
    "file in a subquery": "SELECT 1 WHERE 1 IN (SELECT 1 FROM 'y.parquet')",
}
ALLOW = {
    "keyword inside a string": "SELECT 'DROP TABLE x; ATTACH y' AS s",
    "keyword inside a quoted alias": 'SELECT 1 AS "copy"',
    "a column named use": "SELECT use FROM mart.sources",
    "cte": "WITH a AS (SELECT 1 AS x) SELECT x FROM a",
    "range": "SELECT * FROM range(3)",
    "trailing semicolon and comment": "-- the agencies\nSELECT count(*) FROM mart.d_agency;",
}


@pytest.mark.parametrize("sql", REJECT.values(), ids=REJECT.keys())
def test_the_sql_check_rejects(sql):
    with pytest.raises(guard.QueryRejected):
        guard.check(sql)


@pytest.mark.parametrize("sql", ALLOW.values(), ids=ALLOW.keys())
def test_the_sql_check_allows_plain_selects(sql):
    assert guard.check(sql)


@pytest.fixture(scope="module", params=BACKENDS)
def st(request):
    s = Store(export_dir=ROOT / "site_data", prefer="export") if request.param == "export" else Store(db=DB, prefer="duckdb")
    yield s
    s.close()


@pytest.mark.parametrize("sql", [REJECT[k] for k in ("drop", "drop after select", "attach", "copy out", "read_csv", "install")])
def test_the_query_tool_refuses_and_the_data_is_unchanged(st, sql):
    before = st.sql("SELECT count(*) AS n FROM mart.f_agency")[0]["n"]
    with pytest.raises(ToolInputError, match="rejected"):
        st.query(sql)
    assert st.sql("SELECT count(*) AS n FROM mart.f_agency")[0]["n"] == before


@pytest.mark.parametrize("sql", ["SELECT * FROM read_csv('/etc/passwd')", "ATTACH '/tmp/gmi_mcp_attack.duckdb' AS x",
                                 "COPY (SELECT 1) TO '/tmp/gmi_mcp_attack.csv'", "SET enable_external_access = true",
                                 "INSTALL httpfs"])
def test_the_connection_itself_refuses_files_settings_and_extensions_when_the_check_is_bypassed(st, sql):
    with pytest.raises(ToolInputError):
        st._exec(sql)
    assert not Path("/tmp/gmi_mcp_attack.csv").exists() and not Path("/tmp/gmi_mcp_attack.duckdb").exists()


def test_the_database_file_is_opened_read_only():
    if not DB.exists():
        pytest.skip("data/md_transparency.duckdb not present")
    with Store(db=DB, prefer="duckdb") as st, pytest.raises(ToolInputError, match="read-only|read only"):
        st._exec("CREATE TABLE mart.should_not_exist AS SELECT 1")


def test_statements_time_out():
    st = Store(export_dir=ROOT / "site_data", prefer="export", timeout=0.3)
    with pytest.raises(ToolInputError, match="timeout"):
        st.query("SELECT count(*) FROM range(100000000000) a")


@pytest.mark.parametrize("limit", [0, -1, 501, "lots"])
def test_the_row_limit_is_enforced(st, limit):
    with pytest.raises(ToolInputError, match="limit"):
        st.query("SELECT 1", limit)


@pytest.mark.skipif(not HAS_SDK, reason="mcp SDK not installed")
def test_rejections_reach_the_mcp_client_as_tool_errors():
    import anyio
    from mcp import Client

    from src.mcp.server import build

    async def go():
        async with Client(build(Store(export_dir=ROOT / "site_data", prefer="export"))) as c:
            return [await c.call_tool("query", {"sql": s}) for s in (REJECT["drop"], REJECT["attach"], REJECT["copy out"])]

    for r in anyio.run(go):
        assert r.is_error and "query rejected" in r.content[0].text
