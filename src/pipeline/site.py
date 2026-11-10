"""Build the public GitHub Pages site of the GMI Savings Tracker prototype.

    python -m src.pipeline.site                       # build site/ from data/export/latest, else site_data/
    python -m src.pipeline.site --out DIR             # build somewhere else
    python -m src.pipeline.site --refresh-snapshot    # copy data/export/latest into the checked-in site_data/
    python -m src.pipeline.site --artifact OUT_DIR    # the claude.ai artifact variant of the same build (see below)

index.html is the dashboard page built exactly as preview.py builds it (legacy/gst page and its test harness, the live
look and palette), without the "preview for approval" banner and with a prototype disclaimer line instead. The data
are not embedded: the harness's data stub is built empty and its start-up line is swapped for one that fetches
data/<file>.csv for every dashboard dataset, then draws. The page itself (legacy/gst/page/index.html) is not changed.

The site also gets 404.html, robots.txt, figures/ (docs/figures/*.png) and about.html (the README's pipeline summary).
Nothing on the site loads from another host: d3 is inlined by the harness, as in the preview.

The artifact variant (--artifact) is the same build with what a claude.ai artifact cannot use or does not need left out:
no parquet/ (the explorer registers data/<table>.csv with read_csv_auto), no 404.html, robots.txt or .nojekyll, and no
download buttons (a build flag, not runtime sniffing; Copy results stays). Any U+FFFD replacement character in a text
file is replaced with '?' and reported, since the artifact host rejects or mangles it.
"""
import argparse
import csv
import html
import io
import json
import yaml
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline import preview, site_ai, site_catalog, site_explorer

ROOT = Path(__file__).resolve().parents[2]
EXPORT = ROOT / "data" / "export" / "latest"
SNAPSHOT = ROOT / "site_data"
OUT = ROOT / "site"
FIGURES = ROOT / "docs" / "figures"
REPO = "https://github.com/EVO3-Ecosystem/gmi-savings-tracker"
SITE_URL = "https://evo3-ecosystem.github.io/gmi-savings-tracker/"
DISCLAIMER = "Independent prototype by Sierra Napier, built from Maryland's open data; not an official State of Maryland product"

# the harness's start-up line (legacy/gst/scripts/page_test.py STUB), replaced by the fetch loader below
STUB_START = "window.addEventListener('load',run);"
LOADER = """window.addEventListener('load',()=>{const F=__FILES__,O=__OPTIONAL__,el=document.getElementById('site-status');
Promise.all(Object.entries(F).map(([k,f])=>fetch('data/'+f+'.csv').then(r=>{if(!r.ok){if(O.includes(k))return null;throw new Error(f+'.csv: HTTP '+r.status);}return r.text();})
.then(t=>{if(t!=null)DD[k]=d3.csvParse(t).map(r=>({...r}));})))
.then(()=>{if(el)el.textContent='';run();})
.catch(e=>{if(el)el.textContent=' Data could not be loaded ('+e.message+').';console.error(e);});});"""
BANNER = re.compile(r'<body><div style="background:#fff7e0[^>]*>.*?</div>', re.S)

PAGE_CSS = ("<style>:root{color-scheme:light;--s-bg:#f6f6f4;--s-fg:#0b0b0b;--s-muted:#52514e;--s-line:#e4e3de;--s-link:#1f5fbf;--s-focus:#1f5fbf;--s-img:#fff}"
            "@media (prefers-color-scheme: dark){:root:not([data-theme=\"light\"]){color-scheme:dark;--s-bg:#111110;--s-fg:#f0efec;--s-muted:#b5b3ad;--s-line:#34332f;--s-link:#7fb0ff;--s-focus:#7fb0ff;--s-img:#fff}}"
            ":root[data-theme=\"dark\"]{color-scheme:dark;--s-bg:#111110;--s-fg:#f0efec;--s-muted:#b5b3ad;--s-line:#34332f;--s-link:#7fb0ff;--s-focus:#7fb0ff;--s-img:#fff}"
            ":focus-visible{outline:2px solid var(--s-focus);outline-offset:2px}"
            "*{box-sizing:border-box}body{margin:0;background:var(--s-bg);color:var(--s-fg);font:16px/1.55 ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}"
            "main{max-width:880px;margin:0 auto;padding:24px 16px 64px}a{color:var(--s-link)}h1{font-size:28px;line-height:1.2;margin:.2em 0 .4em}"
            "h2{font-size:20px;margin:1.8em 0 .5em}.note{color:var(--s-muted);font-size:14px;border-bottom:1px solid var(--s-line);padding-bottom:12px}"
            ".tbl{overflow-x:auto}table{border-collapse:collapse;font-size:14px;width:100%}th,td{border-bottom:1px solid var(--s-line);padding:6px 8px;text-align:left;vertical-align:top}"
            "code{overflow-wrap:anywhere}img{max-width:100%;height:auto;background:var(--s-img);border:1px solid var(--s-line);border-radius:6px}code{font-size:.92em}</style>")


