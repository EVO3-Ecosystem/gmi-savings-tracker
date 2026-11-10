"""Numbers in the model notes, from the data: writes generated sections between <!-- facts:NAME --> markers.

    python -m src.models.doc_facts            # run by `make docs` (src/pipeline/governance.py calls main())

docs/models/opportunities.md   facts:opportunities   findings and saving by detector (mart.d_opps) and the bid list
docs/models/payment_screen.md  facts:payment_screen  leads by rule, confidence and review status; source issues; backtest
docs/reviews/payment_screen_review_sheet.csv          one row per lead with her_decision / notes kept across runs

Text outside the markers is written by hand; inside, it is replaced on every run, so a count in the notes cannot go stale.
"""
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "md_transparency.duckdb"
OPPS = ROOT / "docs" / "models" / "opportunities.md"
SCREEN = ROOT / "docs" / "models" / "payment_screen.md"
SHEET = ROOT / "docs" / "reviews" / "payment_screen_review_sheet.csv"
SHEET_COLS = ["group_id", "rule", "fiscal_year", "agency", "agency_raw", "vendor", "n", "amount", "review_amount", "confidence",
              "review_status", "review_note", "her_decision", "notes"]
DECISIONS = "her_decision: duplicate_payment / not_duplicate / source_publishing_issue / records_requested / cannot_tell"


def money(v):
    v = float(v or 0)
    return f"${v / 1e6:,.2f}M" if abs(v) >= 1e6 else f"${v:,.0f}"


def put(text, name, body):
    pat = re.compile(rf"(<!-- facts:{name} -->)(.*?)(<!-- /facts:{name} -->)", re.S)
    if not pat.search(text):
        raise SystemExit(f"marker facts:{name} missing")
    return pat.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", text)


def run_id(con):
    return con.execute("SELECT max(run_id) FROM ops.run_log").fetchone()[0]


def opportunities(con):
    d = con.execute("""SELECT detector, count(*) AS n, sum(likely) AS likely, sum(low) AS low, sum(high) AS high
                       FROM mart.d_opps GROUP BY 1 ORDER BY n DESC""").df()
    rows = [f"| {r.detector} | {r.n:,} | {money(r.likely)} | {money(r.low)}-{money(r.high)} |" for r in d.itertuples()]
    rows.append(f"| **All** | **{d.n.sum():,}** | **{money(d.likely.sum())}** | **{money(d.low.sum())}-{money(d.high.sum())}** |")
    b = con.execute("SELECT count(*), sum(low), sum(high) FROM mart.d_bid_list").fetchone()
    return (f"_Generated from `mart.d_opps` and `mart.d_bid_list`, extract run {run_id(con)}, by `python -m src.models.doc_facts`._\n\n"
            "| Detector | Findings | Likely saving | Range |\n|---|---|---|---|\n" + "\n".join(rows)
            + f"\n\nBid list: {b[0]:,} vendors, {money(b[1])}-{money(b[2])}.")


def payment_screen(con):
    by = con.execute("""SELECT rule, confidence, review_status, count(*) AS groups, sum(n) AS records, sum(review_amount) AS review
                        FROM mart.d_payment_screen GROUP BY ALL ORDER BY rule, confidence, review_status""").df()
    tot = con.execute("SELECT count(*), coalesce(sum(n), 0), coalesce(sum(total_amount), 0), coalesce(sum(review_amount), 0) FROM mart.d_payment_screen").fetchone()
    src = con.execute("""SELECT issue_id, agency, records, amount, identical_records, screen_groups, screen_review_amount, status
                         FROM mart.d_source_issues ORDER BY issue_id""").df()
    yrs = con.execute("""SELECT fiscal_year, sum(groups) AS g, sum(review_amount) AS r FROM mart.d_payment_screen_summary
                         WHERE status = 'Measured' GROUP BY 1 ORDER BY 1""").df()
    rate = con.execute("SELECT any_value(measured_confirmation_rate), any_value(rate_basis), any_value(reviewed_leads), any_value(confirmed_leads), "
                       "any_value(lever_rate_low), any_value(lever_rate_likely), any_value(lever_rate_high) FROM mart.d_payment_screen_summary").fetchone()
    out = [f"_Generated from `mart.d_payment_screen`, `mart.d_source_issues` and `mart.d_payment_screen_summary`, extract run {run_id(con)}, "
           "by `python -m src.models.doc_facts`._", "",
           f"**Payment leads: {tot[0]:,} groups, {int(tot[1]):,} records, {money(tot[2])} in groups, {money(tot[3])} review dollars.**", "",
           "| Rule | Confidence | Review status | Groups | Records | Review dollars |", "|---|---|---|---|---|---|"]
    out += [f"| {r.rule} | {r.confidence} | {r.review_status} | {r.groups:,} | {int(r.records):,} | {money(r.review)} |" for r in by.itertuples()]
    out += ["", f"**Source issues (not leads): {len(src)}**, {int(src.screen_groups.sum()) if len(src) else 0:,} screen groups moved out of the leads "
            f"({money(src.screen_review_amount.sum() if len(src) else 0)} review dollars they carried).", "",
            "| Issue | Agency | Second-block records | Second-block dollars | Identical to first block | Screen groups | Status |", "|---|---|---|---|---|---|---|"]
    out += [f"| {r.issue_id} | {r.agency} | {r.records:,} | {money(r.amount)} | {int(r.identical_records):,} | {r.screen_groups:,} | {r.status} |" for r in src.itertuples()]
    out += ["", "**Backtest, by year** (lead groups / review dollars): " + "; ".join(f"FY{r.fiscal_year} {int(r.g)} / {money(r.r)}" for r in yrs.itertuples()) + ".",
            "", f"**Measured confirmation rate:** {'not measured' if rate[0] is None else f'{rate[0]:.1%}'} ({rate[1]}; {rate[2]} leads reviewed, "
            f"{rate[3]} confirmed). Lever rates low / likely / high: {rate[4]:.1%} / {rate[5]:.1%} / {rate[6]:.1%}."]
    return "\n".join(out)


