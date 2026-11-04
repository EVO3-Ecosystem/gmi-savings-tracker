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
    # the live dashboard's look: its fonts, popover and the validated eight-color palette, which the test stub leaves out
    look = ("<style>:root{--font-anthropic-sans:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;"
            "--font-anthropic-serif:ui-serif,Georgia,'Times New Roman',serif;--cds-font-weight-medium:550;--cds-surface-popover:#fff;"
            "--cds-border:#ddd;--cds-shadow-popover:0 4px 16px rgba(0,0,0,.12);--cds-text-secondary:#52514e;--color-bg:#f6f6f4;--color-fg:#0b0b0b;"
            "--color-fg-muted:#52514e;--color-border-line:#e4e3de;--cds-chart-muted:#c9c8c2}body{font-family:var(--font-anthropic-sans);margin:0 16px}</style>")
    html = pt.build_html(tables, {}).replace("</style>", "</style>" + look, 1).replace(
        "colors:['#2a6fdb','#d9822b','#3a9a5b','#a34fc2','#c94b4b','#2b9aa8','#8a7b2a','#6b6b6b']",
        "colors:['#2a78d6','#eb6834','#1baf7a','#eda100','#e87ba4','#008300','#6250d6','#e34948']").replace("<meta charset=utf-8>", '<meta charset=utf-8><meta name="viewport" content="width=device-width,initial-scale=1"><title>GMI Tracker Preview</title>', 1)
    out.write_text(html.replace("<body>", "<body>" + banner, 1))
    print(f"preview: {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
