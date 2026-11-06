"""Figures for the README and docs: what the pipeline pulls, how it proves the numbers, and what the data shows.

    python -m src.pipeline.figures

Writes PNGs to docs/figures/ from the database, the reconciliation results and the run history (no hand-entered
numbers). Palette: the dataviz skill's validated categorical order (blue, orange, aqua, yellow, magenta); each panel is
labeled directly, so no figure relies on color alone.
"""
from pathlib import Path

import duckdb
import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIG = ROOT / "docs" / "figures"
DB = ROOT / "data" / "md_transparency.duckdb"
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
INK, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
NAMES = {"budget": "Operating budget (yu65-jmmv)", "fund": "Funding source (gy87-e27x)", "fte": "Positions (x8qy-486w)",
         "payments": "Payments (7syw-q4cy)", "grants": "Grants and loans (absk-avps)"}
YEAR = {"budget": "fiscal_year", "fund": "fiscal_year", "fte": "fiscal_year", "payments": "fiscal_year", "grants": "fiscalyear"}

plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": .8, "axes.axisbelow": True, "font.size": 10,
                     "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.spines.top": False, "axes.spines.right": False})


def money(v, _=None):
    if v == 0:
        return "$0"
    if abs(v) >= 1e10:
        return f"${v / 1e9:,.0f}B"
    return f"${v / 1e9:,.1f}B" if abs(v) >= 1e9 else f"${v / 1e6:,.0f}M"


def save(fig, name, title, note):
    fig.tight_layout(rect=(0, .05, 1, .9))
    fig.suptitle(title, x=.01, y=.99, ha="left", fontsize=13, fontweight="bold", color=INK)
    fig.text(.01, .005, note, ha="left", va="bottom", fontsize=8.5, color=MUTED)
    fig.savefig(FIG / name, dpi=150, bbox_inches="tight")
    plt.close(fig)


def rows_by_year(con):
    fig, axs = plt.subplots(1, 5, figsize=(15, 3.2), sharex=False)
    for ax, (k, col), c in zip(axs, NAMES.items(), C):
        d = con.execute(f"select try_cast({YEAR[k]} as int) y, count(*) n from raw.{k} group by 1 order by 1").df()
        ax.bar(d.y, d.n, color=c, width=.75)
        ax.set_title(f"{col}\n{int(d.n.sum()):,} rows", loc="left", fontsize=9.5)
        ax.yaxis.set_major_formatter(lambda v, _: (f"{v / 1e3:,.0f}K" if v >= 1e4 else f"{v / 1e3:,.1f}K") if v >= 1e3 else f"{v:.0f}")
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True, nbins=5))
    save(fig, "rows_by_year.png", "What the pipeline extracts: rows per fiscal year, five datasets",
         "Source: opendata.maryland.gov SODA API, latest extract. Payments start FY2008; the latest payments year is partial.")


def reconciliation():
    r = pd.read_csv(ROOT / "docs" / "reconciliation" / "by_year.csv")
    fig, axs = plt.subplots(1, 4, figsize=(15, 3.4))
    for ax, (k, g), c in zip(axs, r.groupby("dataset", sort=False), C):
        ax.plot(g.fiscal_year, g.total_api, color=c, lw=2, label="API extract")
        ax.scatter(g.fiscal_year, g.total_web, s=36, facecolor=SURF, edgecolor=INK, lw=1.2, zorder=3, label="Website download")
        if k == "payments":  # the latest year is partial: draw its segment dashed so the drop does not read as a collapse
            ax.plot(g.fiscal_year.iloc[-2:], g.total_api.iloc[-2:], color=SURF, lw=3, zorder=2)
            ax.plot(g.fiscal_year.iloc[-2:], g.total_api.iloc[-2:], color=c, lw=2, ls=(0, (3, 2)), zorder=2.5)
        ax.yaxis.set_major_formatter(money)
        bad = int((~g.match).sum())
        ax.set_title(NAMES[k] + "\n" + ("every year matches" if not bad else f"{bad} years differ"), loc="left", fontsize=9.5)
        if k == "payments":
            last = g.iloc[-1]
            ax.annotate(f"FY{int(last.fiscal_year)} partial", (last.fiscal_year, last.total_api), xytext=(-62, 4), textcoords="offset points", fontsize=8, color=MUTED)
    axs[0].legend(frameon=False, fontsize=8.5, loc="upper left")
    save(fig, "reconciliation.png", "Two copies, one answer: API extract vs the Transparency Portal's own downloads",
         "Line: yearly total from the SODA API. Rings: yearly total from mtp.maryland.gov downloads. A match means equal row counts and totals within $1. "
         "Positions (x8qy-486w) is not shown: the portal has no website download for it; it is checked against the portal's own count and yearly totals.")


