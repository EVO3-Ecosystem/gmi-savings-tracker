"""Build a self-contained preview of the GMI Savings Tracker dashboard from the latest export, for review before publishing.

    python -m src.pipeline.preview

Uses the dashboard page and its test harness kept in legacy/gst (page/index.html, scripts/page_test.py): first runs the
dashboard's filter-combination tests against the exported files (every tab drawn, totals reconcile, no script errors),
then writes data/export/latest/dashboard_preview.html with the data embedded. Exits 1 if any test fails, so a preview
is only produced from data the dashboard can draw.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEG = ROOT / "legacy" / "gst"
EXP = ROOT / "data" / "export" / "latest"


def _page_test():
    sys.path.insert(0, str(LEG / "scripts"))
    spec = importlib.util.spec_from_file_location("page_test", LEG / "scripts" / "page_test.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    pt = _page_test()
    (LEG / "model").mkdir(exist_ok=True)
    tables = {f.stem: f.read_text() for f in EXP.glob("*.csv") if f.stem != "manifest"}
    res = pt.run_tests(tables, pt.top3(tables))
    bad = [r for r in res if not r[1]]
    for name, ok, detail in res:
        print(f"{'pass' if ok else 'FAIL'}  {name}: {detail}"[:240])
    print(f"preview tests: {len(res) - len(bad)} of {len(res)} passed")
    if bad:
        return 1
    out = EXP / "dashboard_preview.html"
    out.write_text(pt.build_html(tables, {}))
    print(f"preview: {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