def source_dir():
    """The export the site is built from: the local export when there is one, else the checked-in snapshot."""
    if (EXPORT / "manifest.csv").exists():
        return EXPORT
    if (SNAPSHOT / "manifest.csv").exists():
        return SNAPSHOT
    raise SystemExit("no export found: run `python -m src.pipeline.export` or restore site_data/")


def commit_sha():
    sha = os.environ.get("GITHUB_SHA")
    if not sha:
        try:
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            sha = ""
    return sha


def as_of(src):
    """Date of the latest pipeline run in the export, and the latest portal update of its sources."""
    run = portal = ""
    p = src / "pipeline_runs.csv"
    if p.exists():
        runs = [r["started_utc"] for r in csv.DictReader(open(p)) if r.get("status") == "passed"]
        run = max(runs)[:10] if runs else ""
    p = src / "sources.csv"
    if p.exists():
        ups = [r["portal_updated"] for r in csv.DictReader(open(p)) if r.get("portal_updated")]
        portal = max(ups)[:10] if ups else ""
    return run, portal


def dashboard_html(src):
    """The preview page from preview.py, with no data embedded, no review banner and no page tests (built from the export)."""
    pt = preview._page_test()
    pt.run_tests = lambda *a, **k: []  # the page tests run in `make export`/preview, not here
    pt.top3 = lambda t: []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shutil.copy(src / "manifest.csv", tmp / "manifest.csv")  # only the manifest: the data stub is built empty
        saved = preview._page_test, preview.EXP
        preview._page_test, preview.EXP = (lambda: pt), tmp
        try:
            with redirect_stdout(io.StringIO()):
                if preview.main() != 0:
                    raise SystemExit("preview build failed")
        finally:
            preview._page_test, preview.EXP = saved
        page = (tmp / "dashboard_preview.html").read_text()
    if "var RAW={};" not in page or STUB_START not in page or not BANNER.search(page):
        raise SystemExit("the dashboard harness changed: the site's data loader or banner removal no longer applies")
    opt = set(getattr(pt, "OPTIONAL", set()))
    return page, pt.DATASETS, opt


def published_files(datasets):
    """Every file the page loads plus every file in config/dashboard.yaml (data the page does not draw yet stays downloadable)."""
    cfg = yaml.safe_load((ROOT / "config" / "dashboard.yaml").read_text())
    return sorted(set(datasets.values()) | set(cfg.values())) + ["manifest"]


def header(src, sha):
    run, portal = as_of(src)
    bits = [f"Data as of {run}" if run else "", f"portal updated {portal}" if portal else ""]
    when = ", ".join(b for b in bits if b)
    ref = f'commit <a href="{REPO}/commit/{sha}"><code>{sha[:7]}</code></a>' if sha else "commit unknown"
    return ('<div id="site-head" style="border-bottom:1px solid var(--color-border-line);padding:8px 0;font:13px/1.45 ui-sans-serif,system-ui,sans-serif;color:var(--color-fg-muted)">'
            f"<b>{html.escape(DISCLAIMER)}.</b> {when}. Built from {ref} of "
            f'<a href="{REPO}">EVO3-Ecosystem/gmi-savings-tracker</a> · <a href="about.html">About the pipeline</a> · <a href="explorer.html">Data explorer</a> · <a href="catalog.html">Database catalog</a> · <a href="ai.html">AI layer</a>'
            '<span id="site-status"> Loading data…</span></div>')


def build_index(src, sha):
    page, datasets, opt = dashboard_html(src)
    # optional datasets the export does not have are left out of the loader, so nothing requests a file that is not there
    datasets = {k: v for k, v in datasets.items() if k not in opt or (Path(src) / f"{v}.csv").exists()}
    page = BANNER.sub("<body>", page, count=1)
    page = page.replace(STUB_START, LOADER.replace("__FILES__", json.dumps(datasets)).replace("__OPTIONAL__", json.dumps(sorted(opt))), 1)
    page = page.replace("<title>GMI Tracker Preview</title>",
                        f'<title>GMI Savings Tracker</title><meta name="description" content="{html.escape(DISCLAIMER)}.">', 1)
    return page.replace("<body>", "<body>" + header(src, sha), 1), datasets


