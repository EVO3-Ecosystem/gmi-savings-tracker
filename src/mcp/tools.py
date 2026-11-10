"""The MCP server's tools as plain functions over a Store (server.py registers them; tests can call them directly)."""
import re

from .store import MAX_LIMIT, ToolInputError

AGENCY_CODE = re.compile(r"^[A-Z]\d{2}$")


def list_tables(store):
    tables = [{"name": q, "layer": t["layer"], "kind": t["kind"], "rows": t["rows"], "description": store.describe_table_short(q)}
              for q, t in store.tables.items()]
    return {"tables": tables, "count": len(tables), "provenance": store.provenance([])}


def describe_table(store, name):
    q = store.resolve(name)
    if not q:
        raise ToolInputError(f"unknown table {name!r}; call list_tables for the names")
    out = store.describe_table(q)
    out["provenance"] = store.provenance([q])
    return out


def query(store, sql, limit=100):
    return store.query(sql, limit)


def _year(fiscal_year):
    if fiscal_year is None:
        return None
    try:
        y = int(fiscal_year)
    except (TypeError, ValueError):
        raise ToolInputError("fiscal_year must be a year such as 2025") from None
    if not 2000 <= y <= 2100:
        raise ToolInputError("fiscal_year must be a year such as 2025")
    return y


def resolve_agency(store, agency):
    """(agency_code, agency name) for a three-character code (R00) or a name or part of one."""
    a = str(agency or "").strip()
    if not a:
        raise ToolInputError("agency is required: a code such as R00 or a name such as 'Department of Health'")
    names = store.sql("SELECT DISTINCT agency_code, agency FROM mart.f_agency WHERE agency IS NOT NULL ORDER BY agency_code")
    if AGENCY_CODE.match(a.upper()):
        hit = [r for r in names if r["agency_code"] == a.upper()]
    else:
        hit = [r for r in names if r["agency"].lower() == a.lower()] or [r for r in names if a.lower() in r["agency"].lower()]
    codes = {r["agency_code"] for r in hit}
    if not codes:
        raise ToolInputError(f"no agency matches {agency!r}")
    if len(codes) > 1:
        raise ToolInputError(f"{agency!r} matches {len(codes)} agencies; use a code: "
                             + "; ".join(f"{r['agency_code']} {r['agency']}" for r in hit[:12]))
    code = codes.pop()
    latest = store.sql("SELECT agency FROM mart.f_agency WHERE agency_code = ? ORDER BY fiscal_year DESC LIMIT 1", [code])
    return code, latest[0]["agency"]


def agency_spending(store, agency, fiscal_year=None):
    code, name = resolve_agency(store, agency)
    y = _year(fiscal_year)
    rows = store.sql("SELECT fiscal_year, stage, operating_spending, controllable, fte, payments FROM mart.f_agency "
                     "WHERE agency_code = ? AND (? IS NULL OR fiscal_year = ?) ORDER BY fiscal_year", [code, y, y])
    if y is not None and not rows:
        yrs = store.sql("SELECT min(fiscal_year) AS a, max(fiscal_year) AS b FROM mart.f_agency WHERE agency_code = ?", [code])[0]
        raise ToolInputError(f"no FY{y} row for {code} {name}; years available: FY{yrs['a']}-FY{yrs['b']}")
    return {"agency_code": code, "agency": name, "fiscal_year": y, "rows": rows,
            "definitions": {"operating_spending": "Operating budget or actual spending, all fund types (nominal dollars)",
                            "controllable": "Controllable purchases: the budget's spending codes GMI can change (nominal dollars)",
                            "fte": "Budgeted full-time equivalent positions",
                            "payments": "Payments to payees recorded for the agency (nominal dollars); null where the payments year is partial"},
            "provenance": store.provenance(["mart.f_agency"])}


