"""Phase 3 — Reference data: hand-kept CSVs in reference/ -> ref layer, plus the tables that apply them.

  ref.payment_agency_rule, ref.payment_agency_decision  ->  ref.map_payment_agency   (payment agency name -> budget agency code)
  ref.vendor_family, ref.vendor_normalization           ->  ref.map_payee_vendor     (payee name -> vendor; government flag)
  ref.payee_focus_area                                  ->  focus area by payee name
  ref.controllable_rule, ref.focus_area_rule            ->  core.fact_budget_scope   (controllable flag and focus area per budget line)
  ref.budget_stage                                      ->  ref.dim_stage            (replaces the Phase 2 rule)
  ref.gmi_reported_savings                              ->  recommendation 2's reported items
  core.mfr_document PDFs                                ->  core.mfr_measure         (recommendation 6: every performance measure and its yearly values)

Every rule lives in a CSV so each change has an author and a date in git.
"""
import difflib
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "reference"


def _csv(name):
    return pd.read_csv(REF / name, dtype=str, keep_default_na=False)


def _table(con, name, df):
    con.register("_df", df)
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _df")
    con.unregister("_df")


def load(con):
    for f in sorted(REF.glob("*.csv")):
        _table(con, f"ref.{f.stem.rstrip('s') if f.stem.endswith('rules') else f.stem}", _csv(f.name))


# ---------------------------------------------------------------- payment agency names -> budget agency codes
def map_payment_agency(con):
    rules = _csv("payment_agency_rules.csv")
    decisions = _csv("payment_agency_decisions.csv")
    bud = con.execute("SELECT agency_code, agency_name FROM ref.dim_agency").df().set_index("agency_code").agency_name
    codes = set(bud.index)
    mdot = next((c for c in codes if c.startswith("J00")), None)
    rollup = set(rules[rules.rule == "rollup"].payment_name_pattern)
    p = con.execute("SELECT DISTINCT agency_name_as_paid AS n, agency_code_as_paid AS c FROM core.fact_payment").df()
    coded = p[p.c.str.match(r"^[A-Z]\d\d$", na=False)].copy()
    coded["code"] = coded.c.where(~coded.c.isin(rollup) | (mdot is None), mdot)
    name2code = coded.groupby("n").code.agg(lambda s: s.value_counts().index[0]).to_dict()
    capital = rules[rules.rule == "capital"].payment_name_pattern.iloc[0]
    manual = list(zip(rules[rules.rule == "manual"].payment_name_pattern, rules[rules.rule == "manual"].target))
    direct = list(zip(rules[rules.rule == "direct"].payment_name_pattern, rules[rules.rule == "direct"].target))
    decided = {r.payment_agency_name: r for r in decisions.itertuples() if r.agency_code}
    rows = []
    for n in sorted(p.n.dropna().unique()):
        if n in decided:
            c, how = decided[n].agency_code, f"decision: {decided[n].decision}"
        elif n in name2code:
            c, how = name2code[n], "agency code in payments"
        elif re.search(capital, n):
            c, how = "CAPITAL", "capital budget account"
        else:
            c = next((next((k for k, v in bud.items() if re.search(t, str(v))), None) for pat, t in manual if re.search(pat, n)), None) \
                or next((t for pat, t in direct if re.search(pat, n)), None)
            how = "manual rule" if c else None
            if not c:
                m = difflib.get_close_matches(n, list(name2code), n=1, cutoff=0.88)
                c, how = (name2code[m[0]], f"closest name ({m[0]})") if m else (None, "unmatched")
        rows.append({"payment_agency_name": n, "agency_code": c, "matched_by": how, "in_budget": c in codes})
    _table(con, "ref.map_payment_agency", pd.DataFrame(rows))
    con.execute("""CREATE OR REPLACE TABLE core.fact_payment_mapped AS SELECT p.*, m.agency_code, m.matched_by
                   FROM core.fact_payment p LEFT JOIN ref.map_payment_agency m ON m.payment_agency_name = p.agency_name_as_paid""")


