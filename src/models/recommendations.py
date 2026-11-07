"""The Overview's six recommendations as tracked tables (port of the plan, status and vendor-detail parts of
legacy/gst/scripts/recs.py).

  1. Bid statewide contracts for shared vendors      mart.d_bid_list (opportunities.py); detail below
  2. Confirm which reported savings recur            mart.d_savings_status (savings.py)
  3. Name the seven renegotiated contracts           the four named contract types, checked in d_savings_status
  4. Plan the rest of the path to $50M               mart.d_plan50: GMI's pace, then statewide contracts, then fallback areas
  5. Keep one vendor and agency master list          share of payments matched to an agency
  6. Tie spending to results                         Managing for Results measures read from the agency plans

Builds four dashboard files:
  d_plan50        the path to $50M a year, step by step, with a running total
  d_rec_status    one row per recommendation: a status, one key number, and the previous run's number
  f_vendor_detail payments by agency and year for every vendor an area page or the bid list links to
  d_vendor_names  the payee names merged into each of those vendors (FY2026 payments)

The plan is built from assumed rates, not evidence of what a renegotiation yields (config/assumptions.yaml,
`recommendations`). Differences from the legacy script: recommendation 6 is read from this pipeline's own
Managing for Results data instead of the legacy text "needs a data feed", which this pipeline made false; the history
behind `previous` is written only by builds that passed their checks.
"""
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
HISTORY = "rec_history.csv"
STATUS_COLUMNS = ["rec", "title", "status", "progress", "tab"]


def assumptions():
    return yaml.safe_load((ROOT / "config" / "assumptions.yaml").read_text())["recommendations"]


def vendor_detail(p, vendors, cfg=None):
    """Drill-down for each listed vendor: payments by agency and year, and the payee names merged into it.
    p: fiscal_year, agency_code, vendor, vendor_name, amount."""
    vd = (cfg or assumptions())["vendor_detail"]
    up = {v.upper() for v in vendors}
    q = p[(p.fiscal_year >= vd["first_fy"]) & p.vendor.str.upper().isin(up)].copy()
    q["vendor"] = q.vendor.str.title()
    f = q.groupby(["vendor", "agency_code", "fiscal_year"]).amount.sum().round(2).reset_index().rename(columns={"amount": "paid"})
    n = (q[q.fiscal_year == vd["names_fy"]].groupby(["vendor", "vendor_name"]).amount.sum().round(2).reset_index()
         .rename(columns={"vendor_name": "payee_name", "amount": "fy2026"}))
    return f, n


def plan50(model, forecast, bids, cfg=None):
    """GMI's current pace, then the next actions, added up until they reach the target a year."""
    cfg = cfg or assumptions()
    pl, target = cfg["plan"], cfg["target_saving"]
    f27 = forecast[forecast.fiscal_year == pl["forecast_fy"]].set_index("area").p50
    pace = float((model.set_index("area").gmi_rate.fillna(0) * f27.reindex(model.area).values).sum())
    rows = [{"step": 1, "action": "Keep GMI's current savings going", "basis": f"forecast FY{pl['forecast_fy']} spending × the rate GMI reported for each area",
             "saving": pace, "tab": "calc"}]
    for _, b in bids.iterrows():
        if sum(r["saving"] for r in rows) >= target:
            break
        rows.append({"step": len(rows) + 1, "action": f"Statewide contract: {b.vendor}",
                     "basis": f"assumed {pl['contract_rate'] * 100:.1f}% of ${b.fy2026 / 1e6:,.1f}M paid by {int(b.agencies)} agencies (assumed range 2-5%)",
                     "saving": pl["contract_rate"] * b.fy2026, "tab": "opp"})
    if sum(r["saving"] for r in rows) < target:
        for area in pl["fallback_areas"]:
            rows.append({"step": len(rows) + 1, "action": f"Start savings in {area.lower()} at {pl['fallback_rate'] * 100:.0f}%",
                         "basis": f"assumed {pl['fallback_rate'] * 100:.0f}% of forecast FY{pl['forecast_fy']} spending of ${f27.get(area, 0) / 1e6:,.1f}M",
                         "saving": pl["fallback_rate"] * f27.get(area, 0), "tab": "calc"})
    d = pd.DataFrame(rows)
    d["cumulative"] = d.saving.cumsum()
    return d


def results_row(mfr):
    """Recommendation 6 from the Managing for Results data this pipeline reads: (status, progress). mfr = (measures, plans with
    measures, plans, plans matched to a budget agency) or None when the plans were not available in this run."""
    if not mfr or not mfr[2]:
        return "Needs a data feed", "Managing for Results plans were not available in this run"
    measures, with_measures, plans, matched = mfr
    return "Data in place", f"{measures:,} performance measures read from {with_measures} of {plans} agency plans; {matched} plans matched to a budget agency"


