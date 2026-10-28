"""Staged and modeled layers: master lists, spending-code model and agency-year model."""
import difflib
import re

import numpy as np
import pandas as pd

import payments_legacy as P  # payee-name normalization, focus-area tagging, CPI
from common import RUN

# ---------------------------------------------------------------- spending scope
STAGE = {"Budget - Actual": "Actual", "Budget - Working": "Working budget", "Budget - Appropriation": "Appropriation",
         "Budget - Governors Allowance": "Governor's allowance"}
EXCLUDED_OBJECTS = {"Salaries, Wages and Fringe Benefits", "Grants, Subsidies, and Contributions", "Land and Structures",
                    "Technical and Special Fees"}
# Payments to clients and providers, and debt service: not purchases an agency can renegotiate
ENTITLEMENT_CODES = {830, 818, 820, 836, 838, 1306, 1307}
INTERNAL_CODES = {305, 876, 882, 1303}  # DoIT and in-state allocations, rent paid to DGS
# Programs whose contractual line pays insurers, providers or households rather than buying goods or services
PASS_THROUGH_PROGRAMS = (r"Reinsurance|Provider Reimbursements|Foster Care Maintenance|Health Services Cost Review|"
                         r"Home Energy Programs|Housing and Building Energy Programs|Renewable and Clean Energy Programs")


def clean_agency(s):
    return s.str.replace(r":[A-Z]\d\d$", "", regex=True).str.strip()


def official_stages(text):
    """Budget stage per fiscal year from the Operating Budget site's own statement, e.g.
    "...FY2023, FY 2024, and FY2025 Actual Budgets, FY 2026 Working Budget, and the FY 2027 Legislative Appropriation."
    The dataset's own `type` column is not used: it keeps the label each year had when it was loaded
    (FY2021 "Working", FY2022 "Appropriation", FY2027 "Governors Allowance") after the year moves on."""
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    m = re.search(r"includes (.*?) Actual Budgets?,? (?:and )?FY ?(\d{4}) Working Budget,? (?:and )?(?:the )?FY ?(\d{4}) (Legislative Appropriation|Governor's Allowance|Governors Allowance)", t, re.I)
    if not m:
        return None
    out = {int(y): "Actual" for y in re.findall(r"(\d{4})", m.group(1))}
    out[int(m.group(2))] = "Working budget"
    out[int(m.group(3))] = "Legislative appropriation" if m.group(4).lower().startswith("legislative") else "Governor's allowance"
    return out


def budget_model(b, stages=None):
    b = b.copy()
    b["agency_name"] = clean_agency(b.agency_name)
    b["fiscal_year"] = b.fiscal_year.astype(int)
    b["budget"] = pd.to_numeric(b.budget, errors="coerce").fillna(0.0)
    b["code"] = pd.to_numeric(b.comptroller_subobject_code, errors="coerce").astype("Int64")
    b["file_stage"] = b["type"].map(STAGE).fillna(b["type"])
    b["stage"] = b.fiscal_year.map(stages) if stages else b.file_stage
    sub = b.comptroller_subobject_name.fillna("")
    b["internal"] = b.code.isin(INTERNAL_CODES) | sub.str.contains(r"Allocation|^Instate|^In State", case=False)
    b["entitlement"] = b.code.isin(ENTITLEMENT_CODES) | b.program_name.fillna("").str.contains(PASS_THROUGH_PROGRAMS)
    b["controllable"] = ~b.object_name.isin(EXCLUDED_OBJECTS) & ~b.entitlement & ~b.internal
    it = sub.str.contains(r"Data Proc|Software|Computer|Programming|Sys Analysis|Data Entry|Microcomputer|Mainframe", case=False)
    area = pd.Series(None, index=b.index, dtype=object)
    area[b.object_name == "Motor Vehicle Operation and Maintenance"] = "Fleet & fuel"
    area[it] = "IT hardware, software & services"
    area[(b.object_name == "Communications") & (b.code != 301)] = "Telecom"
    area[b.code.isin([301, 804])] = "Print, copy & mail"
    area[(b.object_name == "Fuel and Utilities") & ~sub.str.contains("Loan", case=False)] = "Utilities & facility energy"
    area[b.code == 1301] = "Real estate & leases"
    area[~b.controllable] = None
    b["area"] = area
    return b


