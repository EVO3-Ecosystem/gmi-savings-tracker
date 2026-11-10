"""site/explorer.html: query the site's Parquet marts in the browser with DuckDB-WASM, with a plain-JS CSV fallback.

DuckDB-WASM is loaded from jsDelivr at an exact, pinned version (DUCKDB_WASM); its worker is started from a blob URL
(the worker script is imported from the CDN), and every Parquet file in site/parquet is registered over HTTP by a URL
resolved against the page's location, so the page works under any base path. If the module, the worker or WebAssembly
cannot load (a sandboxed host, an old browser, no network), or `?fallback=1` is set, the page says so and offers the
fallback: pick a table and view its first 200 rows from data/<table>.csv, with a simple column filter, in plain JS.

Results can be copied (Copy results: the Clipboard API inside the click, else a selected text box to copy by hand) and,
on GitHub Pages, downloaded as CSV. The claude.ai artifact build (`body(tables, artifact=True)`, from
`python -m src.pipeline.site --artifact`) has no Parquet: DuckDB reads data/<table>.csv with read_csv_auto, and the
download buttons are left out (decided at build time, not by sniffing the host).
"""
import html
import json

DUCKDB_WASM = "1.32.0"  # @duckdb/duckdb-wasm, published 2025-12-16; pin an exact version at least a month old

EXAMPLES = [
    ("Top vendors, FY2026", "SELECT vendor, payee_type, fy2026, agencies_fy2026\nFROM d_vendors\nORDER BY fy2026 DESC\nLIMIT 20"),
    ("Payment screen by agency", "SELECT agency, rule, count(*) AS groups, sum(review_amount) AS review_dollars\nFROM d_payment_screen\nGROUP BY ALL\nORDER BY review_dollars DESC"),
    ("Budget vs payments by agency, FY2025", "SELECT b.agency_code, a.agency, b.budget, b.payments,\n       b.payments / nullif(b.budget, 0) AS paid_share\nFROM f_budget_vs_pay b LEFT JOIN d_agency a USING (agency_code)\nWHERE b.fiscal_year = 2025\nORDER BY b.budget DESC\nLIMIT 25"),
    ("Payment screen by year (backtest)", "SELECT fiscal_year, rule, groups, records, review_amount, status\nFROM d_payment_screen_summary\nORDER BY fiscal_year, rule_order"),
    ("Opportunity leads by detector", "SELECT detector, count(*) AS findings, sum(likely) AS likely, sum(high) AS high\nFROM d_opps\nGROUP BY detector\nORDER BY likely DESC"),
    ("Focus-area spending by year", "SELECT fiscal_year, area, sum(spend) AS spend\nFROM f_area\nWHERE stage = 'Actual'\nGROUP BY ALL\nORDER BY fiscal_year, spend DESC"),
]

CSS = """
main.wide{max-width:1180px}
.ex-grid{display:grid;grid-template-columns:minmax(0,15rem) minmax(0,1fr);gap:20px;align-items:start}
@media (max-width:760px){.ex-grid{grid-template-columns:minmax(0,1fr)}}
.panel{border:1px solid var(--s-line);border-radius:8px;padding:12px;min-width:0;background:var(--s-panel)}
.tables{list-style:none;margin:0;padding:0;max-height:26rem;overflow:auto;font-size:14px}
.tables li{display:flex;justify-content:space-between;gap:8px;padding:3px 4px;border-radius:4px;cursor:pointer}
.tables li:hover,.tables li:focus-visible{background:var(--s-hover);outline:none}
.tables .n{color:var(--s-muted);font-variant-numeric:tabular-nums}
textarea{width:100%;min-height:9rem;font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;padding:8px;border:1px solid var(--s-line);border-radius:6px;background:var(--s-bg);color:var(--s-fg);resize:vertical}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
button,select,input[type=search]{font:inherit;font-size:14px;padding:4px 10px;border:1px solid var(--s-line);border-radius:6px;background:var(--s-panel);color:var(--s-fg);max-width:100%}
button{cursor:pointer}button.primary{background:var(--s-accent);border-color:var(--s-accent);color:#fff}
button.chip{border-radius:999px;font-size:13px;padding:2px 10px}
button:disabled{opacity:.5;cursor:default}
.status{font-size:14px;color:var(--s-muted)}.status.bad{color:var(--s-bad)}.status.good{color:var(--s-good)}
.msg{border:1px solid var(--s-bad);border-radius:8px;padding:10px 12px;margin:12px 0;font-size:14px}
.tbl{overflow:auto;max-height:32rem;border:1px solid var(--s-line);border-radius:6px}
.tbl table{font-size:13px}.tbl th{position:sticky;top:0;background:var(--s-panel);white-space:nowrap}.tbl td{white-space:nowrap;font-variant-numeric:tabular-nums}
.tbl td.num{text-align:right}
h2{font-size:18px;margin:1.2em 0 .4em}
"""

