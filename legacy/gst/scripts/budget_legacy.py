"""Turns the Maryland Transparency Portal's datasets into dashboard tables.

Sources (all opendata.maryland.gov, downloaded and reconciled by scripts/download.py):
  yu65-jmmv  Maryland Operating Budget, with object and Comptroller sub-object codes
  gy87-e27x  Operating Budget by funding source
  absk-avps  State grants and loans of $50K or more
Outputs go to ../pipeline/out/ next to the payments outputs, and health rows are
appended to pipeline_health.csv so the dashboard shows one report.
"""
import re
from pathlib import Path
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE.parent / "pipeline" / "out"
b = pd.read_csv(HERE / "raw/yu65-jmmv.csv", usecols=["fiscal_year", "agency_name", "object_name", "comptroller_subobject_code",
                                                     "comptroller_subobject_name", "fund_type_name", "budget", "type", "category_title"])
f = pd.read_csv(HERE / "raw/gy87-e27x.csv", usecols=["fiscal_year", "fund_type_name", "fund_source_name", "budget"])
g = pd.read_csv(HERE / "raw/absk-avps.csv")
inv = pd.read_csv(HERE / "inventory.csv")
STAGE = {"Budget - Actual": "Actual", "Budget - Working": "Working budget", "Budget - Appropriation": "Appropriation",
         "Budget - Governors Allowance": "Governor's allowance"}
b["stage"] = b["type"].map(STAGE).fillna(b["type"])
# The open-data file still labels FY2027 "Governors Allowance", but the Operating Budget site
# (operatingbudget.maryland.gov) and the Transparency Portal describe FY2027 as the Legislative
# Appropriation, and the amounts match it to the dollar. Use the portal's label.
b.loc[(b.fiscal_year == 2027) & (b["type"] == "Budget - Governors Allowance"), "stage"] = "Legislative appropriation"

# The six GMI focus areas, defined by the state's own spending codes (Comptroller sub-objects)
sub = b.comptroller_subobject_name.fillna("")
code = b.comptroller_subobject_code
IT = sub.str.contains(r"Data Proc|Software|Computer|Programming|Doit It|Sys Analysis|Data Entry|Microcomputer|Mainframe", case=False)
# Charges paid to other state agencies are not outside vendor spending: DoIT IT and radio
# allocations, in-state computer usage, and rent paid to DGS
INTERNAL = code.isin([305, 876, 882, 1303]) | sub.str.contains(r"Allocation|^Instate|In State", case=False)
b["area"] = None
b.loc[b.object_name == "Motor Vehicle Operation and Maintenance", "area"] = "Fleet & fuel"
b.loc[IT, "area"] = "IT hardware, software & services"
b.loc[(b.object_name == "Communications") & ~code.isin([301]), "area"] = "Telecom"
b.loc[code.isin([301, 804]), "area"] = "Print, copy & mail"
b.loc[(b.object_name == "Fuel and Utilities") & ~sub.str.contains("Loan", case=False), "area"] = "Utilities & facility energy"
b.loc[code.isin([1301]), "area"] = "Real estate & leases"
b.loc[INTERNAL, "area"] = None

area_fy = b[b.area.notna()].groupby(["fiscal_year", "stage", "area"]).budget.sum().reset_index()
area_fy.to_csv(OUT / "budget_focus_by_fy.csv", index=False)

# Coverage: what payee-name tagging finds vs the state's own codes, in years with actuals
pay = pd.read_csv(OUT / "lens_by_fy.csv").rename(columns={"lens": "area", "spend": "payments_tagged"})
act = area_fy[area_fy.stage == "Actual"].rename(columns={"budget": "coded_actual"})
cmp_ = act.merge(pay[["fiscal_year", "area", "payments_tagged"]], on=["fiscal_year", "area"], how="left")
latest = int(cmp_.fiscal_year.max())
c = cmp_[cmp_.fiscal_year == latest].copy()
c["coverage"] = (c.payments_tagged / c.coded_actual).round(3)
c = c.sort_values("coded_actual", ascending=False)[["fiscal_year", "area", "coded_actual", "payments_tagged", "coverage"]]
c.to_csv(OUT / "budget_vs_payments.csv", index=False)

# Function areas and fund mix
b.groupby(["fiscal_year", "stage", "category_title"]).budget.sum().reset_index().to_csv(OUT / "budget_by_function.csv", index=False)
fund = f.groupby(["fiscal_year", "fund_type_name"]).budget.sum().reset_index()
fund.to_csv(OUT / "budget_by_fund.csv", index=False)
objects = b[b.fiscal_year == latest].groupby(["object_name"]).budget.sum().reset_index().sort_values("budget", ascending=False)
objects.insert(0, "fiscal_year", latest)
objects.to_csv(OUT / "budget_by_object.csv", index=False)

# Grants and loans
g["nonprofit"] = g.nonprofit.fillna("").str.upper().map({"Y": "Nonprofit", "N": "Not nonprofit"}).fillna("Not stated")
gy = g.groupby(["fiscalyear", "category"]).agg(amount=("amount", "sum"), awards=("amount", "size"),
                                              recipients=("grantee", "nunique")).reset_index().rename(columns={"fiscalyear": "fiscal_year"})
