"""GMI reported savings and the public-payments check for each item.

Reported figures come from the Governor's Government Modernization Initiative Joint Chairmen's Report
(January 26, 2026). Each item is paired, where possible, with the payments to vendors that would show
the saving: payee names that sell the thing being cut (wireless carriers for phone plans, dealers for
vehicle purchases, and so on). The check compares FY2025 with FY2026 payments; it shows direction and
size, not proof, because payee names miss some spending and contracts change for other reasons.
"""
import re

import pandas as pd

SRC = "DBM, Government Modernization Initiative Final Report (Joint Chairmen's Report p. 77), Jan 26, 2026"
URL = "https://governor.maryland.gov/media/893"

DGS_SRC = "DGS, Government Modernization: right-sizing State facilities"
DGS_URL = "https://dgs.maryland.gov/Pages/Announcements/GovernmentModernization.aspx"
VEH = r"\b(FORD|CHEVROLET|NISSAN|TOYOTA|DODGE|CHRYSLER|JEEP|RAM TRUCKS|HONDA|HYUNDAI|SUBARU|GMC|MOTOR SALES|AUTO SALES|AUTOMOTIVE GROUP)\b"
SOFTWARE = r"\b(CARAHSOFT|SHI INTERNATIONAL|MICROSOFT|ORACLE|SALESFORCE|ADOBE|SERVICENOW|GOOGLE|AMAZON WEB|SOFTWARE ONE|SOFTWAREONE|CDW)\b"
# Every item and figure below is quoted from the GMI Final Report (DBM, Jan 26, 2026) unless its source says otherwise.
# check: None = no public payment line; "same:<id>" = checked with that item; "union:<ids>" = the listed checks together;
#        "agency:<codes>|<payee regex>" = payee pattern limited to those agencies; "lens:<area>" = payee focus area
ITEMS = [
    dict(id="S01", ws="Vendor contracts", item="Review and update agreements with seven vendors (~$81M annual spend)", lo=18e6, hi=18e6, type="Year over year", status="Reported",
         count="7 vendors", check="union:S02,S03,S04,S05", page="pp. 15-16",
         quote="supported efforts to review and update agreements with seven of the State's vendors (approx. $81M in annual spend) ... These two strategies helped achieve $18M in YoY savings",
         note="The report names four kinds of contract (rows below) but no vendors and no split of the $18M; this row checks the four together."),
    dict(id="S02", ws="Vendor contracts", item="Food services contract at one agency", lo=None, hi=None, type="Part of the $18M", status="Named, no figure",
         check=r"agency:Q00|\bARAMARK\b", page="p. 15", quote="a food services contract at one agency",
         note="The agency and vendor are not named. Checked against Aramark Correctional Services at Public Safety and Correctional Services, the largest food-service payee; it may not be the contract meant."),
    dict(id="S03", ws="Vendor contracts", item="Statewide radio system maintenance", lo=None, hi=None, type="Part of the $18M", status="Named, no figure",
         check=r"agency:F50|\bMOTOROLA\b", page="p. 15", quote="statewide radio system maintenance ... a radio communications contractor",
         note="Checked against Motorola Solutions payments by the Department of Information Technology, which runs the statewide radio system; the report does not name the contractor."),
    dict(id="S04", ws="Vendor contracts", item="Office supplies (DGS Office of State Procurement contract)", lo=None, hi=None, type="Part of the $18M", status="Named, no figure",
         check=r"\b(OFFICE DEPOT|STAPLES|W B MASON|WB MASON|OFFICEMAX)\b", page="pp. 15-16", quote="office supplies ... DGS OSP",
         note="Most office supplies are bought on purchasing cards, which this payments dataset does not show, so payments here are small."),
    dict(id="S05", ws="Vendor contracts", item="Software Enterprise License Agreement (DoIT)", lo=None, hi=None, type="Part of the $18M", status="Named, no figure",
         check="agency:F50|" + SOFTWARE, page="pp. 15-16", quote="Enterprise License Agreement (ELA) negotiation to establish a unified statewide strategy",
         note="Checked against software and software-reseller payments by the Department of Information Technology; the report does not name the software. SHI and CDW also sell laptops, so this overlaps the laptop check for DoIT."),
    dict(id="S06", ws="Fleet", item="Paused vehicle purchases (196 of 538 appropriated)", lo=8e6, hi=8e6, type="One-time", status="Reported", count="196 purchases",
         check=VEH, page="p. 11", quote="For FY2026 the State saved ~$8M via paused purchases."),
    dict(id="S07", ws="Fleet", item="Sale of underutilized vehicles (271 sold by Nov 2025)", lo=2.2e6, hi=2.2e6, type="One-time", status="Reported", count="271 vehicles",
         check=None, page="p. 10", quote="GMI achieved $2.2 million in one-time savings from selling underutilized vehicles",
         note="Sale proceeds are money the state receives; the payments and budget datasets record spending only."),
    dict(id="S08", ws="Fleet", item="Fuel and maintenance for a smaller fleet", lo=0.8e6, hi=0.8e6, type="Recurring", status="Reported", count="~520 vehicles",
         check=r"\b(FUEL|PETROLEUM|OIL CO|TIRE|AUTO PARTS|FLEET SERVICES|ELEMENT FLEET|WEX|MOTOR SERVICE|AUTO REPAIR)\b", page="p. 10", quote="yielding $0.8 million in recurring savings"),
    dict(id="S09", ws="Fleet", item="Lowest-cost maintenance vendors", lo=1.3e6, hi=1.3e6, type="Recurring", status="Projected", count="~9,700 vehicles",
         check="same:S08", page="p. 12", quote="projected to generate approximately $1.3 million in annual savings"),
    dict(id="S10", ws="Telecom", item="End low-use mobile phone lines", lo=0.5e6, hi=0.5e6, type="Recurring", status="Reported", count="~1,000 lines",
         check=r"\b(VERIZON WIRELESS|CELLCO|T-MOBILE|T MOBILE|AT&T MOBILITY|SPRINT)\b", page="pp. 4, 12", quote="The State will save about $0.5 million annually."),
    dict(id="S11", ws="Telecom", item="Consolidated mobile phone plan catalog", lo=2.1e6, hi=2.3e6, type="Recurring", status="Projected",
         check="same:S10", page="p. 17", quote="seeks to achieve $2.1 – $2.3 million in annual savings"),
    dict(id="S12", ws="Telecom", item="Cancel unused copper landlines", lo=1.4e6, hi=1.7e6, type="Recurring", status="Projected", count="~10,000 lines reviewed",
         check=r"\b(VERIZON MARYLAND|VERIZON BUSINESS|VERIZON SERVICES|VERIZON(?! WIRELESS)|COMCAST|LUMEN|CENTURYLINK|WINDSTREAM)\b", page="p. 14",
         quote="projected to generate approximately $1.4–$1.7 million in statewide savings upon completion"),
    dict(id="S13", ws="IT hardware", item="Laptop refresh moved from 3 to 5 years (DoIT agencies)", lo=1.5e6, hi=1.5e6, type="Recurring", status="Reported",
         check=r"\b(DELL MARKETING|DELL TECHNOLOGIES|DELL INC|DELL FEDERAL|LENOVO|HP INC|HEWLETT|CDW|SHI INTERNATIONAL|APPLE INC|APPLE COMPUTER|MICROAGE|PROMARK)\b",
         page="p. 13", quote="Changing the refresh cycle will save about $1.5 million across the State annually."),
    dict(id="S14", ws="IT hardware", item="Standard laptop specifications", lo=1.5e6, hi=1.5e6, type="Recurring", status="Reported", check="same:S13", page="p. 14",
         quote="Changing laptops specs will save about $1.5 million across the State annually."),
    dict(id="S15", ws="IT hardware", item="New laptop pricing model", lo=1.9e6, hi=1.9e6, type="Recurring", status="Projected", check="same:S13", page="p. 15",
         quote="Approximately $1.9M in annual savings"),
    dict(id="S16", ws="Shipping", item="Statewide shipping contract, ground by default", lo=0.8e6, hi=0.8e6, type="Recurring", status="Reported", count="$13M postage spend",
         check=r"\b(FEDEX|FEDERAL EXPRESS|UPS|UNITED PARCEL|PITNEY|POSTMASTER|USPS|POSTAL SERVICE|DHL)\b", page="p. 17", quote="totaling $800k annually on shipping costs"),
    dict(id="S17", ws="Real estate", item="Lease portfolio optimization", lo=None, hi=None, type="Not stated", status="Not quantified", check="lens:Real estate & leases",
         page="GMI report", quote="(no dollar figure given)"),
    dict(id="S18", ws="Real estate", item="Baltimore facility decisions: State Center, three office towers, MDH capital lease (DGS)", lo=326341056, hi=326341056,
         type="Cost avoidance", status="Estimated (DGS)", count="7 facilities", check=None, page="DGS announcement",
         quote="more than $326 million ... estimated savings", src=DGS_SRC, url=DGS_URL,
         note="Mostly avoided renovation and capital costs over several years, not yearly operating savings, so it is shown separately and not counted toward the $50M a year."),
]