# ---------------------------------------------------------------- payee names -> vendors
def map_payee_vendor(con):
    nz = _csv("vendor_normalization.csv").set_index("step").pattern
    fam = _csv("vendor_families.csv")
    lens = _csv("payee_focus_area.csv")
    gov = re.compile(nz["government"])
    v = con.execute("SELECT vendor_name_as_paid AS payee, sum(amount) AS paid FROM core.fact_payment GROUP BY 1").df()

    def norm(s):
        s = re.sub(nz["strip_punctuation"], " ", str(s).upper())
        return re.sub(r"\s+", " ", re.sub(nz["drop_suffix"], " ", s)).strip()
    v["vendor_key"] = v.payee.map(norm)
    v["squash"] = v.vendor_key.str.replace(" ", "", regex=False)
    first = v.sort_values("paid", ascending=False).groupby("squash").vendor_key.first()  # spacing variants share the most-paid spelling
    v["vendor"] = v.squash.map(first)
    v["rule"] = "name"
    for f, pat in zip(fam.family, fam.payee_pattern):
        hit = v.vendor_key.str.contains(pat, regex=True)
        v.loc[hit, ["vendor", "rule"]] = [f, "family"]
    v["is_government"] = v.vendor_key.str.contains(gov)
    v["payee_area"] = None
    for a, pat in zip(lens.area, lens.payee_pattern):
        v.loc[v.payee_area.isna() & v.vendor_key.str.contains(pat, regex=True), "payee_area"] = a
    _table(con, "ref.map_payee_vendor", v[["payee", "vendor_key", "vendor", "rule", "is_government", "payee_area"]])
    # non-profits: grantees the State's grants data marks nonprofit = 'Y', normalized the same way as payee names
    if _has(con, "core", "fact_grant"):
        g = con.execute("SELECT grantee, upper(coalesce(nonprofit, '')) = 'Y' AS np, amount FROM core.fact_grant").df()
        g["vendor_key"] = g.grantee.map(norm)
        g = g.groupby("vendor_key").agg(grantee=("grantee", "first"), grants=("np", "size"), flagged=("np", "sum"), granted=("amount", "sum")).reset_index()
        g["nonprofit_share"] = g.flagged / g.grants
        _table(con, "ref.map_nonprofit", g[g.flagged > 0][["vendor_key", "grantee", "grants", "flagged", "nonprofit_share", "granted"]])


# ---------------------------------------------------------------- budget lines: controllable and focus area
def budget_scope(con):
    r = _csv("controllable_rules.csv")
    ex = "', '".join(r[r.rule == "excluded_object"].value.str.replace("'", "''"))
    ent = ", ".join(r[r.rule == "entitlement_code"].value)
    internal = ", ".join(r[r.rule == "internal_code"].value)
    iname = r[r.rule == "internal_name"].value.iloc[0]
    passthru = r[r.rule == "pass_through_program"].value.iloc[0]
    fa = _csv("focus_area_rules.csv").set_index("area")
    it = fa.loc["IT hardware, software & services", "value"]
    print_codes = ", ".join(f"'{c}'" for c in fa.loc["Print, copy & mail", "value"].split(";"))
    re_codes = ", ".join(f"'{c}'" for c in fa.loc["Real estate & leases", "value"].split(";"))
    con.execute(f"""CREATE OR REPLACE TABLE core.fact_budget_scope AS
      WITH b AS (SELECT *, CAST(subobject_code AS INTEGER) AS code_n,
          CAST(subobject_code AS INTEGER) IN ({internal}) OR regexp_matches(coalesce(subobject_name, ''), '(?i){iname}') AS internal,
          CAST(subobject_code AS INTEGER) IN ({ent}) OR regexp_matches(coalesce(program_name, ''), '{passthru}') AS entitlement
        FROM core.fact_budget),
      c AS (SELECT *, object_name NOT IN ('{ex}') AND NOT entitlement AND NOT internal AS controllable FROM b)
      SELECT * EXCLUDE (code_n),
        CASE WHEN NOT controllable THEN NULL  -- precedence as in the dashboard pipeline: later rules there win, so they come first here
             WHEN subobject_code IN ({re_codes}) THEN 'Real estate & leases'
             WHEN object_name = 'Fuel and Utilities' AND NOT regexp_matches(coalesce(subobject_name, ''), '(?i)Loan') THEN 'Utilities & facility energy'
             WHEN subobject_code IN ({print_codes}) THEN 'Print, copy & mail'
             WHEN object_name = 'Communications' THEN 'Telecom'
             WHEN regexp_matches(coalesce(subobject_name, ''), '(?i){it}') THEN 'IT hardware, software & services'
             WHEN object_name = 'Motor Vehicle Operation and Maintenance' THEN 'Fleet & fuel'
        END AS focus_area,
        CASE WHEN object_name IN ('{ex}') THEN 'Staff, grants and capital' WHEN internal THEN 'Charges between agencies'
             WHEN entitlement THEN 'Client payments and debt service' ELSE 'Controllable purchases' END AS scope
      FROM c""")
    con.execute("""CREATE OR REPLACE TABLE ref.map_focus_area AS SELECT DISTINCT focus_area AS area, subobject_code, subobject_name
                   FROM core.fact_budget_scope WHERE focus_area IS NOT NULL""")
    con.execute("CREATE OR REPLACE TABLE ref.dim_stage AS SELECT CAST(fiscal_year AS INTEGER) AS fiscal_year, stage, source FROM ref.budget_stage")


