"""Snapshot and restore round trip on a small temporary database (no data/ needed)."""
import duckdb
import pytest

from src.pipeline import snapshot


@pytest.fixture
def small_db(tmp_path):
    path = tmp_path / "src.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA core")
    con.execute("CREATE SCHEMA ops")
    con.execute("CREATE TABLE core.fact AS SELECT i AS id, i * 1.5 AS amount, 'x' || i AS label FROM range(1000) t(i)")
    con.execute("CREATE TABLE ops.run_log AS SELECT 'R1' AS run_id")
    con.close()
    return path


def test_round_trip_preserves_every_table(small_db, tmp_path):
    snap = snapshot.create(small_db, tmp_path / "snaps")
    assert snapshot.verify(snap) == []
    target = tmp_path / "restored.duckdb"
    m = snapshot.restore(snap, target)
    assert m["run_id"] == "R1" and m["tables"] == {"core.fact": 1000, "ops.run_log": 1}
    con = duckdb.connect(str(target), read_only=True)
    assert con.execute("SELECT sum(amount) FROM core.fact").fetchone()[0] == sum(i * 1.5 for i in range(1000))
    con.close()


def test_restore_refuses_to_overwrite_without_force(small_db, tmp_path):
    snap = snapshot.create(small_db, tmp_path / "snaps")
    with pytest.raises(SystemExit, match="--force"):
        snapshot.restore(snap, small_db)
    snapshot.restore(snap, small_db, force=True)


def test_tampered_file_fails_verification_and_restores_nothing(small_db, tmp_path):
    snap = snapshot.create(small_db, tmp_path / "snaps")
    victim = next(p for p in snap.iterdir() if p.suffix == ".parquet" and "fact" in p.name)
    victim.write_bytes(victim.read_bytes()[:-8] + b"corrupt!")
    assert any("checksum mismatch" in p for p in snapshot.verify(snap))
    target = tmp_path / "restored.duckdb"
    with pytest.raises(SystemExit, match="failed verification"):
        snapshot.restore(snap, target)
    assert not target.exists()


def test_snapshot_folder_without_manifest_is_rejected(tmp_path):
    assert snapshot.verify(tmp_path) == [f"no manifest.json in {tmp_path}"]