TOKENS = ("<style>:root{--s-panel:#fff;--s-hover:#f1f0ec;--s-accent:#2a78d6;--s-bad:#b42318;--s-good:#1a7f37}"
          "@media (prefers-color-scheme: dark){:root:not([data-theme=\"light\"]){--s-panel:#1e1e1d;--s-hover:#2a2a28;--s-accent:#4f93e6;--s-bad:#ff8a80;--s-good:#7ee2a8}}"
          ":root[data-theme=\"dark\"]{--s-panel:#1e1e1d;--s-hover:#2a2a28;--s-accent:#4f93e6;--s-bad:#ff8a80;--s-good:#7ee2a8}" + CSS + "</style>")

BODY = """<h1>Data explorer</h1>
<p>Query the dashboard's tables with SQL, right in your browser (DuckDB-WASM, nothing is sent to a server). Every table is a published
mart from the pipeline; the <a href="catalog.html">database catalog</a> describes every column.</p>
<p class="status" id="exStatus" role="status">Loading DuckDB-WASM __VER__ from jsDelivr…</p>
<div class="msg" id="exFail" hidden></div>
<div class="ex-grid">
  <div class="panel"><b>Tables</b> <span class="status" id="exTN"></span>
    <ul class="tables" id="exTables" aria-label="Tables"></ul></div>
  <div style="min-width:0">
    <section id="exSql">
      <div class="row" id="exExamples" aria-label="Example queries"></div>
      <label for="exQ" class="status">SQL (DuckDB dialect; Ctrl+Enter runs it)</label>
      <textarea id="exQ" spellcheck="false"></textarea>
      <div class="row"><button class="primary" id="exRun" disabled>Run query</button><button id="exCopy" disabled>Copy results</button><button id="exCsv" disabled__DLHIDE__>Download results (CSV)</button><span class="status" id="exInfo"></span></div>
    </section>
    <section id="exFb" hidden>
      <h2>Browse a table (fallback, no WebAssembly)</h2>
      <div class="row"><label>Table <select id="fbT" aria-label="Table"></select></label>
        <label>Column <select id="fbC" aria-label="Filter column"><option value="">any column</option></select></label>
        <input type="search" id="fbQ" placeholder="contains…" aria-label="Filter text">
        <button id="fbCopy" disabled>Copy rows</button><button id="fbCsv" disabled__DLHIDE__>Download rows (CSV)</button><span class="status" id="fbInfo"></span></div>
    </section>
    <div id="exCopyBox" hidden><p class="status" id="exCopyMsg" role="status"></p><textarea id="exCopyText" readonly aria-label="Results as CSV, selected for copying"></textarea></div>
    <div class="tbl" id="exOut" hidden><table><thead id="exHead"></thead><tbody id="exBody"></tbody></table></div>
  </div>
</div>
<p class="note" style="border:0;margin-top:24px">__SRCNOTE__
Results show the first 500 rows; Copy results__DLNOTE__ holds them all, as CSV. The fallback reads <code>data/&lt;table&gt;.csv</code> and shows the first 200 matching rows.</p>
<script>
window.__EX = {tables: __TABLES__, examples: __EXAMPLES__, ver: "__VER__", source: "__SOURCE__", download: __DOWNLOAD__};
const $ = id => document.getElementById(id);
const S = {mode: 'loading', cols: [], rows: [], counts: {}};
window.__ex = S;
const status = (t, cls) => { const e = $('exStatus'); e.textContent = t; e.className = 'status' + (cls ? ' ' + cls : ''); };
const fmt = v => v == null ? '' : typeof v === 'number' ? (Number.isInteger(v) ? v.toLocaleString('en') : v.toLocaleString('en', {maximumFractionDigits: 4})) : String(v);
function show(cols, rows, limit){ const h = $('exHead'), b = $('exBody'); h.textContent = ''; b.textContent = ''; const tr = document.createElement('tr');
  cols.forEach(c => { const th = document.createElement('th'); th.textContent = c; tr.appendChild(th); }); h.appendChild(tr);
  rows.slice(0, limit).forEach(r => { const tr = document.createElement('tr'); cols.forEach((c, i) => { const td = document.createElement('td'); const v = Array.isArray(r) ? r[i] : r[c]; if (typeof v === 'number') td.className = 'num'; td.textContent = fmt(v); tr.appendChild(td); }); b.appendChild(tr); });
  $('exOut').hidden = false; }
function toCsv(cols, rows){ const q = v => { if (v == null) return ''; const s = String(v); return /[",\\n\\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  return [cols.map(q).join(',')].concat(rows.map(r => cols.map((c, i) => q(Array.isArray(r) ? r[i] : r[c])).join(','))).join('\\n') + '\\n'; }
function download(name, text){ const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], {type: 'text/csv'})); a.download = name; document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0); }
async function copyText(text){ const box = $('exCopyBox'); box.hidden = true; S.copied = null;
  try { if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error('no clipboard access'); await navigator.clipboard.writeText(text); S.copied = 'clipboard';
    $('exInfo').textContent = $('fbInfo').textContent = 'Copied ' + text.split('\n').length.toLocaleString('en') + ' lines (CSV) to the clipboard.'; }
  catch (e) { const t = $('exCopyText'); t.value = text; box.hidden = false; t.focus(); t.select(); let ok = false; try { ok = document.execCommand('copy'); } catch (e2) { ok = false; }
    S.copied = ok ? 'execCommand' : 'select'; $('exCopyMsg').textContent = ok ? 'Copied (CSV). The rows are also in the box below.' : 'This page cannot write to the clipboard here: the rows are selected in the box below; press Ctrl+C (or ⌘C) to copy them.'; } }
function listTables(onPick){ const ul = $('exTables'); ul.textContent = '';
  __EX.tables.forEach(t => { const li = document.createElement('li'); li.tabIndex = 0; li.dataset.t = t; const a = document.createElement('span'); a.textContent = t; const n = document.createElement('span'); n.className = 'n'; n.textContent = S.counts[t] != null ? Number(S.counts[t]).toLocaleString('en') : '';
    li.append(a, n); li.addEventListener('click', () => onPick(t)); li.addEventListener('keydown', e => { if (e.key === 'Enter') onPick(t); }); ul.appendChild(li); });
  $('exTN').textContent = `(${__EX.tables.length})`; }
// --- CSV fallback (plain JS) -------------------------------------------------------------------------------
function parseCsv(text){ const rows = []; let row = [], f = '', q = false;
  for (let i = 0; i < text.length; i++) { const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
    else if (c === '"') q = true; else if (c === ',') { row.push(f); f = ''; } else if (c === '\\n') { row.push(f); rows.push(row); row = []; f = ''; } else if (c !== '\\r') f += c; }
  if (f !== '' || row.length) { row.push(f); rows.push(row); } return rows; }
const fbCache = {};
async function fbLoad(t){ if (!fbCache[t]) { const r = await fetch(new URL('data/' + t + '.csv', location.href)); if (!r.ok) throw new Error(t + '.csv: HTTP ' + r.status); const rows = parseCsv(await r.text()); fbCache[t] = {cols: rows[0] || [], rows: rows.slice(1)}; } return fbCache[t]; }
async function fbDraw(){ const t = $('fbT').value; if (!t) return; let d; try { d = await fbLoad(t); } catch (e) { $('fbInfo').textContent = 'Could not load ' + t + '.csv: ' + e.message; return; }
  const cs = $('fbC'); if (cs._t !== t) { cs._t = t; cs.textContent = ''; const o = document.createElement('option'); o.value = ''; o.textContent = 'any column'; cs.appendChild(o); d.cols.forEach((c, i) => { const x = document.createElement('option'); x.value = i; x.textContent = c; cs.appendChild(x); }); }
  const q = $('fbQ').value.trim().toLowerCase(), ci = cs.value === '' ? null : +cs.value;
  const hit = !q ? d.rows : d.rows.filter(r => ci == null ? r.some(v => v.toLowerCase().includes(q)) : String(r[ci] ?? '').toLowerCase().includes(q));
  S.cols = d.cols; S.rows = hit; show(d.cols, hit, 200); $('fbCsv').disabled = $('fbCopy').disabled = !hit.length;
  $('fbInfo').textContent = `${hit.length.toLocaleString('en')} of ${d.rows.length.toLocaleString('en')} rows match; showing ${Math.min(200, hit.length).toLocaleString('en')}`; }
function fallback(reason){ S.mode = 'fallback'; S.reason = reason; status('SQL is unavailable here; browsing tables from CSV instead.', 'bad');
  const m = $('exFail'); m.hidden = false; m.textContent = 'DuckDB-WASM could not start (' + reason + '). This can happen on a host that blocks WebAssembly, web workers or the jsDelivr CDN, or in an older browser. '
    + 'You can still pick a table below and view its first 200 rows, with a simple column filter. Every table is also downloadable as CSV from the dashboard data folder.';
  $('exSql').hidden = true; $('exFb').hidden = false; const sel = $('fbT'); sel.textContent = '';
  __EX.tables.forEach(t => { const o = document.createElement('option'); o.value = t; o.textContent = t; sel.appendChild(o); });
  listTables(t => { sel.value = t; fbDraw(); }); sel.addEventListener('change', fbDraw); $('fbC').addEventListener('change', fbDraw); $('fbQ').addEventListener('input', fbDraw);
  if (__EX.download) $('fbCsv').addEventListener('click', () => download($('fbT').value + '_filtered.csv', toCsv(S.cols, S.rows)));
  $('fbCopy').addEventListener('click', () => copyText(toCsv(S.cols, S.rows))); fbDraw(); }
// --- DuckDB-WASM ---------------------------------------------------------------------------------------------
const plain = (v, type) => { if (v == null) return null; if (typeof v === 'bigint') return Number.isSafeInteger(Number(v)) ? Number(v) : v.toString();
  if (/^Date/.test(type) && typeof v === 'number') return new Date(v).toISOString().slice(0, 10); if (/^Timestamp/.test(type) && typeof v === 'number') return new Date(v).toISOString();
  if (/^Decimal/.test(type)) return Number(v) / 10 ** (+(/scale=?(\\d+)/.exec(type) || [0, 0])[1] || 0);
  if (typeof v === 'object' && !(v instanceof Date)) return String(v); return v; };
async function run(conn){ const sql = $('exQ').value.trim(); if (!sql) return; $('exRun').disabled = true; $('exInfo').textContent = 'Running…'; const t0 = performance.now();
  try { const res = await conn.query(sql); const f = res.schema.fields; S.cols = f.map(x => x.name); const types = f.map(x => String(x.type));
    S.rows = res.toArray().map(r => { const o = r.toJSON(); return S.cols.map((c, i) => plain(o[c], types[i])); });
    show(S.cols, S.rows, 500); $('exCsv').disabled = $('exCopy').disabled = !S.rows.length; S.lastError = null;
    $('exInfo').textContent = `${S.rows.length.toLocaleString('en')} rows${S.rows.length > 500 ? ' (first 500 shown)' : ''} in ${Math.round(performance.now() - t0)} ms`; }
  catch (e) { S.lastError = e.message; $('exInfo').textContent = 'Error: ' + e.message; }
  finally { $('exRun').disabled = false; S.runs = (S.runs || 0) + 1; } }
async function start(){
  try { const m = await fetch(new URL('data/manifest.csv', location.href)); if (m.ok) { const r = parseCsv(await m.text()); const h = r[0]; r.slice(1).forEach(x => { if (x[h.indexOf('file')]) S.counts[x[h.indexOf('file')]] = x[h.indexOf('rows')]; }); } } catch (e) { /* row counts are optional */ }
  if (/[?&]fallback=1/.test(location.search)) return fallback('fallback requested in the address');
  if (typeof WebAssembly !== 'object' || typeof Worker !== 'function') return fallback('this browser has no WebAssembly or web workers');
  let timer; const timeout = new Promise((_, rej) => { timer = setTimeout(() => rej(new Error('timed out after 30 s')), 30000); });
  try {
    const conn = await Promise.race([timeout, (async () => {
      const duckdb = await import('https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@' + __EX.ver + '/+esm');
      const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
      const wurl = URL.createObjectURL(new Blob([`importScripts("${bundle.mainWorker}");`], {type: 'text/javascript'}));
      const worker = new Worker(wurl); const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
      await db.instantiate(bundle.mainModule, bundle.pthreadWorker); URL.revokeObjectURL(wurl);
      await db.open({filesystem: {allowFullHTTPReads: true}});
      const c = await db.connect();
      const pq = __EX.source === 'parquet';
      for (const t of __EX.tables) { const f = t + (pq ? '.parquet' : '.csv');
        await db.registerFileURL(f, new URL((pq ? 'parquet/' : 'data/') + f, location.href).href, duckdb.DuckDBDataProtocol.HTTP, false);
        await c.query(`CREATE OR REPLACE VIEW "${t}" AS SELECT * FROM ${pq ? `read_parquet('${f}')` : `read_csv_auto('${f}')`}`); }
      return c; })()]);
    clearTimeout(timer); S.mode = 'wasm'; S.conn = conn; status(`Ready: DuckDB-WASM ${__EX.ver}, ${__EX.tables.length} tables registered from ${__EX.source === 'parquet' ? 'parquet/' : 'data/ (CSV)'}.`, 'good');
    $('exRun').disabled = false; $('exRun').addEventListener('click', () => run(conn));
    $('exQ').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(conn); } });
    if (__EX.download) $('exCsv').addEventListener('click', () => download('query_results.csv', toCsv(S.cols, S.rows)));
    $('exCopy').addEventListener('click', () => copyText(toCsv(S.cols, S.rows)));
    listTables(t => { $('exQ').value = `SELECT *\\nFROM ${t}\\nLIMIT 100`; run(conn); });
    const ex = $('exExamples'); __EX.examples.forEach(([label, sql]) => { const b = document.createElement('button'); b.className = 'chip'; b.type = 'button'; b.textContent = label; b.addEventListener('click', () => { $('exQ').value = sql; run(conn); }); ex.appendChild(b); });
    $('exQ').value = __EX.examples[0][1]; run(conn);
  } catch (e) { clearTimeout(timer); console.warn('DuckDB-WASM unavailable:', e); fallback(e && e.message ? e.message : String(e)); } }
start();
</script>"""


def body(tables, artifact=False):
    """The explorer page body. artifact=True: tables are read from data/<table>.csv and there is no download button."""
    src = ("Tables come from the page's <code>data/</code> folder (the published CSVs, read with <code>read_csv_auto</code>)." if artifact else
           "Tables come from the site's <code>parquet/</code> folder (zstd Parquet, the same rows as the CSVs in <code>data/</code>).")
    return (BODY.replace("__TABLES__", json.dumps(tables)).replace("__EXAMPLES__", json.dumps(EXAMPLES))
            .replace("__VER__", html.escape(DUCKDB_WASM)).replace("__SOURCE__", "csv" if artifact else "parquet")
            .replace("__DOWNLOAD__", "false" if artifact else "true").replace("__DLHIDE__", " hidden" if artifact else "")
            .replace("__SRCNOTE__", src).replace("__DLNOTE__", "" if artifact else " or the CSV download"))
