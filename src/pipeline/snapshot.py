"""Portable, verifiable snapshots of the DuckDB database (the database file itself is git-ignored and ephemeral).

    python -m src.pipeline.snapshot create  [--out data/snapshots]
    python -m src.pipeline.snapshot restore SNAPSHOT_DIR [--db data/md_transparency.duckdb] [--force]

`create` runs DuckDB's EXPORT DATABASE (Parquet, ZSTD) from a read-only connection, so it never touches the live file,
and writes manifest.json: DuckDB version, source run ID, per-table row counts and a SHA-256 for every file.
`restore` verifies every checksum, imports into a fresh file, checks each table's row count against the manifest, and
only then moves it into place (never overwrites an existing database unless --force). Copy the snapshot folder
anywhere (object storage, a drive, a release asset) to keep it beyond this machine.
"""
import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "md_transparency.duckdb"
OUT = ROOT / "data" / "snapshots"


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tables(con):
    return [(s, t) for s, t in con.execute(
        "SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE' ORDER BY 1, 2").fetchall()]


def create(db=DB, out=OUT):
    db, out = Path(db), Path(out)
    con = duckdb.connect(str(db), read_only=True)
    try:
        try:
            run_id = con.execute("SELECT max(run_id) FROM ops.run_log").fetchone()[0]
        except duckdb.Error:
            run_id = None
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = out / f"{run_id or 'db'}-{stamp}"
        dest.mkdir(parents=True)
        con.execute(f"EXPORT DATABASE '{dest.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        rows = {f"{s}.{t}": con.execute(f'SELECT count(*) FROM "{s}"."{t}"').fetchone()[0] for s, t in _tables(con)}
        version = duckdb.__version__
    finally:
        con.close()
    files = {p.name: _sha(p) for p in sorted(dest.iterdir()) if p.is_file() and p.name != "manifest.json"}
    manifest = {"created_utc": stamp, "run_id": run_id, "duckdb_version": version, "source": db.name,
                "tables": rows, "files": files, "bytes": sum(p.stat().st_size for p in dest.iterdir())}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return dest


def verify(snap):
    """Return a list of problems with the snapshot folder (empty = intact)."""
    snap = Path(snap)
    mf = snap / "manifest.json"
    if not mf.exists():
        return [f"no manifest.json in {snap}"]
    m = json.loads(mf.read_text())
    bad = []
    for name, want in m["files"].items():
        p = snap / name
        if not p.exists():
            bad.append(f"missing file: {name}")
        elif _sha(p) != want:
            bad.append(f"checksum mismatch: {name}")
    return bad


def restore(snap, db=DB, force=False):
    snap, db = Path(snap), Path(db)
    bad = verify(snap)
    if bad:
        raise SystemExit("snapshot failed verification:\n  - " + "\n  - ".join(bad))
    if db.exists() and not force:
        raise SystemExit(f"{db} exists; pass --force to replace it")
    m = json.loads((snap / "manifest.json").read_text())
    tmp = db.with_suffix(".restoring")
    tmp.unlink(missing_ok=True)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.execute(f"IMPORT DATABASE '{snap.as_posix()}'")
        got = {f"{s}.{t}": con.execute(f'SELECT count(*) FROM "{s}"."{t}"').fetchone()[0] for s, t in _tables(con)}
    finally:
        con.close()
    if got != m["tables"]:
        tmp.unlink(missing_ok=True)
        diff = sorted(k for k in set(got) | set(m["tables"]) if got.get(k) != m["tables"].get(k))
        raise SystemExit(f"restore failed: row counts differ from the manifest for {diff[:8]}")
    if db.exists():
        db.unlink()
    shutil.move(str(tmp), str(db))
    return m


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--out", default=str(OUT))
    c.add_argument("--db", default=str(DB))
    r = sub.add_parser("restore")
    r.add_argument("snapshot")
    r.add_argument("--db", default=str(DB))
    r.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "create":
        dest = create(a.db, a.out)
        m = json.loads((dest / "manifest.json").read_text())
        print(f"snapshot: {dest}  ({len(m['tables'])} tables, {sum(m['tables'].values()):,} rows, {m['bytes'] / 1e6:.1f} MB, run {m['run_id']})")
    else:
        m = restore(a.snapshot, a.db, a.force)
        print(f"restored {len(m['tables'])} tables ({sum(m['tables'].values()):,} rows, run {m['run_id']}) to {a.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
