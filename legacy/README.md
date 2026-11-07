# Legacy baseline: the original pipeline's outputs and the live dashboard

Kept so the Phase 5 parity gate can compare the new pipeline's 44 exports with what the original pipeline published. Nothing here is rebuilt by `make`; `legacy/MANIFEST.csv` lists every file with its size, row count and SHA-256.

| Folder | What it is | When and where it came from |
|---|---|---|
| `gst/out/` | The original pandas pipeline's 41 published CSVs (the dashboard's data files until Nov 4, 2026, plus its run log and check list) | Last original-pipeline run `20261102T183034Z`, 93 of 93 checks passed (`gst/out/pipeline_runs.csv`); copied from that run's `out/` folder on Nov 7, 2026 |
| `gst/page/`, `gst/scripts/` | The dashboard page and the original scripts (already in the repo) | Kept in sync with the original pipeline |
| `artifact/index.html` | The page as live on the GMI Savings Tracker dashboard artifact (version 18, published Nov 4, 2026 with the Vendors tab) | Read from the artifact's `files/index.html` document on Nov 7, 2026 |
| `artifact/datasets/` | The 40 dataset records the live dashboard reads: title, description, source file link, update stamp | Read from the artifact's `datasets` collection on Nov 7, 2026 |

## Notes for the parity gate

- The live dashboard's data files were replaced on Nov 4, 2026 by the new pipeline's export (39 files) and are not downloadable from a cloud session; `artifact/datasets/*.json` records which file each dataset points to. The pre-Nov 4 published data is `gst/out/`.
- **30 of the 44 exports have a legacy file of the same name** in `gst/out/`; compare those file by file.
- **14 exports have no legacy counterpart** because they were added after the original pipeline: the Vendors tab (`d_vendors`, `f_vendor_pay`, `f_payee_type`, `f_vendor_year`, `d_multi`, `d_multi_basis`, `f_concentration`, `d_area_top`, `d_families`) and the portal views (`f_budget_vs_pay`, `f_fund_source`, `f_program`, `f_grants`, `f_overlap`). Check them against their marts' tests and the source totals instead.
- **11 legacy files are not dashboard exports**: the intermediate tables `agency_year`, `area_year`, `area_agency_year`, `area_code_year`, `area_vendor_year`, `budget_by_function`, `budget_by_fund`, `budget_by_object` and `spending_scope` (the 21-file base parity in `docs/parity/` already uses these), plus `reports` and `run_checks_failed`.
- `run_checks_failed.csv` is the original pipeline's record of its last failed run (`20261102T182752Z`), kept for the fault history.
- The original pipeline's `reports.csv` points to PDF reports stored in the artifact; the PDFs themselves are not copied.