def vendor_payments(store, vendor, fiscal_year=None, top_agencies=10):
    v = str(vendor or "").strip()
    if not v:
        raise ToolInputError("vendor is required, for example 'GRAINGER'")
    y = _year(fiscal_year)
    top = max(1, min(int(top_agencies), 50))
    exact = store.sql("SELECT DISTINCT vendor FROM mart.f_vendor_pay WHERE upper(vendor) = upper(?)", [v])
    if exact:
        name = exact[0]["vendor"]
    else:
        like = store.sql("SELECT vendor, sum(paid) AS paid FROM mart.f_vendor_pay WHERE vendor ILIKE ? GROUP BY 1 ORDER BY 2 DESC LIMIT 11",
                         ["%" + v.replace("%", "").replace("_", r"\_") + "%"])
        if not like:
            raise ToolInputError(f"no vendor matches {vendor!r} (vendors paid by several agencies, mart.f_vendor_pay)")
        if len(like) > 1:
            raise ToolInputError(f"{vendor!r} matches {len(like) if len(like) <= 10 else 'more than 10'} vendors; "
                                 "use one of: " + "; ".join(r["vendor"] for r in like[:10]))
        name = like[0]["vendor"]
    by_year = store.sql("SELECT fiscal_year, sum(paid) AS paid, count(DISTINCT agency_code) AS agencies FROM mart.f_vendor_pay "
                        "WHERE vendor = ? AND (? IS NULL OR fiscal_year = ?) GROUP BY 1 ORDER BY 1", [name, y, y])
    if not by_year:
        raise ToolInputError(f"no payments to {name} in FY{y}")
    agencies = store.sql("SELECT p.agency_code, any_value(a.agency) AS agency, sum(p.paid) AS paid FROM mart.f_vendor_pay p "
                         "LEFT JOIN (SELECT DISTINCT agency_code, agency FROM mart.d_agency) a USING (agency_code) "
                         "WHERE p.vendor = ? AND (? IS NULL OR p.fiscal_year = ?) GROUP BY 1 ORDER BY 3 DESC, 1 LIMIT ?", [name, y, y, top])
    return {"vendor": name, "fiscal_year": y, "total_paid": round(sum(r["paid"] or 0 for r in by_year), 2), "by_year": by_year,
            "top_agencies": agencies,
            "note": "Payments to private vendors, merged across payee-name variants, by agency and year (mart.f_vendor_pay); nominal dollars",
            "provenance": store.provenance(["mart.f_vendor_pay", "mart.d_agency"])}


def get_sources(store):
    rec = store.reconciliation()
    rows = store.sql("SELECT * FROM mart.sources ORDER BY source") if "mart.sources" in store.tables else []
    out = []
    for r in rows:
        w = rec.get(r["source"])
        out.append({"source": r["source"], "dataset_id": r["dataset_id"], "portal_url": f"https://opendata.maryland.gov/d/{r['dataset_id']}",
                    "title": r["title"], "portal_name": r["portal_name"], "use": r["use"], "years": r["years"],
                    "portal_updated": r["portal_updated"], "rows_portal": r["rows_portal"], "rows_downloaded": r["rows_downloaded"],
                    "portal_count_matched": bool(r["reconciled"]),
                    "website_reconciliation": ({"rows_web": int(w["rows_web"]), "rows_api": int(w["rows_api"]), "years": int(w["years"]),
                                                "years_differing": int(w["years_differing"]),
                                                "status": "matches every year" if w["years_differing"] == "0" else f"{w['years_differing']} years differ"}
                                               if w else {"status": "no website download to compare"})})
    runs = store.sql("SELECT run_id, started_utc, status, checks, passed, warnings, failed FROM mart.pipeline_runs "
                     "ORDER BY started_utc DESC LIMIT 1") if "mart.pipeline_runs" in store.tables else []
    return {"datasets": out, "latest_run": runs[0] if runs else None,
            "provenance": store.provenance(["mart.sources", "mart.pipeline_runs"])}


def catalog_markdown(store):
    lines = ["# GMI Savings Tracker data catalog", "",
             f"Backend: {store.backend} ({store.provenance([])['source']}); run {store.run.get('run_id')}, as of {store.run.get('as_of')}; "
             f"latest portal update of a source {store.run.get('portal_updated')}.", "",
             "Independent prototype by Sierra Napier, built from Maryland's open data; not an official State of Maryland product.", "",
             f"Query with the `query` tool (one SELECT or WITH statement, at most {MAX_LIMIT} rows). Bare table names resolve on the "
             "search path mart, core, ref, ops, raw.", ""]
    layer = None
    for q, t in store.tables.items():
        if t["layer"] != layer:
            layer = t["layer"]
            lines += ["", f"## {layer}", "", "| table | rows | description |", "|---|---|---|"]
        lines.append(f"| `{q}` | {t['rows']:,} | {store.describe_table_short(q).replace('|', '/')} |")
    return "\n".join(lines) + "\n"
