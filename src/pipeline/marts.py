"""Phase 4: build the mart layer from sql/mart/*.sql, in file order (one table per file; grain and checks in each header)."""
from pathlib import Path

SQL = Path(__file__).resolve().parents[2] / "sql" / "mart"


def build(con):
    con.execute("CREATE SCHEMA IF NOT EXISTS mart")
    for f in sorted(SQL.glob("*.sql")):
        try:
            con.execute(f.read_text())
        except Exception as e:  # name the file so a broken mart is easy to find
            raise RuntimeError(f"{f.name}: {e}") from e
    return [f.stem for f in sorted(SQL.glob("*.sql"))]