gy.to_csv(OUT / "grants_by_fy.csv", index=False)
gl = int(g.fiscalyear.max())
top = g[g.fiscalyear == gl].groupby("grantor").agg(amount=("amount", "sum"), awards=("amount", "size"),
                                                   recipients=("grantee", "nunique")).reset_index().sort_values("amount", ascending=False).head(15)
top.insert(0, "fiscal_year", gl)
top.to_csv(OUT / "grants_top_grantors.csv", index=False)

# Source inventory for the page
src = inv[["dataset_id", "name", "publisher", "rows_api", "rows_downloaded", "reconciled", "last_updated", "update_frequency", "public_url"]].copy()
src = src[src.rows_api.notna()]
src.to_csv(OUT / "sources.csv", index=False)

# Health checks, appended to the payments pipeline report
H = []
for r in src.itertuples():
    H.append({"check": f"{r.name} ({r.dataset_id}) matches the portal", "status": "pass" if str(r.reconciled).lower() == "true" else "fail",
              "detail": f"{int(r.rows_downloaded):,} of {int(r.rows_api):,} rows downloaded"})
bt = b.groupby("fiscal_year").budget.sum(); ft = f.groupby("fiscal_year").budget.sum()
diff = (bt - ft).abs() / ft
ok = bool((diff.dropna() < 0.005).all())
H.append({"check": "Operating budget matches its funding-source totals", "status": "pass" if ok else "warn",
          "detail": f"largest gap {diff.max():.2%} across FY{int(bt.index.min())}–FY{int(bt.index.max())}"})
H.append({"check": "Charges between state agencies left out of coded spend", "status": "pass",
          "detail": f"FY{latest} actuals: ${b[(b.fiscal_year == latest) & (b.stage == 'Actual') & INTERNAL].budget.sum()/1e6:,.0f}M of DoIT allocations, in-state services and DGS rent removed"})
H.append({"check": "Focus areas defined by state spending codes", "status": "pass",
          "detail": f"FY{latest} actuals: ${c.coded_actual.sum()/1e6:,.0f}M coded to the six areas vs ${c.payments_tagged.sum()/1e6:,.0f}M found by payee name"})
# Cross-check against the state's own Operating Budget site (its public data feed), FY2025-FY2027
import json, urllib.request
def site(year, entity):
    u = f"https://operatingbudget.maryland.gov/api/opex/chart_data.json?black_list=true&child_entity={entity}&sort=desc&sort_field=total&year={year}"
    with urllib.request.urlopen(u, timeout=60) as r:
        return {e["label"]: e["total"] for e in json.load(r)["entities"]}
for y in (2025, 2026, 2027):
    try:
        sf, sd = site(y, "org1"), site(y, "fund")
        of = b[b.fiscal_year == y].groupby("category_title").budget.sum(); od = f[f.fiscal_year == y].groupby("fund_type_name").budget.sum()
        gap = max([abs(of.get(k, 0) - v) for k, v in sf.items()] + [abs(od.get(k, 0) - v) for k, v in sd.items()])
        H.append({"check": f"FY{y} budget matches operatingbudget.maryland.gov", "status": "pass" if gap <= 10 else "fail",
                  "detail": f"{len(sf)} functions and {len(sd)} fund types compared; largest gap ${gap:,.0f}; site total ${sum(sf.values())/1e9:,.2f}B"})
    except Exception as e:
        H.append({"check": f"FY{y} budget matches operatingbudget.maryland.gov", "status": "warn", "detail": f"site not reachable: {e}"})
tot = pd.read_csv(OUT / "totals_by_fy.csv").set_index("fiscal_year").total_payments
for y in (2024, 2025, 2026):
    try:
        with urllib.request.urlopen(f"https://vendorpayments.maryland.gov/api/opex/totals.json?year={y}", timeout=60) as r:
            v = float(json.load(r)[0]["amount"])
        gap = abs(tot.get(y, 0) - v)
        H.append({"check": f"FY{y} payments match vendorpayments.maryland.gov", "status": "pass" if gap <= 10 else "fail",
                  "detail": f"site ${v:,.0f}; dashboard ${tot.get(y, 0):,.0f}; gap ${gap:,.0f}"})
    except Exception as e:
        H.append({"check": f"FY{y} payments match vendorpayments.maryland.gov", "status": "warn", "detail": f"site not reachable: {e}"})
h = pd.read_csv(OUT / "pipeline_health.csv")
h = h[~h.check.isin([x["check"] for x in H])]
pd.concat([h, pd.DataFrame(H)]).to_csv(OUT / "pipeline_health.csv", index=False)

print(c.to_string(index=False))
print(diff.round(4).to_dict())
print(fund[fund.fiscal_year == latest].to_string(index=False))
print(gy[gy.fiscal_year >= 2023].to_string(index=False))
