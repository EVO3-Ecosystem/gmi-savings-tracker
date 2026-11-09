"""Dashboard tests: render the published page against the new tables before anything is published.

The page is loaded in headless Chromium with a stand-in for the dashboard runtime, then driven through
filter combinations (single years, back-to-back years, scattered years, budgets, areas, agencies,
invalid values). For each one it checks that
  * the page draws without script errors and shows no NaN / undefined / Infinity,
  * the page's own reconcile check passes (areas, controllable purchases, scopes and agencies add up),
  * agencies add up to the statewide total and the six areas add up to the focus total,
  * several years combined equal the sum of the same years taken one at a time,
  * invalid filter values are dropped by the page's self-healing step.
Results are recorded as checks with stage "page"; a failure stops the run from publishing.
Browser start-up problems are retried once (they are infrastructure, not data, problems).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "page" / "index.html"
D3 = ROOT / "deploy" / "vendor" / "d3.min.js"

DATASETS = {  # dataset id on the dashboard -> published table
    "f_function": "f_function", "f_object": "f_object", "f_scope": "f_scope", "f_fund": "f_fund", "f_code": "f_code",
    "f_area": "f_area", "f_vendor": "f_vendor", "f_agency": "f_agency", "d_agency": "d_agency", "totals": "totals_by_fy",
    "sources": "sources", "measures": "measures", "stage_evidence": "stage_evidence", "agency_master": "agency_master",
    "vendor_families": "vendor_families", "runs": "pipeline_runs", "checks": "run_checks", "d_vendor_moves": "d_vendor_moves", "d_opps": "d_opps", "d_bid_list": "d_bid_list", "f_vendor_detail": "f_vendor_detail", "d_vendor_names": "d_vendor_names", "d_savings_status": "d_savings_status", "d_plan50": "d_plan50", "d_master_quality": "d_master_quality", "d_rec_status": "d_rec_status", "f_forecast": "f_forecast", "d_forecast_model": "d_forecast_model", "d_savings": "d_savings", "f_savings_check": "f_savings_check",
    "d_vendors": "d_vendors", "f_vendor_pay": "f_vendor_pay", "f_payee_type": "f_payee_type", "f_vendor_year": "f_vendor_year",
    "d_multi": "d_multi", "f_concentration": "f_concentration", "d_area_top": "d_area_top", "d_families": "d_families", "d_multi_basis": "d_multi_basis",
    "f_grants": "f_grants", "f_fund_source": "f_fund_source", "f_program": "f_program", "f_budget_vs_pay": "f_budget_vs_pay", "f_overlap": "f_overlap",
}
AREAS = ['IT hardware, software & services', 'Fleet & fuel', 'Utilities & facility energy', 'Real estate & leases', 'Print, copy & mail', 'Telecom']

CSS = (":root{--color-bg:#fafafa;--color-panel:#fff;--color-border-line:#ddd;--color-fg:#111;--color-fg-muted:#666;--color-ok:#2a7;--color-warn:#c80;"
       "--color-bad:#c00;--cds-chart-muted:#bbb;--cds-font-size-title:28px;--cds-font-size-heading:17px;--cds-font-size-body:15px;--cds-font-size-caption:13px;"
       "--cds-pad-lg:16px;--cds-pad-sm:8px;--cds-pad-xs:4px;--cds-pad-md:12px;--cds-gap-md:12px;--cds-gap-lg:20px;--cds-gap-sm:8px;--cds-gap-xs:4px;--cds-radius:8px}"
       "body{font-family:sans-serif;background:var(--color-bg)}")

STUB = """<script>
var RAW=__RAW__;var DD={};for(const k in RAW)DD[k]=d3.csvParse(RAW[k]).map(r=>({...r}));
var calcs=[],cbs=[],PP=__PARAMS__;
window.dash={colors:['#2a6fdb','#d9822b','#3a9a5b','#a34fc2','#c94b4b','#2b9aa8','#8a7b2a','#6b6b6b'],params:()=>PP,
 setParams:p=>{PP={...PP,...p};setTimeout(run,0);},resetParams:()=>{PP={};setTimeout(run,0);},setLink:()=>{},
 calc:(id,o)=>calcs.push([id,o]),onData:f=>cbs.push(f),data:id=>DD[id]?{status:'ok',data:DD[id]}:{status:'loading',data:[]}};