# ---------------------------------------------------------------- Managing for Results measures (recommendation 6)
VAL = re.compile(r"^(?:N/?A|n/a|TBD|-+|—|\$?\(?-?[\d,]*\.?\d+\)?%?[A-Za-z]{0,2}|\$?[\d.,]+\s*/\s*[\d.,]+|[\d.,]+/[\d.,]+)$")
HDR = re.compile(r"^(?:Performance Measures?|Measures?)\b.*?((?:(?:FY\s?)?\d{4}\s+(?:Act\.?|Est\.?|Actual|Estimate|Target)\s*){3,})", re.I)


def _num(v):
    s = v.replace("$", "").replace(",", "").replace("%", "").strip()
    if "/" in s or not s:
        return None
    try:
        return float(s.strip("()")) * (-1 if s.startswith("(") else 1)
    except ValueError:
        return None


def parse_mfr(path):
    import pdfplumber
    rows, goal, obj, cols, pending = [], None, None, None, ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("Goal "):
                    goal, cols, pending = line, None, ""
                    continue
                if line.startswith("Obj."):
                    obj, cols, pending = line, None, ""
                    continue
                m = HDR.match(line)
                if m:
                    cols = [f"{y} {t[:3].title()}." for y, t in re.findall(r"(\d{4})\s+(Act|Est|Actual|Estimate|Target)", m.group(1), re.I)]
                    pending = ""
                    continue
                if not cols:
                    continue
                tok = re.split(r"\s+", line)
                # values are the trailing tokens; "97.2 / 54.2" style pairs are joined first
                joined = re.sub(r"(\d)\s+/\s+(\d)", r"\1/\2", line)
                tok = re.split(r"\s+", joined)
                k = len(cols)
                if len(tok) > k and all(VAL.match(t) for t in tok[-k:]):
                    name = (pending + " " + " ".join(tok[:-k])).strip()
                    for c, v in zip(cols, tok[-k:]):
                        yr, kind = c.split()
                        rows.append({"goal": goal, "objective": obj, "measure": name, "fiscal_year": int(yr),
                                     "kind": "Actual" if kind.startswith("Act") else "Estimate", "value_text": v, "value": _num(v)})
                    pending = ""
                else:
                    pending = (pending + " " + line).strip()[-300:]  # a measure name that wraps onto the next line
    return rows


def mfr_measures(con, raw_dir):
    docs = con.execute("SELECT agency_file, agency_title, fiscal_year FROM core.mfr_document").df() if _has(con, "core", "mfr_document") else pd.DataFrame()
    if docs.empty:
        return
    agencies = con.execute("SELECT agency_code, agency_name FROM ref.dim_agency").df()
    key = lambda s: re.sub(r"\b(maryland|department|of|the|and|office|for|state|commission)\b|[^a-z ]", " ", s.lower()).split()  # noqa: E731
    names = {" ".join(key(n)): c for c, n in zip(agencies.agency_code, agencies.agency_name)}
    out, docmap = [], []
    rules = _csv("mfr_agency_map.csv")
    for d in docs.itertuples():
        hit = next((r for r in rules.itertuples() if re.search(r.file_pattern, d.agency_file)), None)
        if hit is not None:
            code, how = hit.agency_code, f"rule: {hit.note}"
        else:
            m = difflib.get_close_matches(" ".join(key(d.agency_title)), list(names), n=1, cutoff=0.75)
            code, how = (names[m[0]], "name") if m else (None, "unmatched")
        docmap.append({"agency_file": d.agency_file, "agency_code": code, "match": how})
        try:
            for r in parse_mfr(raw_dir / "mfr" / d.agency_file):
                out.append({"agency_file": d.agency_file, "agency_code": code, "plan_year": d.fiscal_year, **r})
        except Exception as e:  # one unreadable PDF never stops the build; it shows in the match report
            docmap[-1]["match"] += f"; parse error {type(e).__name__}"
    _table(con, "core.mfr_measure", pd.DataFrame(out))
    _table(con, "ref.map_mfr_agency", pd.DataFrame(docmap))


def _has(con, schema, table):
    return con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?", [schema, table]).fetchone()[0] > 0


def build(con, raw_dir):
    load(con)
    map_payment_agency(con)
    map_payee_vendor(con)
    budget_scope(con)
    mfr_measures(con, raw_dir)
