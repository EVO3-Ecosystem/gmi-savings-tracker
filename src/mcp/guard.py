"""SQL guardrails for the MCP server's query tool: one read-only SELECT (or WITH ... SELECT) statement, nothing else.

Three layers, any of which refuses the query:
1. DuckDB's own parser (extract_statements): exactly one statement, of type SELECT.
2. The statement's first keyword (after comments) is SELECT or WITH.
3. The parsed tree (json_serialize_sql): every table reference is a plain identifier (no file path or URL used as a
   table) and every table function is on a short allowlist (range, generate_series, unnest).
4. Outside string literals, no keyword that changes state or reaches outside the database (ATTACH, COPY, INSTALL, LOAD,
   PRAGMA, SET, ...) and no function that reads files or runs a SQL string (read_csv, read_parquet, glob, query, ...).
The connection itself is also locked down (store.py): read-only, external access disabled, configuration locked, a timeout.
"""
import json
import re

import duckdb

MAX_SQL = 20_000
DENY_WORDS = ("ATTACH", "DETACH", "COPY", "INSTALL", "LOAD", "PRAGMA", "SET", "RESET", "CALL", "EXPORT", "IMPORT",
              "CHECKPOINT", "VACUUM", "CREATE", "DROP", "INSERT", "UPDATE", "DELETE", "ALTER", "TRUNCATE", "GRANT")
DENY_FUNCS = re.compile(r"\b(read_\w+|\w+_scan|glob|query|query_table|sniff_csv|getenv|load_extension|duckdb_secrets|"
                        r"duckdb_extensions|httpfs\w*|sqlite_\w+|postgres_\w+|mysql_\w+)\s*\(", re.I)
_LITERALS = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", re.S)
_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_parser = None
TABLE_FUNCS = {"range", "generate_series", "unnest"}
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class QueryRejected(ValueError):
    """The SQL is not a single read-only SELECT."""


def _strip(sql):
    """The SQL with string literals and quoted identifiers blanked and comments removed (for keyword checks)."""
    return _LITERALS.sub(lambda m: " " if m.group(0).startswith(("--", "/*")) else "''", sql)


def _refs(node):
    """(BASE_TABLE, name) and (TABLE_FUNCTION, function name) for every table reference in a serialized query tree."""
    if isinstance(node, dict):
        if node.get("type") == "BASE_TABLE":
            yield "BASE_TABLE", node.get("table_name")
        elif node.get("type") == "TABLE_FUNCTION":
            yield "TABLE_FUNCTION", (node.get("function") or {}).get("function_name")
        for v in node.values():
            yield from _refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _refs(v)


def check(sql):
    """Return the cleaned SQL (no trailing semicolon) or raise QueryRejected with the reason."""
    global _parser
    if not isinstance(sql, str) or not sql.strip():
        raise QueryRejected("empty query")
    if len(sql) > MAX_SQL:
        raise QueryRejected(f"query longer than {MAX_SQL} characters")
    if _parser is None:
        _parser = duckdb.connect(":memory:")
    try:
        stmts = _parser.extract_statements(sql)
    except duckdb.Error as e:
        raise QueryRejected(f"could not parse the query: {str(e).splitlines()[0]}") from None
    if len(stmts) != 1:
        raise QueryRejected(f"exactly one statement is allowed (got {len(stmts)})")
    if stmts[0].type != duckdb.StatementType.SELECT:
        raise QueryRejected(f"only SELECT or WITH queries are allowed (got {stmts[0].type.name})")
    tree = json.loads(_parser.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0])
    if tree.get("error"):
        raise QueryRejected(f"could not parse the query: {tree.get('error_message', '')}")
    for kind, name in _refs(tree):
        if kind == "BASE_TABLE" and not IDENT.match(name or ""):
            raise QueryRejected(f"table name not allowed (a file path or URL?): {name!r}")
        if kind == "TABLE_FUNCTION" and (name or "").lower() not in TABLE_FUNCS:
            raise QueryRejected(f"table function not allowed: {name}")
    bare = _strip(sql)
    first = _COMMENTS.sub(" ", sql).lstrip().split(None, 1)
    if not first or first[0].upper().rstrip("(") not in ("SELECT", "WITH"):
        raise QueryRejected("the query must start with SELECT or WITH")
    words = set(re.findall(r"[A-Za-z_]+", bare.upper()))
    bad = sorted(words & set(DENY_WORDS))
    if bad:
        raise QueryRejected(f"keyword not allowed in a read-only query: {', '.join(bad)}")
    m = DENY_FUNCS.search(bare)
    if m:
        raise QueryRejected(f"function not allowed (reads files or runs SQL text): {m.group(1)}")
    return sql.strip().rstrip(";").strip()