def review_sheet(con, path=SHEET):
    """One row per lead for a person's decision; her_decision and notes already filled in are kept (by group_id)."""
    d = con.execute(f"SELECT {', '.join(c for c in SHEET_COLS if c not in ('her_decision', 'notes'))} FROM mart.d_payment_screen "
                    "ORDER BY review_amount DESC, group_id").df()
    old = pd.read_csv(path, dtype=str).fillna("") if path.exists() else pd.DataFrame(columns=["group_id", "her_decision", "notes"])
    d = d.merge(old[["group_id", "her_decision", "notes"]], on="group_id", how="left").fillna({"her_decision": "", "notes": ""})
    path.parent.mkdir(parents=True, exist_ok=True)
    d[SHEET_COLS].to_csv(path, index=False)
    return len(d)


README = ROOT / "README.md"


def readme_badges(con):
    """Badge line for the README: check results and the data's as-of date, from the last build."""
    rid = run_id(con)
    r = con.execute("select count(*), count(*) filter (where result = 'pass'), count(*) filter (where result = 'fail') "
                    "from ops.check_result where run_id = ?", [rid]).fetchone()
    asof = f"{rid[:4]}--{rid[4:6]}--{rid[6:8]}"
    color = "2da44e" if r[2] == 0 else "cf222e"
    return (f"![Data checks](https://img.shields.io/badge/data%20checks-{r[1]}%20of%20{r[0]}%20pass%2C%20{r[2]}%20fail-{color}) "
            f"![Data as of](https://img.shields.io/badge/data%20as%20of-{asof}-0969da)")


def mm(v):
    """Compact dollars for prose: $29M, $50.2M, $1.86M."""
    v = float(v or 0)
    if abs(v) >= 1e9:
        return f"${v / 1e9:,.1f}B"
    if abs(v) >= 1e7:
        return f"${v / 1e6:,.1f}M".replace(".0M", "M")
    return f"${v / 1e6:,.2f}M"


def readme_facts(con):
    """The README's "What it found" bullets, computed from the marts."""
    sv = con.execute("select * from mart.d_savings").df()
    gmi = sv[sv.source.str.contains("Government Modernization Initiative Final Report", na=False)]
    saved = gmi[gmi.status == "Saved in FY2026"]
    st = con.execute("select * from mart.d_savings_status").df()
    pl = con.execute("select * from mart.d_plan50").df()
    seen = set(st[st.status == "Seen"].check_id)
    rec = sv[sv.check_id.isin(seen) & sv.type.str.contains("Recurring|Year over year", na=False)]
    tot = pl.cumulative.max()
    ev = ((rec.reported_low.fillna(0) + rec.reported_high.fillna(0)) / 2).sum() / tot
    rate = pl.basis.str.extract(r"assumed ([\d.]+)%")[0].dropna()
    op = con.execute("select count(*), sum(high), sum(likely) from mart.d_opps").fetchone()
    ps = con.execute("select sum(groups), sum(review_amount) from mart.d_payment_screen_summary where rule = 'Possible duplicate'").fetchone()
    si = con.execute("select sum(amount), max(verified_on), string_agg(agency, ' and ' order by agency) from mart.d_source_issues").fetchone()
    other = len(sv) - len(gmi)
    return "\n".join([
        f"- **Reported savings:** GMI's January 26, 2026 report lists {len(gmi)} items" + ((" (plus a separate DGS facility estimate)" if other == 1 else f" (plus {other} separate DGS estimates)") if other else "")
        + f". The {len(saved)} it describes as saved in FY2026 add up to {mm(saved.reported_low.sum())}, its own FY2026 total; the rest are yearly savings under way or projected and are not added to it.",
        f"- **Payment evidence:** about {ev:.0%} of the path to {mm(tot)} has payment evidence; the path is conditional on reported savings recurring"
        + (f" and an assumed {rate.iloc[0]}% from statewide contracts" if len(rate) else "")
        + f" ({mm(pl.low.sum())}–{mm(pl.high.sum())} across the assumed ranges).",
        f"- **Opportunities:** {op[0]} findings worth up to {mm(op[1])} a year ({mm(op[2])} likely). They are leads to review; they overlap and are not additive.",
        f"- **Payment screen:** {int(ps[0])} possible duplicate payment groups ({mm(ps[1])} to review). None can be confirmed without payment records.",
        f"- **Source data issue:** the published FY2022 payments data lists a second block of {mm(si[0])} for {" and ".join(n.strip().title() for n in si[2].split(" and "))}, confirmed on both State sites on "
        f"{si[1]:%b} {si[1].day}, {si[1].year}. It is reported as a source issue, never as a lead.",
    ])


def main(argv=None, db=DB):
    con = duckdb.connect(str(db), read_only=True)
    try:
        OPPS.write_text(put(OPPS.read_text(), "opportunities", opportunities(con)))
        SCREEN.write_text(put(SCREEN.read_text(), "payment_screen", payment_screen(con)))
        n = review_sheet(con)
        if README.exists():
            README.write_text(put(put(README.read_text(), "readme", readme_facts(con)), "badges", readme_badges(con)))
    finally:
        con.close()
    print(f"doc_facts: opportunities and payment screen facts written; review sheet {n} leads ({DECISIONS})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
