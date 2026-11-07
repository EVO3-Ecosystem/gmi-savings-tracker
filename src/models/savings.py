"""GMI's reported savings and the public-payments check for each item (port of legacy/gst/scripts/savings.py and the
recurrence status in legacy/gst/scripts/recs.py).

The reported figures come from reference/gmi_reported_savings.csv (Governor's Government Modernization Initiative Joint
Chairmen's Report, January 26, 2026; every item carries its page and verbatim quote). Each item is paired, where
possible, with the payments to vendors that would show the saving: payee names that sell the thing being cut (wireless
carriers for phone plans, dealers for vehicle purchases, and so on). The check compares FY2025 with FY2026 payments.
It shows direction and size, not proof: payee names miss some spending and contracts change for other reasons.

Builds four dashboard files:
  d_savings         the 18 reported items and how each is checked
  f_savings_check   matching payments by check, fiscal year and agency
  d_savings_status  per check: reported saving, payments before and after, a status, and the previous run's status
  d_vendor_moves    the largest vendor decreases FY2025 to FY2026: candidates for the unnamed renegotiated contracts

Thresholds and years live in config/assumptions.yaml (`savings`).
"""
import re
import warnings
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
HISTORY = "savings_status_history.csv"


def assumptions():
    return yaml.safe_load((ROOT / "config" / "assumptions.yaml").read_text())["savings"]


def items(reference=None):
    """The reported items, in the reference file's order."""
    ref = reference if reference is not None else pd.read_csv(ROOT / "reference" / "gmi_reported_savings.csv", keep_default_na=False)
    out = []
    for r in ref.to_dict("records"):
        out.append({"id": r["saving_id"], "ws": r["workstream"], "item": r["item"], "lo": None if r["reported_low"] == "" else float(r["reported_low"]),
                    "hi": None if r["reported_high"] == "" else float(r["reported_high"]), "type": r["type"], "status": r["status"], "count": r["count"],
                    "check": r["payment_check"] or None, "note": r["note"], "src": r["source"], "url": r["source_url"], "page": r["source_page"],
                    "quote": r["source_quote"]})
    return out


def _match(p, spec):
    if spec.startswith("lens:"):
        return (p.area == spec[5:]) & ~p.passthrough.astype(bool)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")  # the payee patterns use groups on purpose
        if spec.startswith("agency:"):
            codes, pat = spec[7:].split("|", 1)
            return p.agency_code.isin(codes.split(",")) & p.payee.str.contains(pat, flags=re.I, regex=True)
        return p.payee.str.contains(spec, flags=re.I, regex=True)


def check_payments(payments, its=None, cfg=None):
    """payments: fiscal_year, agency_code, vendor_name, amount, is_government, passthrough, area. Returns (d_savings, f_savings_check)."""
    cfg, its = cfg or assumptions(), its or items()
    after = cfg["after_fy"]
    p = payments[(payments.fiscal_year >= cfg["first_fy"]) & (~payments.is_government.astype(bool))].copy()
    p["payee"] = p.vendor_name.astype(str).str.upper()  # match on the payee name as paid
    masks = {it["id"]: _match(p, it["check"]) for it in its if it["check"] and not it["check"].startswith(("same:", "union:"))}
    for it in its:
        if it["check"] and it["check"].startswith("union:"):
            m = pd.Series(False, index=p.index)
            for k in it["check"][6:].split(","):
                m |= masks[k]
            masks[it["id"]] = m
    rows, facts = [], []
    for it in its:
        sid, chk, why = it["id"], it["check"], it["note"]
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
            top = m[m.fiscal_year == after].groupby("payee").amount.sum().nlargest(3)
            why = (why + " " if why else "") + "Payees: " + ", ".join(top.index.str.title())
        rows.append({"saving_id": sid, "workstream": it["ws"], "item": it["item"], "reported_low": it["lo"], "reported_high": it["hi"], "type": it["type"],
                     "status": it["status"], "count": it["count"], "check_id": check, "check_note": why.strip(), "source": it["src"],
                     "source_url": it["url"], "source_page": it["page"], "source_quote": it["quote"]})
    f = pd.concat(facts, ignore_index=True).rename(columns={"amount": "paid"})
    f["paid"] = f.paid.round(2)
    return pd.DataFrame(rows), f[["check_id", "fiscal_year", "agency_code", "paid"]]


