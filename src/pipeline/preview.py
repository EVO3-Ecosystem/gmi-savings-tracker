"""Build a self-contained preview of the GMI Savings Tracker dashboard from the latest export, for review before publishing.

    python -m src.pipeline.preview

Uses the dashboard page and its test harness kept in legacy/gst (page/index.html, scripts/page_test.py): first runs the
dashboard's filter-combination tests against the exported files (every tab drawn, totals reconcile, no script errors),
then writes data/export/latest/dashboard_preview.html with the data embedded. Exits 1 if any test fails, so a preview
is only produced from data the dashboard can draw.
"""
import csv
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
    man = list(csv.DictReader(open(EXP / "manifest.csv")))
    n = sum(r["source"] == "mart" for r in man)
    banner = ('<div style="background:#fff7e0;color:#3a2a00;border-bottom:1px solid #e6c97a;padding:10px 16px;font:14px/1.4 sans-serif">'
              f"<b>Preview for approval</b>: the GMI Savings Tracker built from the new database pipeline. {n} of {len(man)} data files come from "
              f"the new marts; {len(man) - n} are carried from the current pipeline until Phase 5. The live dashboard is unchanged.</div>")
    html = pt.build_html(tables, {}).replace("<meta charset=utf-8>", '<meta charset=utf-8><meta name="viewport" content="width=device-width,initial-scale=1"><title>GMI Tracker Preview</title>', 1)
    out.write_text(html.replace("<body>", "<body>" + banner, 1))
    print(f"preview: {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
