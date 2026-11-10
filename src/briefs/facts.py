"""Facts behind each agency's one-line brief, computed from the marts (read through the MCP server's read-only Store).

One fact set per agency for the latest fiscal year with payments: payments and the change from the year before,
operating spending and its budget stage, controllable purchases, and the private vendor the agency paid most. Every number a
brief may use is a value here; the guardrail (guardrail.py) checks generated sentences against exactly these values.
"""
from src.mcp.store import Store


def fmt_money(v):
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:,.2f} billion"
    if a >= 1e6:
        return f"${v / 1e6:,.1f} million"
    return f"${v:,.0f}"


def fmt_pct(v):
    return f"{abs(v) * 100:.1f}%"


def latest_year(store):
    return store.sql("SELECT max(fiscal_year) AS y FROM mart.f_agency WHERE payments IS NOT NULL")[0]["y"]


def agency_facts(store=None, fiscal_year=None):
    """[{agency_code, agency, fiscal_year, prior_year, payments, payments_prior, payments_change, operating_spending, stage,
    controllable, top_vendor, top_vendor_paid, display: {name: formatted}}] sorted by payments, largest first."""
    store = store or Store()
    y = int(fiscal_year or latest_year(store))
    rows = store.sql(
        "SELECT a.agency_code, a.agency, a.fiscal_year, a.payments, p.payments AS payments_prior, a.operating_spending, a.stage, "
        "a.controllable FROM mart.f_agency a LEFT JOIN mart.f_agency p ON p.agency_code = a.agency_code AND p.fiscal_year = a.fiscal_year - 1 "
        "WHERE a.fiscal_year = ? AND a.payments > 0 ORDER BY a.payments DESC, a.agency_code", [y])
    top = {r["agency_code"]: r for r in store.sql(
        "SELECT agency_code, vendor, paid FROM (SELECT agency_code, vendor, round(sum(paid), 2) AS paid, "
        "row_number() OVER (PARTITION BY agency_code ORDER BY sum(paid) DESC, vendor) AS k FROM mart.f_vendor_pay "
        "WHERE fiscal_year = ? GROUP BY 1, 2) WHERE k = 1", [y])}
    out = []
    for r in rows:
        f = {"agency_code": r["agency_code"], "agency": r["agency"], "fiscal_year": y, "prior_year": y - 1,
             "payments": round(r["payments"], 2), "payments_prior": round(r["payments_prior"], 2) if r["payments_prior"] else None,
             "payments_change": None, "operating_spending": r["operating_spending"], "stage": r["stage"],
             "controllable": r["controllable"], "top_vendor": None, "top_vendor_paid": None}
        if f["payments_prior"]:
            f["payments_change"] = round(f["payments"] / f["payments_prior"] - 1, 6)
        t = top.get(r["agency_code"])
        if t:
            f["top_vendor"], f["top_vendor_paid"] = t["vendor"], t["paid"]
        f["display"] = {k: fmt_money(f[k]) for k in ("payments", "payments_prior", "operating_spending", "controllable", "top_vendor_paid") if f[k]}
        if f["payments_change"] is not None:
            f["display"]["payments_change"] = ("up " if f["payments_change"] >= 0 else "down ") + fmt_pct(f["payments_change"])
        out.append(f)
    return out