# ---------------------------------------------------------------- agency master
MDOT = {"J01", "J02", "J03", "J04", "J05", "J06"}  # modal administrations, one budget agency (J00)
# Older payment agency names with no agency code: payment-name pattern -> budget agency-name pattern
MANUAL = {
    r"^DHMH|HEALTH AND MENTAL HYGIENE|^DEPT OF HEALTH": r"^Maryland Department of Health$",
    r"HUMAN RESOURCES": r"^Department of Human Services$",
    r"LABOR, LICENSING": r"^Maryland Department of Labor$",
    r"BUSINESS & ECONOMIC DEVELOPMENT$|^DEPT OF COMMERCE$": r"^Department of Commerce$",
    r"DEPT\. OF AGING": r"^Department of Aging$",
    r"^ENERGY ADMINISTRATION$": r"^Maryland Energy Administration$",
    r"OFFICE OF PLANNING": r"^Department of Planning$",
    r"COMMISSION ON HUMAN RELATIONS": r"Civil Rights",
    r"DISPARITY GRANTS|PROPERTY TAX GRANT|MISCELLANEOUS GRANTS": r"^Payments to Civil Divisions",
    r"PUBLIC SCHOOL CONSTRUCTION PROGRAM": r"School Construction",
    r"SUBSEQUENT INJURY FUND": r"^Subsequent Injury Fund$",
}
DIRECT = {r"^MARYLAND ENVIRONMENTAL SERVICE$": "U10"}  # payment-only agency code
CAPITAL = r"CAPITAL|CAP PROJ|- ?CAP\b|-CAP$"


def agency_master(pay, budget):
    bud = clean_agency(budget.sort_values("fiscal_year").groupby("agency_code").agency_name.last())
    codes = set(bud.index)
    mdot = next((c for c in codes if c.startswith("J00")), None)
    p = pay[["fiscal_year", "agency_name", "category"]].drop_duplicates()
    coded = p[p.category.str.match(r"^[A-Z]\d\d$", na=False)].copy()
    coded["code"] = coded.category.where(~coded.category.isin(MDOT) | (mdot is None), mdot)
    name2code = coded.groupby("agency_name").code.agg(lambda s: s.value_counts().index[0]).to_dict()
    names = sorted(p.agency_name.unique())
    known = list(name2code)
    def by_budget_name(pat):
        hit = [k for k, v in bud.items() if re.search(pat, str(v))]
        return hit[0] if hit else None
    rows = []
    for n in names:
        if n in name2code:
            c, how = name2code[n], "agency code in payments"
        elif re.search(CAPITAL, n):
            c, how = "CAPITAL", "capital budget account"
        else:
            c = next((by_budget_name(v) for k, v in MANUAL.items() if re.search(k, n)), None) \
                or next((v for k, v in DIRECT.items() if re.search(k, n)), None)
            how = "manual rename" if c else None
            if not c:
                m = difflib.get_close_matches(n, known, n=1, cutoff=0.88)
                c, how = (name2code[m[0]], f"closest name ({m[0]})") if m else (None, "unmatched")
        rows.append({"payment_agency_name": n, "agency_code": c, "matched_by": how})
    am = pd.DataFrame(rows)
    am["agency"] = am.agency_code.map(bud).fillna(am.agency_code.map(coded.groupby("code").agency_name.last()))
    am.loc[am.agency_code == "CAPITAL", "agency"] = "Capital projects (capital budget, not in the operating budget)"
    am["in_budget"] = am.agency_code.isin(codes)
    return am