def vendor_moves(payments, cfg=None):
    """The largest vendor decreases between the last two years shown, among vendors a statewide contract could cover."""
    cfg = cfg or assumptions()
    vm = cfg["vendor_moves"]
    y0, y1, y2 = vm["years"]
    p = payments[(payments.fiscal_year >= cfg["first_fy"]) & (~payments.is_government.astype(bool))]
    q = p[~p.passthrough.astype(bool) & p.fiscal_year.isin(vm["years"]) & ~p.agency_code.isin(vm["excluded_agency_codes"])]
    v = q.pivot_table(index="vendor", columns="fiscal_year", values="amount", aggfunc="sum", fill_value=0)
    v = v.reindex(columns=list(vm["years"]), fill_value=0)  # a year with no payments is zero, not a missing column
    agencies = q[q.fiscal_year == y1].groupby("vendor").agency_code.nunique()
    v = v[(agencies.reindex(v.index).fillna(0) >= vm["min_agencies"]) & ~v.index.str.upper().str.contains(vm["not_procurement"], regex=True)]
    v = v[(v[y1] >= vm["min_before"]) & (v[y2] > 0)].assign(change=lambda x: x[y2] - x[y1])
    v = v[v.change < 0].sort_values("change").head(vm["top"])  # decreases only: with few of them the legacy script listed increases too
    return pd.DataFrame({"vendor": v.index.str.title(), "fy2024": v[y0].round(2).values, "fy2025": v[y1].round(2).values, "fy2026": v[y2].round(2).values,
                         "change": v.change.round(2).values, "agencies": agencies.reindex(v.index).fillna(0).astype(int).values})


def status(d_sav, f_chk, run_id, history=None, cfg=None):
    """The status of every payment check this run, with the previous run's status (from `history`, a frame of past runs).

    With a reported saving: Seen when payments fell by at least half of it, Partly seen when they fell by less, Not seen
    yet when they did not fall. Without one: Payments fell / Payments did not fall."""
    cfg = cfg or assumptions()
    before, after = cfg["before_fy"], cfg["after_fy"]
    paid = f_chk.groupby(["check_id", "fiscal_year"]).paid.sum().unstack(fill_value=0)
    rep = d_sav.dropna(subset=["reported_low"]).assign(mid=lambda x: (x.reported_low + x.reported_high) / 2).groupby("check_id").mid.sum()
    rows = []
    for cid, r in paid.iterrows():
        b, a = r.get(before, 0), r.get(after, 0)
        rp = rep.get(cid)
        drop = b - a
        st = (("Payments fell" if drop > 0 else "Payments did not fall") if not rp else
              ("Seen" if drop >= cfg["seen_share"] * rp else "Partly seen" if drop > 0 else "Not seen yet"))
        rows.append({"check_id": cid, "item": d_sav[d_sav.saving_id == cid].item.iloc[0], "reported": rp, "before": b, "after": a, "status": st})
    cur = pd.DataFrame(rows)
    hist = history if history is not None else pd.DataFrame(columns=["run_id", "check_id", "status", "after"])
    prev = hist[hist.run_id != run_id].sort_values("run_id").groupby("check_id").tail(1).set_index("check_id")
    cur["previous_status"] = cur.check_id.map(prev.status) if len(prev) else None
    cur["changed"] = cur.previous_status.notna() & (cur.previous_status != cur.status)
    return cur


def read_history(data):
    path = Path(data) / HISTORY
    return pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["run_id", "check_id", "status", "after"])


def record(con, run_id, data):
    """Append this run's statuses to the history file (call only for a build that passed its checks); one row per run and check."""
    cur = con.execute("SELECT check_id, status, after FROM mart.d_savings_status").df()
    hist = read_history(data)
    hist = pd.concat([hist[hist.run_id != run_id], cur.assign(run_id=run_id)[["run_id", "check_id", "status", "after"]]], ignore_index=True)
    Path(data).mkdir(parents=True, exist_ok=True)
    hist.to_csv(Path(data) / HISTORY, index=False)
    return len(cur)


def write(con, run_id, data, cfg=None):
    """Build the four tables in the mart schema (reads the history file; writing it is `record`)."""
    payments = con.execute("SELECT fiscal_year, agency_code, vendor, vendor_name, area, amount, is_government, passthrough FROM mart.payment_area").df()
    cfg = cfg or assumptions()
    d, f = check_payments(payments, cfg=cfg)
    tables = {"d_savings": d, "f_savings_check": f, "d_vendor_moves": vendor_moves(payments, cfg), "d_savings_status": status(d, f, run_id, read_history(data), cfg)}
    for name, df in tables.items():
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE mart.{name} AS SELECT * FROM _df")
        con.unregister("_df")
    return {k: len(v) for k, v in tables.items()}