def _inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", s)

    def link(m):
        text, url = m.group(1), m.group(2)
        if url.startswith("docs/figures/"):
            url = "figures/" + url[len("docs/figures/"):]
        elif not re.match(r"https?://", url):
            url = f"{REPO}/blob/main/{url}"
        return f'<a href="{url}">{text}</a>'
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)


def md_to_html(md):
    """Enough Markdown for the README sections the about page shows: headings, paragraphs, tables, images, links."""
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                i += 1
            i += 1
            continue
        m = re.match(r"!\[([^\]]*)\]\(docs/figures/([^)]+)\)", ln)
        if m:
            out.append(f'<p><img src="figures/{m.group(2)}" alt="{html.escape(m.group(1))}" loading="lazy"></p>')
        elif ln.startswith("#"):
            n = min(len(ln) - len(ln.lstrip("#")) + 1, 4)
            out.append(f"<h{n}>{_inline(ln.lstrip('#').strip())}</h{n}>")
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            head, body = rows[0], rows[1:]
            out.append('<div class="tbl"><table><thead><tr>' + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table></div>")
            continue
        elif ln.strip():
            para = [ln]
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"[#|!`]", lines[i + 1]):
                i += 1
                para.append(lines[i])
            out.append(f"<p>{_inline(' '.join(para))}</p>")
        i += 1
    return "\n".join(out)


def readme_summary(readme):
    """The README's introduction, pipeline, datasets and status sections (the mermaid chart becomes figures/pipeline.png)."""
    keep, sec, intro = [], None, []
    for ln in readme.splitlines():
        if ln.startswith("## ") or ln.startswith("### "):
            sec = ln.lstrip("#").strip()
            if sec in ("How the pipeline works", "Datasets", "Status"):
                keep.append(ln)
                if sec == "How the pipeline works":
                    keep.append("![How the pipeline works](docs/figures/pipeline.png)")
            continue
        if sec is None:
            if not ln.startswith("# ") and not ln.startswith("[!["):
                intro.append(ln)
        elif sec in ("How the pipeline works", "Datasets", "Status"):
            keep.append(ln)
    return "\n".join(intro).strip(), "\n".join(keep)


NAV = ('<a href="./">Dashboard</a> · <a href="explorer.html">Data explorer</a> · <a href="catalog.html">Database catalog</a> · '
       '<a href="ai.html">AI layer</a> · <a href="about.html">About</a>')


def page(title, body, desc, head="", wide=False):
    cls = ' class="wide"' if wide else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><meta name="description" content="{html.escape(desc)}">{PAGE_CSS}{head}</head>'
            f'<body><main{cls}><p class="note">{html.escape(DISCLAIMER)}. {NAV} · <a href="{REPO}">Source code</a></p>{body}</main></body></html>')


TEXT_EXT = {".html", ".csv", ".txt", ".js", ".css", ".json", ".md", ".svg"}


def scrub_replacement_chars(out):
    """Replace U+FFFD in every text file under out with '?'; return {relative path: count}."""
    found = {}
    for f in sorted(out.rglob("*")):
        if f.is_file() and f.suffix.lower() in TEXT_EXT:
            t = f.read_text(encoding="utf-8", errors="replace")
            n = t.count("\ufffd")
            if n:
                f.write_text(t.replace("\ufffd", "?"), encoding="utf-8")
                found[str(f.relative_to(out))] = n
    return found