function run(){for(const[id,o]of calcs){DD[id]=o.fn(...o.inputs.map(i=>DD[i]));}cbs.forEach(f=>f());}
window.addEventListener('load',run);</script>"""

# filter combinations: (name, params, tabs to draw)
def combos(latest=2025):
    y = latest
    return [
        ("default (all actual years)", {}, ["over", "areas", "track", "opp", "calc", "vend", "agency", "budget"]),
        ("vendors, one agency and one year", {"agencies": ["__TOP1__"], "years": [y]}, ["vend", "detail:vendor:Verizon"]),
        ("vendors, one area, budget years", {"areas": ["Telecom"], "stage": "budget"}, ["vend"]),
        ("vendors, FY2023 and two areas", {"years": [2023], "areas": ["Fleet & fuel", "Telecom"]}, ["vend", "detail:vendor:Element Fleet"]),
        ("vendor page outside the bid list", {}, ["detail:vendor:Depository Trust", "detail:vendor:Wellpoint Maryland"]),
        ("opportunities, one agency and area", {"agencies": ["__TOP1__"], "areas": ["IT hardware, software & services"]}, ["opp", "calc"]),
        ("savings check, one agency", {"agencies": ["__TOP1__"], "years": [2026]}, ["track"]),
        ("savings check, budgets only", {"stage": "budget"}, ["track"]),
        ("one year", {"years": [y]}, ["over", "areas", "agency", "budget"]),
        ("first actual year", {"years": [2017]}, ["over", "budget"]),
        ("FY2026 working budget, all stages", {"years": [2026], "stage": "all"}, ["over", "budget"]),
        ("one agency, budget and payments", {"agencies": ["__TOP1__"]}, ["over", "budget"]),
        ("back-to-back years", {"years": [y - 2, y - 1, y]}, ["over", "areas", "agency", "budget"]),
        ("scattered years", {"years": [2018, 2021, y]}, ["over", "areas", "agency"]),
        ("budget years", {"stage": "budget"}, ["over", "areas", "budget"]),
        ("working budget only", {"stage": "budget", "years": [2026]}, ["over", "agency"]),
        ("actual and budgets", {"stage": "all"}, ["over", "areas", "budget"]),
        ("actual and budgets, mixed pick", {"stage": "all", "years": [y, 2026, 2027]}, ["over", "budget"]),
        ("one area", {"areas": ["Fleet & fuel"]}, ["over", "areas", "agency"]),
        ("two areas, one year", {"areas": ["Telecom", "Print, copy & mail"], "years": [y]}, ["over", "areas", "agency"]),
        ("one agency", {"agencies": ["__TOP1__"]}, ["over", "areas", "budget"]),
        ("three agencies, two years", {"agencies": ["__TOP1__", "__TOP2__", "__TOP3__"], "years": [y - 1, y]}, ["over", "areas", "agency", "budget"]),
        ("agency + area + year", {"agencies": ["__TOP1__"], "areas": ["IT hardware, software & services"], "years": [y]}, ["over", "areas"]),
        ("FY2026 payments under actual", {"years": [2026]}, ["over"]),
        ("invalid values are dropped", {"years": [1999, y], "areas": ["Not an area"], "agencies": ["ZZZ"], "stage": "nonsense"}, ["over"]),
        ("old single-value params", {"fy": 2025, "area": "all", "agency": "all", "years": y, "areas": "Telecom"}, ["over"]),
        ("detail: controllable", {"years": [y]}, ["detail:controllable"]),
        ("detail: area page", {"years": [y - 1, y]}, ["detail:area:Fleet & fuel"]),
        ("detail: all areas, budgets", {"stage": "budget"}, ["detail:areas"]),
        ("detail: agency page", {}, ["detail:agency:__TOP1__"]),
        ("detail: payments by area", {"areas": ["Telecom"]}, ["detail:payments"]),
        ("detail: funds", {"years": [2020, 2021]}, ["detail:funds"]),
        ("opportunity pages", {}, ["opp", "detail:bid", "detail:opps", "detail:det:Peer gap", "detail:det:Leverage", "detail:vendor:Carahsoft", "detail:vendor:Verizon", "detail:vendor:Apple Ford", "detail:area:Telecom"]),
        ("calculator source pages", {}, ["calc", "detail:src:area:Telecom", "detail:src:area:Other controllable purchases", "detail:src:fee"]),
    ]


def build_html(tables, params):
    raw = {k: tables[v] for k, v in DATASETS.items() if v in tables}
    stub = STUB.replace("__RAW__", json.dumps(raw)).replace("__PARAMS__", json.dumps(params))
    return f"<!doctype html><meta charset=utf-8><style>{CSS}</style><script>{D3.read_text()}</script>{stub}<body>{PAGE.read_text()}</body>"


PROBE = """(tab) => {
  const G = window.__gst; const p = G.prm(); const ok = G.ok; const out = {params: p, issues: []};
  const vis = [...document.querySelectorAll('.gs .panel')].filter(e => !e.hidden).map(e => e.innerText).join('\\n') + document.getElementById('chips').innerText;
  if (/\\bNaN\\b|undefined|\\bInfinity\\b(?! [A-Z])/.test(vis))  /* 'Infinity Health Care' is a vendor name */ out.issues.push('NaN/undefined on screen');
  const sc = document.getElementById('selfcheck'); if (sc && /do not reconcile/.test(sc.textContent)) out.issues.push(sc.textContent);
  const rc = G.reconcile(p); if (!rc.ok) out.issues.push(rc.msg);
  // agencies add up to the state (operating spending), for the selected years
  const ff = ok('f_function'); const m = G.measure(ff, 'budget', p, {ignoreArea:true});
  const byAg = d3.rollup(ff.filter(r => m.years.includes(r.fiscal_year) && (!p.agencies.length || p.agencies.includes(r.agency_code))), v => d3.sum(v, r => r.budget), r => r.agency_code);
  if (m.n && Math.abs(d3.sum([...byAg.values()]) - m.value) > 1) out.issues.push('agencies do not add up to the total');
  // several years combined = sum of single years
  if (m.n > 1) { const singles = d3.sum(m.years, y => G.measure(ff, 'budget', p, {ignoreArea:true, years:[y]}).value || 0); if (Math.abs(singles - m.value) > 1) out.issues.push('combined years differ from the sum of single years'); }
  // six areas add up to the focus total
  const fa = ok('f_area').filter(r => r.spend != null); const am = G.measure(fa, 'spend', p);
  const parts = d3.sum(G.AREAS.filter(a => !p.areas.length || p.areas.includes(a)), a => G.measure(fa.filter(r => r.area === a), 'spend', p, {ignoreArea:true, years: am.years}).value || 0);
  if (Math.abs(parts - (am.value || 0)) > 1) out.issues.push('areas do not add up to the focus total');
  // changes must show when there is an earlier year to compare with
  const chg = [...document.querySelectorAll('.gs .panel:not([hidden]) .chg')]; const blank = chg.filter(e => e.textContent.trim().startsWith('—') || !e.textContent.trim()).length;
  if (p.years.length === 1 && G.STAGE_OF[p.years[0] - 1] && G.STAGE_OF[p.years[0]] && chg.length && blank === chg.length) out.issues.push('no year-over-year changes shown although the prior year exists');
  // v2 layout probes: new elements exist and say what they should (one entry per tab)
  const T = id => (document.getElementById(id) || {}).textContent || '';
  const NEED = {
    over: () => [[/^In the FY\\d{4} |^No operating budget/.test(T('overLede')), 'Overview finding missing'],
                 [/, FY\\d{4}$/.test(T('kBud')) && !/combined/.test(T('sBud')), 'Overview tiles are not one year'],
                 [!document.querySelector('#p-over #scopeChart'), 'scope chart still on the Overview'],
                 [/^A path to .* if reported savings recur .* across the assumed ranges/.test(T('ov50Note')) && /payment evidence/.test(T('ov50Note')), 'path to $50M not worded as a conditional']],
    calc: () => [[/ if reported savings recur /.test(T('planFind')), 'Calculator plan not worded as a conditional'],
                 [!/8 in 10|8-in-10/.test(T('p-calc')) && /indicative/.test(T('p-calc')) && /fell inside such a range/.test(T('p-calc')), 'forecast ranges not labelled indicative with their coverage']],
    opp: () => [[/leads worth up to/.test(T('opLede')) && /not additive/.test(T('opLede')), 'Opportunities headline reads as savings, or omits the overlap'],
                [!/Likely savings found|would reach GMI/.test(T('p-opp')), 'Opportunities still promise savings']],
    track: () => [[!document.getElementById('stBody2'), 'status table not merged'],
                  [/Since last run/.test(T('p-track')) && /at least 50% of the reported saving/.test(T('trTolNote')) && /50%/.test(T('trSeenS')), 'Seen tolerance or status column missing']],
    agency: () => [[/ per position: /.test(T('agLede')) || /No agency/.test(T('agLede')), 'Agencies headline missing'],
                   [!!document.querySelector('#agChart svg') || !!document.querySelector('#agChart .empty'), 'Agencies chart not drawn'],
                   [/pass money through/.test(T('agChartNote')), 'pass-through flag not explained']],
    budget: () => [[!!document.querySelector('#fsChart svg') || !!document.querySelector('#fsChart .empty'), 'funding chart not drawn'],
                   [['ovlFind', 'fnFind', 'fundFind', 'objFind', 'pgFind'].every(id => T(id).length > 20), 'a Budget card has no finding line'],
                   [[...document.querySelectorAll('#grBody td:nth-child(4)')].every(td => td.classList.contains('one') || td.colSpan > 1), 'grant descriptions are not one line']],
    areas: () => [[!!document.querySelector('#p-areas #scopeChart svg'), 'scope chart not drawn on Focus areas']],
  }[tab];
  // small-base rule: a change from a prior-year base under $1M carries no percent
  { const P0 = {stage:'all', years:[], areas:[], agencies:[]}; const a = G.measure([{fiscal_year:2024, v:5e5}, {fiscal_year:2025, v:2e6}], 'v', P0, {years:[2025]}), b = G.measure([{fiscal_year:2024, v:5e6}, {fiscal_year:2025, v:6e6}], 'v', P0, {years:[2025]});
    if (a.change != null || !a.small || b.change == null) out.issues.push('small-base rule not applied in measure()'); }
  if (NEED) NEED().forEach(([ok2, msg]) => { if (!ok2) out.issues.push(msg); });
  out.years = m.years.length; out.total = m.value; return out; }"""


def run_tests(tables, top_agencies, latest=2025, check=None, shots=None):
    """Return a list of (name, ok, detail). `tables` maps table name -> CSV text."""
    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as pw:
        browser = None
        for attempt in (1, 2):  # self-healing: one retry if the browser itself fails to start
            try:
                browser = pw.chromium.launch(); break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    return [("Dashboard tests could run", False, f"browser did not start: {e}")]
        tmp = ROOT / "model" / "page_test.html"
        for name, params, tabs in combos(latest):
            ps = json.loads(json.dumps(params).replace("__TOP1__", top_agencies[0]).replace("__TOP2__", top_agencies[1]).replace("__TOP3__", top_agencies[2]))
            tmp.write_text(build_html(tables, ps))
            page = browser.new_page(viewport={"width": 1200, "height": 900}); errs = []
            page.on("pageerror", lambda e: errs.append(str(e))); page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            issues, detail = [], ""
            try:
                page.goto("file://" + str(tmp)); page.wait_for_timeout(500)
                for t in tabs:
                    if t.startswith("detail:"):
                        key = t[7:].replace("__TOP1__", top_agencies[0])
                        page.evaluate("k => { const b = document.createElement('button'); b.dataset.expand = k; document.querySelector('.gs').appendChild(b); b.click(); b.remove(); }", key)
                    else:
                        page.click(f"#t-{t}")
                    page.wait_for_timeout(250)
                    r = page.evaluate(PROBE, t)
                    issues += [f"{t}: {i}" for i in r["issues"]]
                    detail = f"{r['years']} years, total ${r['total'] / 1e9:,.1f}B" if r.get("total") else f"{r['years']} years"
                    if shots:
                        page.screenshot(path=str(Path(shots) / f"pt_{len(results):02d}_{t.replace(':', '_')[:30]}.png"), full_page=True)
                if name == "invalid values are dropped":
                    p = page.evaluate("() => window.__gst.prm()")
                    if p["areas"] or p["agencies"] or 1999 in p["years"] or p["stage"] != "actual":
                        issues.append(f"invalid values were kept: {p}")
                    else:
                        detail = "invalid year, area, agency and spending type removed; notice shown"
                if name == "old single-value params":
                    p = page.evaluate("() => window.__gst.prm()")
                    if p["areas"] != ["Telecom"] or p["years"] != [latest]:
                        issues.append(f"single values not converted to lists: {p}")
                    else:
                        detail = "single values converted to lists"
            except Exception as e:  # noqa: BLE001
                issues.append(f"test error: {e}")
            issues += [f"script error: {e}" for e in errs]
            results.append((f"Dashboard: {name}", not issues, "; ".join(issues)[:400] if issues else detail))
            page.close()
        browser.close()
    return results


def tables_from(dirs):
    """Read the published tables, preferring the first directory that has each one."""
    out = {}
    for v in set(DATASETS.values()):
        for d in dirs:
            f = Path(d) / f"{v}.csv"
            if f.exists():
                out[v] = f.read_text(); break
    return out


def top3(tables):
    import io
    import pandas as pd
    a = pd.read_csv(io.StringIO(tables["f_agency"]))
    return list(a.groupby("agency_code").operating_spending.sum().sort_values(ascending=False).index[:3])


if __name__ == "__main__":
    dirs = sys.argv[1:] or [str(ROOT / "out")]
    t = tables_from(dirs)
    res = run_tests(t, top3(t), shots=None)
    for n, ok, d in res:
        print("PASS" if ok else "FAIL", n, "|", d)
    sys.exit(0 if all(ok for _, ok, _ in res) else 1)