def budget_by_stage(con):
    d = con.execute("select b.fiscal_year y, s.stage, sum(b.budget) v from core.fact_budget b join ref.dim_stage s using (fiscal_year) group by 1, 2 order by 1").df()
    fig, ax = plt.subplots(figsize=(10, 3.8))
    act = d.stage.str.lower().eq("actual")
    ax.bar(d.y[act], d.v[act], color=C[0], width=.7, label="Actual")
    ax.bar(d.y[~act], d.v[~act], color=SURF, edgecolor=C[0], hatch="///", lw=1.2, width=.7, label="Budget (working or appropriation)")
    for y, v in zip(d.y, d.v):
        ax.text(y, v, money(v), ha="center", va="bottom", fontsize=8, color=INK)
    ax.yaxis.set_major_formatter(money)
    ax.set_xticks(d.y)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    save(fig, "budget_by_stage.png", "Maryland operating budget, all funds, FY2017–FY2027 (nominal dollars)",
         "Stages from ref.budget_stage (operatingbudget.maryland.gov statement, checked against DBM budget books), not the file's out-of-date Type column.")


def vendor_concentration(con):
    d = con.execute("""select sum(p.amount) s from core.fact_payment p join ref.map_payee_vendor m on m.payee = p.vendor_name_as_paid
                       where p.fiscal_year = 2025 and not m.is_government group by m.vendor order by 1 desc""").df()
    cum = d.s.cumsum() / d.s.sum()
    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.plot(range(1, len(cum) + 1), cum, color=C[0], lw=2)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
    for n in (200, 1000, 3000):
        if n <= len(cum):
            ax.scatter([n], [cum.iloc[n - 1]], s=40, color=C[0], edgecolor=SURF, lw=2, zorder=3)
            ax.annotate(f"top {n:,}: {cum.iloc[n - 1]:.0%}", (n, cum.iloc[n - 1]), xytext=(8, -14), textcoords="offset points", fontsize=9, color=INK)
    ax.set_ylim(0, 1.02)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_xlabel("Vendors ranked by FY2025 payments (log scale)")
    ax.set_ylabel("Share of payments")
    save(fig, "vendor_concentration.png", f"A few vendors hold most of the money: {len(d):,} non-government vendors, FY2025",
         "Payee names grouped into companies by reference/vendor_normalization.csv and vendor_families.csv; government payees excluded.")


def concentration(con):
    d = con.execute("SELECT fiscal_year, area, hhi FROM mart.f_concentration ORDER BY area, fiscal_year").df()
    areas = d.groupby("area").hhi.last().sort_values(ascending=False).index
    fig, axs = plt.subplots(1, len(areas), figsize=(15, 3.1), sharey=True)
    for ax, a in zip(axs, areas):
        g = d[d.area == a]
        last = g.iloc[-1]
        c = C[0] if last.hhi >= 1800 else MUTED
        ax.axhline(1800, color=MUTED, lw=1, ls=(0, (3, 3)))
        ax.plot(g.fiscal_year, g.hhi, color=c, lw=2)
        ax.scatter([last.fiscal_year], [last.hhi], s=30, color=c, zorder=3)
        ax.set_title(f"{a}\nHHI {last.hhi:,.0f} in FY{int(last.fiscal_year)}", loc="left", fontsize=9.5)
        ax.xaxis.set_major_locator(matplotlib.ticker.FixedLocator([2008, 2017, 2026]))
        ax.xaxis.set_major_formatter(lambda v, _: f"FY{int(v) % 100:02d}")
    axs[0].set_ylabel("HHI")
    axs[0].yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
    axs[0].text(2008.3, 2000, "1,800: highly concentrated", fontsize=8, color=MUTED, va="bottom")
    save(fig, "vendor_concentration_hhi.png", "Buying in four of six focus areas is highly concentrated",
         "Herfindahl-Hirschman Index of private-vendor spend per focus area, FY2008-FY2026 (mart.f_concentration). Threshold from the 2023 U.S. DOJ/FTC Merger Guidelines.")


def check_history():
    h = pd.read_csv(ROOT / "data" / "check_history.csv")
    if h.run_id.nunique() < 3:  # one or two builds make a poor chart; the table in docs/checks.md covers it
        return
    g = h.groupby(["run_id", "result"]).size().unstack(fill_value=0).reindex(columns=["pass", "warn", "fail"], fill_value=0).tail(12)
    fig, ax = plt.subplots(figsize=(10, 3.4))
    x = range(len(g))
    ax.bar(x, g["pass"], color=C[2], width=.7, label="pass")
    ax.bar(x, g["warn"], bottom=g["pass"], color=C[3], width=.7, label="warn")
    ax.bar(x, g["fail"], bottom=g["pass"] + g["warn"], color="#e34948", width=.7, label="fail")
    ax.set_xticks(list(x), [f"{r[4:6]}/{r[6:8]} {r[9:11]}:{r[11:13]}" for r in g.index], rotation=35, ha="right", fontsize=8)
    ax.legend(frameon=False, fontsize=9, ncol=3, loc="upper left")
    ax.set_ylabel("Checks")
    save(fig, "check_history.png", "Every build is checked: results of the last builds",
         "From data/check_history.csv. A failed stop check keeps the last good database and blocks publishing.")


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    rows_by_year(con)
    budget_by_stage(con)
    vendor_concentration(con)
    concentration(con)
    con.close()
    if (ROOT / "docs" / "reconciliation" / "by_year.csv").exists():
        reconciliation()
    if (ROOT / "data" / "check_history.csv").exists():
        check_history()
    print("figures:", ", ".join(sorted(p.name for p in FIG.glob("*.png"))))


if __name__ == "__main__":
    main()
