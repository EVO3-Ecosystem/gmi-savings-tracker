"""Builds the GMI Savings Tracker PDF report from the published tables.

It renders the dashboard page itself (page/index.html) with the latest out/*.csv, captures each
finished tab as it appears on screen, and lays them out after a cover page into a letter-size,
landscape PDF: reports/GMI_Savings_Tracker_<run date>.pdf.

    python scripts/report.py
"""
import base64
import datetime as dt
import html
import json
from pathlib import Path

import io

import pandas as pd
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT, REPORTS, PAGE = ROOT / "out", ROOT / "reports", ROOT / "page" / "index.html"
REPORTS.mkdir(exist_ok=True)
D3 = (Path(__file__).parent / "vendor" / "d3.min.js").read_text()

# dataset id on the dashboard -> published table
DATASETS = {"f_function": "f_function", "f_object": "f_object", "f_scope": "f_scope", "f_fund": "f_fund", "f_code": "f_code",
            "f_area": "f_area", "f_vendor": "f_vendor", "f_agency": "f_agency", "d_agency": "d_agency", "totals": "totals_by_fy",
            "agency_master": "agency_master", "vendor_families": "vendor_families", "sources": "sources", "runs": "pipeline_runs",
            "checks": "run_checks", "measures": "measures", "reports": "reports", "stage_evidence": "stage_evidence"}
AREAS = ["IT hardware, software & services", "Fleet & fuel", "Utilities & facility energy", "Real estate & leases", "Print, copy & mail", "Telecom"]
DETAILS = [("controllable", "Detail: controllable purchases"), ("scope", "Detail: what agencies can change"), ("funds", "Detail: how the budget is paid for")] + [(f"area:{a}", f"Focus area: {a}") for a in AREAS]
# tabs included in the report, in order, once they are built
SECTIONS = [("over", "Overview"), ("areas", "Focus areas"), ("track", "Savings tracker"), ("opp", "Opportunities"), ("calc", "Calculator"), ("agency", "Agencies"), ("budget", "Budget"), ("data", "Data & pipeline")]

TOKENS = """:root{--color-bg:#ffffff;--color-panel:#ffffff;--color-border-line:#dcdfe4;--color-fg:#16181d;--color-fg-muted:#5c6370;
--color-ok:#1f7a4d;--color-warn:#a46200;--color-bad:#b3261e;--cds-chart-muted:#b9bec7;--cds-surface-popover:#fff;--cds-border:#dcdfe4;
--font-anthropic-sans:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;--font-anthropic-serif:Georgia,'Times New Roman',serif;
--cds-font-size-title:28px;--cds-font-size-heading:17px;--cds-font-size-body:14px;--cds-font-size-caption:12px;--cds-font-weight-medium:600;
--cds-pad-lg:16px;--cds-pad-md:12px;--cds-pad-sm:8px;--cds-pad-xs:4px;--cds-gap-xl:28px;--cds-gap-lg:20px;--cds-gap-md:12px;--cds-gap-sm:8px;--cds-gap-xs:4px;--cds-radius:8px}
body{margin:0;background:#fff;font-family:var(--font-anthropic-sans);color:var(--color-fg)}"""
COLORS = ["#2a6fdb", "#d9822b", "#2f9e6e", "#9b59b6", "#c0392b", "#16a2b8", "#8d7b2a", "#6b7280"]


def stub_page():
    data = {k: (OUT / f"{v}.csv").read_text() for k, v in DATASETS.items() if (OUT / f"{v}.csv").exists()}
    stub = f"""<script>{D3}</script><script>
var RAW={json.dumps(data)};var DD={{}};for(const k in RAW)DD[k]=d3.csvParse(RAW[k]).map(r=>({{...r}}));
var calcs=[],cbs=[],PP={{}};
window.dash={{colors:{json.dumps(COLORS)},params:()=>PP,setParams:p=>{{PP={{...PP,...p}};run();}},setLink:()=>{{}},
 calc:(id,o)=>calcs.push([id,o]),onData:f=>cbs.push(f),data:id=>DD[id]?{{status:'ok',data:DD[id]}}:{{status:'missing',data:[]}}}};
function run(){{for(const[id,o]of calcs){{try{{DD[id]=o.fn(...o.inputs.map(i=>DD[i]));}}catch(e){{}}}}cbs.forEach(f=>f());}}
window.addEventListener('load',run);</script>"""
    return f"<!doctype html><meta charset=utf-8><style>{TOKENS} .gs nav,.gs .filters,.gs .chips,.gs .xp,.gs .tip,.gs .msp{{display:none!important}} .gs .tbl{{max-height:none!important}} .gs .replink{{display:none!important}}</style>{stub}<body style='padding:16px'>{PAGE.read_text()}</body>"


