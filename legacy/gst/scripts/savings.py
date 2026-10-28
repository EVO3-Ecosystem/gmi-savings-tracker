"""GMI reported savings and the public-payments check for each item.

Reported figures come from the Governor's Government Modernization Initiative Joint Chairmen's Report
(January 26, 2026). Each item is paired, where possible, with the payments to vendors that would show
the saving: payee names that sell the thing being cut (wireless carriers for phone plans, dealers for
vehicle purchases, and so on). The check compares FY2025 with FY2026 payments; it shows direction and
size, not proof, because payee names miss some spending and contracts change for other reasons.
"""
import re

import pandas as pd

SRC = "GMI Joint Chairmen's Report, Jan 26, 2026"
URL = "https://governor.prod.maryland.gov/media/893"

# workstream, item, reported low, high (dollars a year), type, status, count, payee pattern (None = no public check), why
ITEMS = [
    ("Vendor contracts", "Oversight and renegotiation of 7 vendors (~$81M annual spend)", 18e6, 18e6, "Year over year", "Reported", "7 vendors", None,
     "GMI did not name the seven vendors, so no single payment line matches this item. The payments data covers every vendor, so the table of largest vendor decreases below lists the candidates."),
    ("Fleet", "Paused vehicle purchases (196 of 538 appropriated)", 8e6, 8e6, "One-time", "Reported", "196 purchases",
     r"\b(FORD|CHEVROLET|NISSAN|TOYOTA|DODGE|CHRYSLER|JEEP|RAM TRUCKS|HONDA|HYUNDAI|SUBARU|GMC|MOTOR SALES|AUTO SALES|AUTOMOTIVE GROUP)\b", ""),
    ("Fleet", "Sale of underutilized vehicles (271 sold by Nov 2025)", 2.2e6, 2.2e6, "One-time", "Reported", "271 vehicles", None,
     "Sale proceeds are money the state receives. The payments and budget datasets record spending only, so the sales do not appear in either."),
    ("Fleet", "Fuel and maintenance for a smaller fleet", 0.8e6, 0.8e6, "Recurring", "Reported", "~520 vehicles",
     r"\b(FUEL|PETROLEUM|OIL CO|TIRE|AUTO PARTS|FLEET SERVICES|ELEMENT FLEET|WEX|MOTOR SERVICE|AUTO REPAIR)\b", ""),
    ("Fleet", "Lowest-cost maintenance vendors", 1.3e6, 1.3e6, "Recurring", "Projected", "~9,700 vehicles", "same:Fleet|Fuel and maintenance for a smaller fleet", ""),
    ("Telecom", "End low-use mobile phone lines", 0.5e6, 0.5e6, "Recurring", "Reported", "~1,000 lines",
     r"\b(VERIZON WIRELESS|CELLCO|T-MOBILE|T MOBILE|AT&T MOBILITY|SPRINT)\b", ""),
    ("Telecom", "Consolidated mobile phone plan catalog", 2.1e6, 2.3e6, "Recurring", "Projected", "", "same:Telecom|End low-use mobile phone lines", ""),
    ("Telecom", "Cancel unused copper landlines", 1.4e6, 1.7e6, "Recurring", "Projected", "~10,000 lines reviewed",
     r"\b(VERIZON MARYLAND|VERIZON BUSINESS|VERIZON SERVICES|VERIZON(?! WIRELESS)|COMCAST|LUMEN|CENTURYLINK|WINDSTREAM)\b", ""),
    ("IT hardware", "Laptop refresh moved from 3 to 5 years (DoIT agencies)", 1.5e6, 1.5e6, "Recurring", "Reported", "",
     r"\b(DELL MARKETING|DELL TECHNOLOGIES|DELL INC|DELL FEDERAL|LENOVO|HP INC|HEWLETT|CDW|SHI INTERNATIONAL|APPLE INC|APPLE COMPUTER|MICROAGE|PROMARK)\b", ""),
    ("IT hardware", "Standard laptop specifications", 1.5e6, 1.5e6, "Recurring", "Reported", "", "same:IT hardware|Laptop refresh moved from 3 to 5 years (DoIT agencies)", ""),
    ("IT hardware", "New laptop pricing model", 1.9e6, 1.9e6, "Recurring", "Projected", "", "same:IT hardware|Laptop refresh moved from 3 to 5 years (DoIT agencies)", ""),
    ("Shipping", "Statewide shipping contract, ground by default", 0.8e6, 0.8e6, "Recurring", "Reported", "$13M postage spend",
     r"\b(FEDEX|FEDERAL EXPRESS|UPS|UNITED PARCEL|PITNEY|POSTMASTER|USPS|POSTAL SERVICE|DHL)\b", ""),
    ("Office supplies", "Renegotiated office supply pricing (10–20% discounts)", None, None, "Recurring", "Not quantified", "",
     r"\b(OFFICE DEPOT|STAPLES|W B MASON|WB MASON|OFFICEMAX)\b", ""),
    ("Real estate", "Lease portfolio optimization", None, None, "Not stated", "Not quantified", "", "lens:Real estate & leases",
     ""),
]