def status(bids, chk, plan, matched, mfr=None, cfg=None):
    """One row per recommendation. matched: share of the matched year's payments with a budget agency."""
    cfg = cfg or assumptions()
    seen = int((chk.status == "Seen").sum())
    tot = int(chk.status.isin(["Seen", "Partly seen", "Not seen yet"]).sum())
    cats = chk[chk.check_id.isin(["S02", "S03", "S04", "S05"])]
    fell = int((cats.status == "Payments fell").sum())
    reach = plan.cumulative.iloc[-1] >= cfg["target_saving"]
    st6, pr6 = results_row(mfr)
    return pd.DataFrame([
        (1, "Bid statewide contracts for shared vendors", "Ready", f"{len(bids)} vendors ranked; ${bids.low.sum() / 1e6:,.1f}M–${bids.high.sum() / 1e6:,.1f}M a year", "opp"),
        (2, "Confirm which reported savings recur", "Tracking", f"{seen} of {tot} checks seen in payments; {int(chk.changed.sum())} changed since last run", "track"),
        (3, "Name the seven renegotiated contracts", "Categories tracked",
         f"4 contract types named in GMI's report are checked against payments; payments fell for {fell} of 4; vendors still unnamed", "track"),
        (4, "Plan the rest of the path to $50M", "Plan reaches $50M" if reach else "Gap remains",
         f"{len(plan)} steps to ${plan.cumulative.iloc[-1] / 1e6:,.1f}M a year", "calc"),
        (5, "Keep one vendor and agency master list", "In place", f"{matched:.1%} of FY{cfg['matched_fy']} payments matched to an agency", "data"),
        (6, "Tie spending to results", st6, pr6, "data"),
    ], columns=STATUS_COLUMNS)


def with_previous(current, history, run_id):
    """Add `previous`: each recommendation's progress text in the last earlier run."""
    prev = history[history.run_id != run_id].groupby("rec").tail(1).set_index("rec") if len(history) else pd.DataFrame()
    out = current.copy()
    out["previous"] = out.rec.map(prev.progress) if len(prev) else None
    return out


def read_history(data):
    path = Path(data) / HISTORY
    return pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["run_id", *STATUS_COLUMNS])


def record(con, run_id, data):
    """Append this run's rows to the history file (only for a build that passed its checks); a rerun replaces its own rows."""
    cur = con.execute("SELECT rec, title, status, progress, tab FROM mart.d_rec_status").df()
    hist = read_history(data)
    hist = pd.concat([hist[hist.run_id != run_id], cur.assign(run_id=run_id)[["run_id", *STATUS_COLUMNS]]], ignore_index=True)
    Path(data).mkdir(parents=True, exist_ok=True)
    hist.to_csv(Path(data) / HISTORY, index=False)
    return len(cur)


def inputs(con):
    pay = con.execute("SELECT fiscal_year, agency_code, vendor, vendor_name, amount, is_government, passthrough FROM mart.payment_area").df()
    return pay


def write(con, run_id, data, cfg=None):
    """Build the four tables in the mart schema (they need the forecasts, the opportunity tables and the savings status)."""
    cfg = cfg or assumptions()
    from . import opportunities  # the bid-list basis: private vendors outside capital and the excluded agencies

    pay = inputs(con)
    excluded = opportunities.assumptions()["bid_list"]["excluded_agency_codes"]
    ops = pay[~pay.is_government.astype(bool) & ~pay.passthrough.astype(bool) & ~pay.agency_code.isin(excluded)]
    bids = con.execute("SELECT * FROM mart.d_bid_list").df()
    leverage = con.execute("SELECT spending_code FROM mart.d_opps WHERE detector = 'Leverage'").df().spending_code.tolist()
    f1, n1 = vendor_detail(ops, list(bids.vendor) + leverage, cfg)  # bid-list and leverage vendors: the bid list's own basis
    area_vendors = con.execute("SELECT DISTINCT vendor FROM mart.f_vendor").df().vendor
    rest = sorted(set(area_vendors) - {v.upper() for v in f1.vendor.str.upper()})
    f2, n2 = vendor_detail(pay, rest, cfg)  # every other vendor on an area page: all its payments
    plan = plan50(con.execute("SELECT * FROM mart.d_forecast_model").df(), con.execute("SELECT * FROM mart.f_forecast").df(), bids, cfg)
    chk = con.execute("SELECT * FROM mart.d_savings_status").df()
    share = con.execute("SELECT sum(amount) FILTER (WHERE agency_code IS NOT NULL) / sum(amount) FROM core.fact_payment_mapped WHERE fiscal_year = ?",
                        [cfg["matched_fy"]]).fetchall()[0][0]
    mfr = None
    have = {r[0] for r in con.execute("SELECT table_schema || '.' || table_name FROM information_schema.tables").fetchall()}
    if "core.mfr_measure" in have and "ref.map_mfr_agency" in have:
        docs, matched = con.execute("SELECT count(*), count(agency_code) FROM ref.map_mfr_agency").fetchall()[0]
        n, ag = con.execute("SELECT count(DISTINCT agency_file || measure), count(DISTINCT agency_file) FROM core.mfr_measure").fetchall()[0]
        mfr = (n, ag, docs, matched)
    rec = with_previous(status(bids, chk, plan, share, mfr, cfg), read_history(data), run_id)
    tables = {"f_vendor_detail": pd.concat([f1, f2], ignore_index=True), "d_vendor_names": pd.concat([n1, n2], ignore_index=True),
              "d_plan50": plan, "d_rec_status": rec}
    for name, df in tables.items():
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE mart.{name} AS SELECT * FROM _df")
        con.unregister("_df")
    return {k: len(v) for k, v in tables.items()}