def slices(png, page_ratio=6.6 / 10.1):
    """Split a tall screenshot into page-height pieces, cutting in the white gap between table rows."""
    im = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = im.size
    step = int(w * page_ratio)
    out, top = [], 0
    while top < h:
        bottom = min(h, top + step)
        if bottom < h:  # move the cut up to a horizontal line that is nearly all background
            g = im.convert("L")
            for y in range(bottom, max(top + step // 2, bottom - 200), -1):
                row = list(g.crop((0, y, w, y + 1)).getdata()) if not hasattr(g, 'get_flattened_data') else g.crop((0, y, w, y + 1)).get_flattened_data()
                if sum(1 for v in row if v < 235) < w * 0.02:
                    bottom = y
                    break
        buf = io.BytesIO()
        im.crop((0, top, w, bottom)).save(buf, "JPEG", quality=72, optimize=True, progressive=True)
        out.append(base64.b64encode(buf.getvalue()).decode())
        top = bottom
    return out


def capture():
    shots = []
    tmp = REPORTS / "_render.html"
    tmp.write_text(stub_page())
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1.35)
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(tmp.as_uri())
        pg.wait_for_timeout(700)
        for tab, title in SECTIONS:
            pg.evaluate(f"showTab('{tab}')")
            pg.wait_for_timeout(350)
            panel = pg.locator(f"#p-{tab}")
            if panel.locator(".soon").count():  # not built yet
                continue
            parts = panel.locator(":scope > *")
            imgs = []
            for i in range(parts.count()):
                if parts.nth(i).is_visible() and parts.nth(i).get_attribute('data-report') != 'skip':
                    imgs += slices(parts.nth(i).screenshot())
            shots.append((title, imgs))
        for key, title in DETAILS:  # expanded pages
            pg.evaluate(f"openDetail({json.dumps(key)})")
            pg.wait_for_timeout(350)
            parts = pg.locator("#p-detail > *")
            imgs = []
            for i in range(parts.count()):
                el = parts.nth(i)
                if el.is_visible() and el.get_attribute("class") != "crumb":
                    imgs += slices(el.screenshot())
            shots.append((title, imgs))
        b.close()
    tmp.unlink()
    if errors:
        raise RuntimeError(f"page errors while rendering the report: {errors}")
    return shots


def content_pdf(shots, path):
    """One section per tab or expanded page; images flow down the page and start a new page when they do not fit."""
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    W, H = landscape(letter)
    mx, my, head = 0.45 * 72, 0.45 * 72, 22
    c = canvas.Canvas(str(path), pagesize=(W, H))
    c.setTitle("GMI Savings Tracker report")
    page = [0]

    def footer():
        page[0] += 1
        c.setFont("Helvetica", 7.5); c.setFillGray(0.45)
        c.drawString(mx, my * 0.45, "GMI Savings Tracker · prototype by Sierra Napier, not an official State of Maryland product")
        c.drawRightString(W - mx, my * 0.45, f"Page {page[0] + 1}")

    for title, imgs in shots:
        y = H - my
        c.setFont("Helvetica-Bold", 13); c.setFillGray(0.08); c.drawString(mx, y - 13, title); y -= head + 4
        for b64 in imgs:
            raw = base64.b64decode(b64)
            ir = ImageReader(io.BytesIO(raw))
            iw, ih = ir.getSize()
            w = W - 2 * mx
            h = ih * w / iw
            if h > H - 2 * my - head:  # still too tall: scale to fit the page
                h = H - 2 * my - head; w = iw * h / ih
            if y - h < my:
                footer(); c.showPage(); y = H - my
                c.setFont("Helvetica", 9); c.setFillGray(0.45); c.drawString(mx, y - 9, title + " (continued)"); y -= 16
            c.drawImage(ImageReader(io.BytesIO(raw)), mx, y - h, width=w, height=h)
            y -= h + 8
        footer(); c.showPage()
    c.save()


def build():
    runs = pd.read_csv(OUT / "pipeline_runs.csv")
    run = runs.iloc[-1]
    checks = pd.read_csv(OUT / "run_checks.csv")
    n_pass, n = int((checks.status == "pass").sum()), len(checks)
    date = str(run.started_utc)[:10]
    fa = pd.read_csv(OUT / "f_function.csv"); act = fa[fa.stage == "Actual"].fiscal_year
    first, last = int(act.min()), int(act.max())
    shots = capture()
    toc = "".join(f"<li>{html.escape(t)}</li>" for t, _ in shots)
    body = ""  # content pages are laid out by content_pdf(), which keeps the JPEG compression
    doc = f"""<!doctype html><meta charset=utf-8><style>
@page{{size:Letter landscape;margin:0.45in}}
body{{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#16181d;margin:0}}
.cover{{height:7.3in;display:flex;flex-direction:column;justify-content:space-between;page-break-after:always}}
.cover h1{{font-family:Georgia,serif;font-weight:400;font-size:40px;margin:0 0 10px}}
.cover p{{font-size:15px;line-height:1.5;max-width:7.5in;margin:0 0 8px;color:#3a3f48}}
.cover .meta{{display:grid;grid-template-columns:repeat(3,auto);gap:6px 36px;font-size:13px;color:#3a3f48;justify-content:start}}
.cover .meta b{{display:block;color:#16181d;font-size:16px}}
.cover ol{{font-size:13px;line-height:1.6;margin:0;padding-left:30px;columns:2;column-gap:36px}}
.cover .fine{{font-size:11px;color:#6b7280;border-top:1px solid #dcdfe4;padding-top:8px}}
.sec{{page-break-before:always}}
.sec h2{{font-size:18px;font-weight:600;margin:0 0 8px}}
.sec img{{display:block;width:100%;height:auto;max-height:6.9in;object-fit:contain;object-position:top left;margin:0 0 10px;break-inside:avoid}}
</style>
<div class="cover"><div>
<h1>GMI Savings Tracker</h1>
<p>An independent savings tracker for GMI: it checks reported savings against the state's own payments, and finds the next $50M.</p>
<p>Report generated from pipeline run {html.escape(str(run.run_id))} on {date}. Every figure comes from State of Maryland data on opendata.maryland.gov, matched to the portal and to DBM's Operating Budget and Vendor Payments sites.</p>
<p><b>Filters for every page:</b> actual spending, all actual fiscal years (FY{first}–FY{last} for the budget, FY2008 onward for payments), all six focus areas, all agencies. Budget years (FY2026 working budget, FY2027 Legislative Appropriation) appear on the charts with dashed outlines and are not added into totals. Changes compare FY{first}–FY{last} with the first and last year where no equal earlier window exists.</p>
<div class="meta"><span>Data checks<b>{n_pass} of {n} passed</b></span><span>Payment and budget rows checked<b>{int(run.payment_rows)+int(run.budget_rows):,}</b></span><span>Run result<b>{'Passed' if run.status=='passed' else 'Failed'}</b></span></div>
</div><div><p style="margin-bottom:6px"><b>Contents</b></p><ol>{toc}</ol></div>
<p class="fine">Prototype by Sierra Napier, not an official State of Maryland product. Savings figures are scenarios for discussion, not estimates for any contract. Pages show the dashboard as of the run date.</p></div>
{body}"""
    name = f"GMI_Savings_Tracker_{date}.pdf"
    src = REPORTS / "_report.html"
    src.write_text(doc)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(src.as_uri())
        pg.wait_for_timeout(300)
        cover = REPORTS / "_cover.pdf"
        pg.pdf(path=str(cover), format="Letter", landscape=True, print_background=True)
        b.close()
    src.unlink()
    content = REPORTS / "_content.pdf"
    content_pdf(shots, content)
    from pypdf import PdfWriter, PdfReader
    w = PdfWriter()
    for part in (cover, content):
        for page in PdfReader(str(part)).pages:
            w.add_page(page)
    w.add_metadata({"/Title": f"GMI Savings Tracker report, {date}", "/Author": "Sierra Napier"})
    with open(REPORTS / name, "wb") as f:
        w.write(f)
    cover.unlink(); content.unlink()
    print(json.dumps({"report": name, "sections": [t for t, _ in shots], "bytes": (REPORTS / name).stat().st_size}))
    return REPORTS / name


if __name__ == "__main__":
    build()