def _match(p, spec):
    if spec.startswith("lens:"):
        return (p.lens == spec[5:]) & ~p.passthrough.astype(bool)
    if spec.startswith("agency:"):
        codes, pat = spec[7:].split("|", 1)
        return p.agency_code.isin(codes.split(",")) & p.payee.str.contains(pat, flags=re.I, regex=True)
    return p.payee.str.contains(spec, flags=re.I, regex=True)


def build(pm):
    """pm: payments model rows (fiscal_year, agency_code, vendor_name, family, amount, is_government)."""
    p = pm[(pm.fiscal_year >= 2022) & (~pm.is_government.astype(bool))].copy()
    p["payee"] = p.vendor_name.astype(str).str.upper()  # match on the payee name as paid (families merge carriers' wireless and wireline arms)
    masks = {it["id"]: _match(p, it["check"]) for it in ITEMS if it["check"] and not it["check"].startswith(("same:", "union:"))}
    for it in ITEMS:
        if it["check"] and it["check"].startswith("union:"):
            m = pd.Series(False, index=p.index)
            for k in it["check"][6:].split(","):
                m |= masks[k]
            masks[it["id"]] = m
    rows, facts = [], []
    for it in ITEMS:
        sid, chk, why = it["id"], it["check"], it.get("note", "")
        check = None
        if chk and chk.startswith("same:"):
            check = chk[5:]
            why = why or "Checked together with the related item above; payments cannot separate the two."
        elif chk:
            check = sid
            m = p[masks[sid]]
            g = m.groupby(["fiscal_year", "agency_code"], dropna=False).amount.sum().reset_index()
            g["check_id"] = sid
            facts.append(g)
            top = m[m.fiscal_year == 2026].groupby("payee").amount.sum().nlargest(3)
            why = (why + " " if why else "") + "Payees: " + ", ".join(top.index.str.title())
        rows.append({"saving_id": sid, "workstream": it["ws"], "item": it["item"], "reported_low": it["lo"], "reported_high": it["hi"], "type": it["type"],
                     "status": it["status"], "count": it.get("count", ""), "check_id": check, "check_note": why.strip(),
                     "source": it.get("src", SRC), "source_url": it.get("url", URL), "source_page": it["page"], "source_quote": it["quote"]})
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
