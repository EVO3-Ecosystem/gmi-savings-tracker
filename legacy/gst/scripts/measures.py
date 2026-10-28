"""Measures layer: year-over-year change for every published table.

One definition used everywhere, the same way a DAX measure is defined once in Power BI and reused
by every visual. Each measure adds, for a value column `v`:

    v_prior   value in the previous fiscal year for the same keys
    v_yoy     (v - v_prior) / v_prior   (blank when the prior year is missing or zero)
    stage_pair  "Actual vs Actual", "Working budget vs Actual", ... so a reader knows when a change
                compares a budget with spending rather than like with like

The same measures are written as DAX in deploy/powerbi/measures.dax for a Power BI build.
"""
import numpy as np
import pandas as pd

CATALOG = []  # rows for out/measures.csv


def yoy(df, keys, values, stage_col="stage", table=None, good="neutral"):
    """Add prior-year and year-over-year columns for `values`, grouped by `keys` (without fiscal_year)."""
    d = df.sort_values(keys + ["fiscal_year"]).copy()
    prev = d.copy()
    prev["fiscal_year"] = prev.fiscal_year + 1
    cols = keys + ["fiscal_year"] + values + ([stage_col] if stage_col in d else [])
    prev = prev[cols].rename(columns={**{v: f"{v}_prior" for v in values}, stage_col: "stage_prior"})
    d = d.merge(prev, on=keys + ["fiscal_year"], how="left")
    for v in values:
        p = d[f"{v}_prior"]
        d[f"{v}_yoy"] = np.where((p.notna()) & (p != 0), (d[v] - p) / p.abs(), np.nan)
        CATALOG.append({"table": table, "measure": f"{v}_yoy", "definition": f"Change in {v} from the previous fiscal year, as a share of the previous year",
                        "grouped_by": ", ".join(keys) or "fiscal year", "higher_is": good})
    if stage_col in d:
        d["stage_pair"] = np.where(d.stage_prior.isna(), None,
                                   np.where(d[stage_col] == d.stage_prior, d[stage_col] + " vs " + d.stage_prior.astype(str),
                                            d[stage_col].astype(str) + " vs " + d.stage_prior.astype(str)))
        d = d.drop(columns=["stage_prior"])
    return d


def catalog():
    return pd.DataFrame(CATALOG).drop_duplicates(["table", "measure"])