def build(out=OUT, src=None, artifact=False):
    """Build the site into out. artifact=True builds the claude.ai artifact variant (see the module docstring)."""
    src = Path(src) if src else source_dir()
    out = Path(out)
    sha = commit_sha()
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    index, datasets = build_index(src, sha)
    missing = sorted({f for f in datasets.values() if not (src / f"{f}.csv").exists()})
    if missing:
        raise SystemExit(f"export is missing dashboard files: {', '.join(missing)}")
    for f in published_files(datasets):
        if (src / f"{f}.csv").exists():
            shutil.copy(src / f"{f}.csv", out / "data" / f"{f}.csv")
    (out / "index.html").write_text(index)
    pq = [] if artifact else parquet_files(src)
    if pq:
        (out / "parquet").mkdir()
        for f in pq:
            shutil.copy(f, out / "parquet" / f.name)
    (out / "figures").mkdir()
    for f in sorted(FIGURES.glob("*.png")):
        shutil.copy(f, out / "figures" / f.name)
    intro, summary = readme_summary((ROOT / "README.md").read_text())
    (out / "about.html").write_text(page("About the GMI Savings Tracker",
                                         "<h1>GMI Savings Tracker: how it is built</h1>" + md_to_html(intro) + md_to_html(summary)
                                         + f'<p>Full documentation, code and tests: <a href="{REPO}">{REPO}</a>.</p>',
                                         "How the GMI Savings Tracker prototype is built from Maryland's open data."))
    tables = sorted(f.stem for f in (out / "data").glob("*.csv") if f.stem != "manifest") if artifact else [f.stem for f in pq]
    if tables:
        (out / "explorer.html").write_text(page("GMI data explorer", site_explorer.body(tables, artifact=artifact),
                                                "Query the GMI Savings Tracker's tables with SQL in the browser (DuckDB-WASM).", site_explorer.TOKENS, wide=True))
    (out / "catalog.html").write_text(page("GMI database catalog", site_catalog.body(src),
                                           "Every table of the GMI Savings Tracker: layer, rows, columns, checks and lineage.", site_catalog.TOKENS, wide=True))
    _, ai_body = site_ai.write(out, src)
    (out / "ai.html").write_text(page("GMI AI layer", ai_body, "The GMI Savings Tracker's AI and ML layer: payment screen, payee classifier, "
                                      "grant overlap, MCP server and Gemini briefs, with results read from the data.", site_ai.TOKENS))
    if artifact:
        fixed = scrub_replacement_chars(out)
        for k, n in fixed.items():
            print(f"artifact: replaced {n} U+FFFD character{'s' if n > 1 else ''} with '?' in {k}")
        if not fixed:
            print("artifact: no U+FFFD characters found")
        return _report(out, src, pq, artifact)
    (out / "404.html").write_text(page("Page not found", '<h1>Page not found</h1><p>That page is not part of this site. '
                                       'Go to the <a href="/gmi-savings-tracker/">dashboard</a> or the <a href="/gmi-savings-tracker/about.html">pipeline notes</a>.</p>',
                                       "Page not found."))
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\n# {SITE_URL}\n")
    (out / ".nojekyll").write_text("")
    return _report(out, src, pq, artifact)


def _report(out, src, pq, artifact):
    files = [p for p in out.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    pqs = sum(p.stat().st_size for p in (out / "parquet").glob("*.parquet")) if (out / "parquet").exists() else 0
    print(f"{'artifact' if artifact else 'site'}: {out} from {src.relative_to(ROOT) if src.is_relative_to(ROOT) else src} "
          f"({len(list((out / 'data').glob('*.csv')))} data files, {len(pq)} Parquet files ({pqs / 1e6:.1f} MB), {len(files)} files, {size / 1e6:.1f} MB, "
          f"index.html {(out / 'index.html').stat().st_size / 1e3:.0f} kB)")
    return out


def parquet_files(src):
    """The export's Parquet copies of its marts (data/export/<run>/parquet or site_data/parquet), for the explorer."""
    d = Path(src) / "parquet"
    return sorted(d.glob("*.parquet")) if d.exists() else []


def refresh_snapshot():
    if not (EXPORT / "manifest.csv").exists():
        raise SystemExit("no export in data/export/latest: run `python -m src.pipeline.export` first")
    files = [f for f in published_files(preview._page_test().DATASETS) if (EXPORT / f"{f}.csv").exists()]
    if SNAPSHOT.exists():
        shutil.rmtree(SNAPSHOT)
    SNAPSHOT.mkdir()
    for f in files:
        shutil.copy(EXPORT / f"{f}.csv", SNAPSHOT / f"{f}.csv")
    pq = [p for p in parquet_files(EXPORT) if p.stem in files]
    if pq:
        (SNAPSHOT / "parquet").mkdir()
        for p in pq:
            shutil.copy(p, SNAPSHOT / "parquet" / p.name)
    info = {"export": EXPORT.resolve().name, "refreshed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "files": len(files)}
    (SNAPSHOT / "snapshot.json").write_text(json.dumps(info, indent=1) + "\n")
    size = sum(p.stat().st_size for p in SNAPSHOT.rglob("*") if p.is_file())
    pqs = sum(p.stat().st_size for p in pq)
    print(f"snapshot: {SNAPSHOT} ({len(files)} files from export {info['export']}, {len(pq)} Parquet files {pqs / 1e6:.1f} MB, {size / 1e6:.1f} MB in all)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--src", help="export folder to build from (default: data/export/latest, else site_data/)")
    ap.add_argument("--refresh-snapshot", action="store_true", help="copy data/export/latest into site_data/ and stop")
    ap.add_argument("--artifact", metavar="OUT_DIR", help="build the claude.ai artifact variant into OUT_DIR instead of the site")
    a = ap.parse_args(argv)
    if a.refresh_snapshot:
        refresh_snapshot()
        return 0
    if a.artifact:
        build(a.artifact, a.src, artifact=True)
        return 0
    build(a.out, a.src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
