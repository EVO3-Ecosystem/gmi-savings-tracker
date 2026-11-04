# Visualization portfolio rubric: Vendors tab

The standard the GMI Savings Tracker's views are held to, written for a data-science visualization portfolio. Each criterion is scored 1–5; a view scores 5 only when every criterion does. Evidence for each score is something a reviewer can check: a check, a test, a screenshot or a file.

| # | Criterion | What a 5 requires |
|---|---|---|
| 1 | Decision-first story | Each view answers a stated question; the headline is a finding, not a description; every chart ends in a verdict or an action; caveats are stated where a reader would over-read |
| 2 | Analytical rigor | Metrics are defined and cited (HHI and its 1,800 threshold); one counting basis, stated, with any other basis computed and reconciled; small-number caveats; change compares like with like |
| 3 | Visual encoding and design | The chart fits the question (ranked bars, small multiples on a shared scale with the threshold drawn); validated colorblind-safe palette; direct labels; clean names and number formats; no clipped or wrapped labels |
| 4 | Interactivity and drill-down | Global filters (year, agency, area) apply; local filters and search; clicking a chart filters the tab; every vendor opens its own page; sortable tables; tooltips |
| 5 | Accessibility and responsiveness | Keyboard reaches every control and chart filter; charts carry aria labels; color is never the only signal; no page overflow at 400 px, wide tables scroll inside their card with the name column pinned |
| 6 | Data integrity and provenance | Every number on screen comes from a dataset (no typed figures); each new table ties back to the payments data in a stop check; method and sources on the page and in the repo |
| 7 | Reproducibility | One SQL file per mart with grain and checks in its header; unit tests for the metric; every column documented; figures generated from the database; committed |

## Scores: Vendors tab, Nov 4, 2026

| Criterion | Round 1 | Round 2 | Round 3 | Evidence for the final score |
|---|---|---|---|---|
| 1 Story | 4 | 5 | 5 | Headline states the three savings levers; each card has a verdict sentence; findings list ends in four actions and a caveat |
| 2 Rigor | 4 | 5 | 5 | HHI defined and cited; both counting bases computed (`mart.d_multi_basis`: 42 vs 54, the Spend Lens's figure reproduced); small-n caveat for Telecom |
| 3 Visual | 3 | 4 | 5 | Names fixed (AT&T, MD, trailing "&"); small multiples drawn after layout on one scale with the 1,800 line; distinct change headers; short area labels; "IT" kept in sentences |
| 4 Interactivity | 4 | 5 | 5 | Bar and small-multiple clicks set the area filter (tested); global filters, search, ledger filters; 3,640 vendor pages |
| 5 Accessibility | 4 | 4 | 5 | Keyboard Enter on a small multiple filters (tested); 0 px page overflow at 400 px; tables scroll in their card with the vendor pinned |
| 6 Integrity | 4 | 5 | 5 | 7 Vendors-tab stop checks (55 of 55 pass); the "54" comes from data; Delmarva false positives removed from the Utility rule |
| 7 Reproducibility | 3 | 4 | 5 | `sql/mart/34-39`, `tests/test_concentration.py`, 944 of 944 columns documented, `docs/figures/vendor_concentration_hhi.png`, committed |
| **Overall** | **3** | **4** | **5** | |

Round 1 → 2 fixed: typed "54", misleading "several years" note, name casing, duplicate headers, missing tie-out checks and tests. Round 2 → 3 fixed: AT&T casing, the master-list example (Verizon, 7 names), Delmarva utility false positives, phone-width tables, "IT" casing, README figure.
