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


# The live dashboard's look: its fonts, popover and the validated eight-colour palette, which the test stub leaves out.
# Every colour is a token on :root, with dark values under prefers-color-scheme (unless the page is stamped
# data-theme="light") and again under data-theme="dark". The chart series are CSS variables too (dash.colors holds
# var(--series-N)), so d3 marks, axes and text follow the theme; the dark steps are the same hues stepped for the dark
# surface (validated as a set against #1a1a19).
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
SERIES_JS = "colors:[" + ",".join(f"'var(--series-{i + 1})'" for i in range(8)) + "]"
_LIGHT = {"color-bg": "#f6f6f4", "color-panel": "#fff", "color-border-line": "#e4e3de", "color-fg": "#0b0b0b", "color-fg-muted": "#52514e",
          "color-ok": "#1a7f37", "color-warn": "#9a6700", "color-bad": "#b42318", "cds-chart-muted": "#c9c8c2", "cds-surface-popover": "#fff",
          "cds-border": "#ddd", "cds-shadow-popover": "0 4px 16px rgba(0,0,0,.12)", "cds-text-secondary": "#52514e", "color-link": "#1f5fbf",
          "color-focus": "#1f5fbf", "conf-low": "#8a8983", **{f"series-{i + 1}": c for i, c in enumerate(SERIES_LIGHT)}}
_DARK = {"color-bg": "#111110", "color-panel": "#1a1a19", "color-border-line": "#34332f", "color-fg": "#f0efec", "color-fg-muted": "#b5b3ad",
         "color-ok": "#7ee2a8", "color-warn": "#f2cc60", "color-bad": "#ff8a80", "cds-chart-muted": "#5b5a55", "cds-surface-popover": "#242422",
         "cds-border": "#3a3936", "cds-shadow-popover": "0 4px 16px rgba(0,0,0,.5)", "cds-text-secondary": "#c3c2b7", "color-link": "#7fb0ff",
         "color-focus": "#7fb0ff", "conf-low": "#8a8983", **{f"series-{i + 1}": c for i, c in enumerate(SERIES_DARK)}}


def _vars(d):
    return ";".join(f"--{k}:{v}" for k, v in d.items())


LOOK = ("<style>:root{color-scheme:light;--font-anthropic-sans:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;"
        "--font-anthropic-serif:ui-serif,Georgia,'Times New Roman',serif;--cds-font-weight-medium:550;" + _vars(_LIGHT) + "}"
        "@media (prefers-color-scheme: dark){:root:not([data-theme=\"light\"]){color-scheme:dark;" + _vars(_DARK) + "}}"
        ":root[data-theme=\"dark\"]{color-scheme:dark;" + _vars(_DARK) + "}"
        "html,body{background:var(--color-bg);color:var(--color-fg)}body{font-family:var(--font-anthropic-sans);margin:0 16px}"
        "a{color:var(--color-link)}:focus-visible{outline:2px solid var(--color-focus);outline-offset:2px}"
        ".gs select:focus-visible,.gs a:focus-visible,.gs summary:focus-visible,.gs [tabindex]:focus-visible{outline:2px solid var(--color-focus);outline-offset:2px}"
        "@media (max-width:480px){body{margin:0 12px}}</style>")


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
              "<b>Preview for approval</b>: the GMI Savings Tracker built from the new database pipeline. "
              + (f"All {len(man)} data files come from the new marts." if n == len(man) else
                 f"{n} of {len(man)} data files come from the new marts; {len(man) - n} are carried from the current pipeline.")
              + " The live dashboard is unchanged.</div>")
    html = pt.build_html(tables, {}).replace("</style>", "</style>" + LOOK, 1).replace(
        "colors:['#2a6fdb','#d9822b','#3a9a5b','#a34fc2','#c94b4b','#2b9aa8','#8a7b2a','#6b6b6b']", SERIES_JS).replace("<meta charset=utf-8>", '<meta charset=utf-8><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>GMI Tracker Preview</title>', 1)
    out.write_text(html.replace("<body>", "<body>" + banner, 1))
    print(f"preview: {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