# ---------------------------------------------------------------- vendor master
FAMILIES = [  # company families that appear under several payee names
    ("VERIZON", r"VERIZON|CELLCO|^MCI\b"), ("AT&T", r"^AT & T|^AT T\b|AT&T"), ("COMCAST", r"COMCAST"),
    ("T-MOBILE", r"T MOBILE|SPRINT"), ("PITNEY BOWES", r"PITNEY BOWES"), ("XEROX", r"^XEROX"), ("CANON", r"^CANON"),
    ("RICOH", r"^RICOH"), ("DELL", r"^DELL\b"), ("CDW", r"^CDW"), ("SHI INTERNATIONAL", r"^SHI\b"),
    ("CARAHSOFT", r"CARAHSOFT"), ("MICROSOFT", r"MICROSOFT"), ("ORACLE", r"ORACLE"), ("IBM", r"^IBM\b|INTERNATIONAL BUSINESS MACHINES"),
    ("BALTIMORE GAS & ELECTRIC", r"BALTIMORE GAS & ELECTRIC|^BGE\b"), ("PEPCO", r"PEPCO|POTOMAC ELECTRIC"),
    ("WASHINGTON GAS", r"WASHINGTON GAS"), ("CONSTELLATION ENERGY", r"^CONSTELLATION (?:NEW ?ENERGY|ENERGY|HOME|SOLAR|RENEWABLES)|^CONSTELLATION$"), ("DELMARVA POWER", r"^DELMARVA POWER"),
    ("ELEMENT FLEET", r"ELEMENT FLEET"), ("CARROLL INDEPENDENT FUEL", r"CARROLL INDEPENDENT FUEL"),
    ("GRAINGER", r"GRAINGER"), ("STAPLES", r"^STAPLES"), ("OFFICE DEPOT", r"OFFICE DEPOT"), ("AMAZON", r"^AMAZON"),
    ("GARTNER", r"GARTNER"), ("DELOITTE", r"DELOITTE"), ("ACCENTURE", r"ACCENTURE"), ("BOOZ ALLEN", r"BOOZ ALLEN"),
    ("MAXIMUS", r"MAXIMUS"), ("CONDUENT", r"CONDUENT|XEROX STATE"), ("UNITEDHEALTHCARE", r"UNITEDHEALTH"),
]


def vendor_master(pay):
    v = pay[["vendor_name"]].copy()
    v["vendor_key"] = v.vendor_name.map(P.norm)
    v["family"] = v.vendor_key.str.replace(" ", "", regex=False)  # same name apart from spacing
    first = v.groupby("family").vendor_key.agg(lambda x: x.value_counts().index[0])
    v["family"] = v.family.map(first)
    for fam, pat in FAMILIES:
        v.loc[v.vendor_key.str.contains(pat, regex=True), "family"] = fam
    v = v.drop_duplicates()
    v["is_government"] = v.vendor_key.str.contains(P.GOV)
    return v


# ---------------------------------------------------------------- modeled tables
def payments_model(pay, am, vm):
    p = pay.copy()
    p["fiscal_year"] = p.fiscal_year.astype(int)
    p["amount"] = pd.to_numeric(p.amount, errors="coerce").fillna(0.0)
    p = P.tag(p)  # focus-area tagging with pass-through exclusions (adds vnorm, lens, passthrough)
    p = p.merge(am[["payment_agency_name", "agency_code", "agency"]], left_on="agency_name", right_on="payment_agency_name", how="left")
    fam = vm.drop_duplicates("vendor_name").set_index("vendor_name")
    p["family"] = p.vendor_name.map(fam.family)
    p["is_government"] = p.vendor_name.map(fam.is_government).fillna(False)
    return p


def agency_year(bm, fte, pm):
    # every year, with its budget stage: actual spending for most years, budgets for FY2021-22 and FY2026-27
    a = bm.groupby(["agency_code", "fiscal_year", "stage"]).agg(
        budget_actual=("budget", "sum"),
        controllable=("budget", lambda s: s[bm.loc[s.index, "controllable"]].sum())).reset_index()
    f = fte.copy()
    f["fiscal_year"] = f.fiscal_year.astype(int)
    f["count"] = pd.to_numeric(f["count"], errors="coerce").fillna(0)
    f = f.groupby(["agency_code", "fiscal_year"])["count"].sum().rename("fte").reset_index()
    pay = pm[pm.agency_code.notna()].groupby(["agency_code", "fiscal_year"]).amount.sum().rename("payments").reset_index()
    out = a.merge(f, on=["agency_code", "fiscal_year"], how="outer").merge(pay, on=["agency_code", "fiscal_year"], how="outer")
    names = bm.sort_values("fiscal_year").groupby("agency_code").agency_name.last()
    out["agency"] = out.agency_code.map(names)
    out["controllable_per_fte"] = np.where(out.fte > 0, out.controllable / out.fte, np.nan)
    return out.sort_values(["agency_code", "fiscal_year"])
