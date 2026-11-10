"""The README's images exist and its generated facts match the data."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
DB = ROOT / "data" / "md_transparency.duckdb"


def test_every_local_image_and_link_in_the_readme_exists():
    paths = re.findall(r'(?:src|srcset)="([^"]+)"', README) + re.findall(r"\]\(((?!https?://|#)[^)\s]+)\)", README)
    missing = [p for p in paths if not (ROOT / p.split("#")[0]).exists()]
    assert not missing, missing


def test_generated_blocks_are_marked():
    for name in ("readme", "badges"):
        assert f"<!-- facts:{name} -->" in README and f"<!-- /facts:{name} -->" in README


@pytest.mark.skipif(not DB.exists(), reason="needs the built database")
def test_readme_facts_equal_what_the_data_gives():
    import duckdb

    from src.models import doc_facts
    con = duckdb.connect(str(DB), read_only=True)
    try:
        assert doc_facts.put(README, "readme", doc_facts.readme_facts(con)) == README, "README facts are stale: run make docs"
        assert doc_facts.put(README, "badges", doc_facts.readme_badges(con)) == README, "README badges are stale: run make docs"
    finally:
        con.close()