def build(pm):
    """pm: payments model rows (fiscal_year, agency_code, vendor_name, family, amount, is_government)."""
    p = pm[(pm.fiscal_year >= 2022) & (~pm.is_government.astype(bool))].copy()
    p["payee"] = p.vendor_name.astype(str).str.upper()  # match on the payee name as paid (families merge carriers' wireless and wireline arms)
    rows, facts = [], []
    keys = {}
    for i, (ws, item, lo, hi, kind, status, count, pat, why) in enumerate(ITEMS, 1):
        sid = f"S{i:02d}"
        check = None
        if pat and pat.startswith("same:"):
            check = keys[pat[5:]]
            why = "Checked together with the related item above; payments cannot separate the two."
        elif pat:
            check = sid
            m = p[(p.lens == pat[5:]) & ~p.passthrough.astype(bool)] if pat.startswith("lens:") else p[p.payee.str.contains(pat, flags=re.I, regex=True)]
            g = m.groupby(["fiscal_year", "agency_code"], dropna=False).amount.sum().reset_index()
            g["check_id"] = sid
            facts.append(g)
            top = m[m.fiscal_year == 2026].groupby("payee").amount.sum().nlargest(3)
            why = why or "Payees: " + ", ".join(top.index.str.title())
        keys[f"{ws}|{item}"] = sid
        rows.append({"saving_id": sid, "workstream": ws, "item": item, "reported_low": lo, "reported_high": hi, "type": kind,
                     "status": status, "count": count, "check_id": check, "check_note": why, "source": SRC, "source_url": URL})
    d = pd.DataFrame(rows)
    f = pd.concat(facts, ignore_index=True).rename(columns={"amount": "paid"})
    f["paid"] = f.paid.round(2)
    # largest vendor decreases FY2025 to FY2026: candidates for the unnamed renegotiated contracts
    q = p[~p.passthrough.astype(bool) & p.fiscal_year.isin([2024, 2025, 2026]) & ~p.agency_code.isin(["CAPITAL", "D06", "D25"])].copy()  # operating spending only
    q["vendor"] = q.family.fillna(q.vendor_name).astype(str)
    v = q.pivot_table(index="vendor", columns="fiscal_year", values="amount", aggfunc="sum", fill_value=0)
    ag = q[q.fiscal_year == 2025].groupby("vendor").agency_code.nunique()
    # GMI renegotiated statewide procurement contracts, so keep vendors paid by five or more agencies and
    # leave out construction, health plans, banks and trustees, schools and governments, which are not that kind of contract
    skip = r"CONSTRUCT|PAVING|CONTRACTING|MCO|HEALTH PLAN|PARTNERS MCO|TRUST|BANK|SCHOOL|ACADEMY|UNIVERSITY|COLLEGE|HOSPITAL|COUNTY|CITY OF|\bJV\b|BUS SALES|NOVA BUS|INSURANCE|MEDICAL CENTER|YESHIVA|TALMUD|BNOS|ROOF|MECHANICAL|CORPS OF ENGINEERS|HEALTH|TITLE|RESCUE|BUILDERS|EXCAVAT|BRIDGE|STEEL|CONCRETE"
    ag_all = q[q.fiscal_year == 2025].groupby("vendor").agency_code.nunique()
    v = v[(ag_all.reindex(v.index).fillna(0) >= 5) & ~v.index.str.upper().str.contains(skip, regex=True)]
    v = v[(v[2025] >= 1e6) & (v[2026] > 0)].assign(change=lambda x: x[2026] - x[2025]).sort_values("change").head(40)
    mv = pd.DataFrame({"vendor": v.index.str.title(), "fy2024": v[2024].round(2).values, "fy2025": v[2025].round(2).values, "fy2026": v[2026].round(2).values,
                       "change": v.change.round(2).values, "agencies": ag_all.reindex(v.index).fillna(0).astype(int).values})
    return d, f[["check_id", "fiscal_year", "agency_code", "paid"]], mv
