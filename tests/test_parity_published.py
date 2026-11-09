"""The published-file parity gate's comparison rules, on constructed files (no data needed)."""
import pandas as pd

from src.pipeline import parity_published as pp


def _cmp(legacy, export, keys):
    return pp.compare("t", pd.DataFrame(legacy), pd.DataFrame(export), keys)


def test_identical_files_in_another_column_and_row_order_are_equivalent():
    a = {"fiscal_year": [2025, 2026], "agency_code": ["D50", "M00"], "spend": [1.5, 2.25], "name": ["x", "y"]}
    b = {"name": ["y", "x"], "spend": [2.25, 1.5], "agency_code": ["M00", "D50"], "fiscal_year": [2026, 2025]}
    s, aspects, d = _cmp(a, b, ["fiscal_year", "agency_code"])
    assert aspects == set() and s["matched_keys"] == 2 and s["cells_differing"] == 0 and d.empty
    assert pp.classify(aspects, None) == ("equivalent", [])


def test_money_within_a_cent_ratios_within_1e5_and_counts_exactly():
    a = {"k": ["a", "b"], "spend": [100.00, 100.00], "spend_yoy": [0.123450, 0.5], "vendors": [10, 10]}
    b = {"k": ["a", "b"], "spend": [100.01, 100.02], "spend_yoy": [0.123459, 0.50002], "vendors": [10, 11]}
    s, aspects, d = _cmp(a, b, ["k"])
    assert aspects == {"cells:spend", "cells:spend_yoy", "cells:vendors"}
    assert s["columns_differing"] == "spend (1); spend_yoy (1); vendors (1)"
    assert abs(s["max_abs_diff"] - 1.0) < 1e-9 and s["max_abs_diff_column"] == "vendors"
    assert set(d[d.aspect == "cells:spend"].key) == {"B"}


def test_keys_are_normalised_and_empty_key_parts_still_match():
    a = {"agency_code": ["d50", None], "area": [None, "Fleet"], "spend": [1.0, 2.0]}
    b = {"agency_code": [" D50 ", ""], "area": ["", "fleet"], "spend": [1.0, 2.0]}
    s, aspects, _ = _cmp(a, b, ["agency_code", "area"])
    assert aspects == set() and s["matched_keys"] == 2 and s["duplicate_keys"] == 0


def test_rows_and_columns_on_one_side_and_duplicate_keys_are_listed():
    a = {"k": ["a", "b", "b"], "old": [1, 2, 3], "v": [1.0, 2.0, 2.0]}
    b = {"k": ["a", "c"], "new": [5, 6], "v": [1.0, 3.0]}
    s, aspects, d = _cmp(a, b, ["k"])
    assert aspects == {"rows_only_legacy", "rows_only_export", "column_only_legacy:old", "column_only_export:new", "duplicate_keys"}
    assert (s["keys_only_legacy"], s["keys_only_export"], s["duplicate_keys"]) == (1, 1, 1)
    assert set(d.aspect) == {"rows_only_legacy", "rows_only_export"}


def test_text_compares_trimmed_and_numbers_written_as_text_compare_as_numbers():
    a = {"k": ["a", "b", "c"], "status": ["Seen ", None, "Fell"], "ok": ["True", "1", "2.50"]}
    b = {"k": ["a", "b", "c"], "status": ["Seen", "", "Rose"], "ok": [1, 1.0, 2.5]}
    s, aspects, d = _cmp(a, b, ["k"])
    assert aspects == {"cells:status"} and s["cells_differing"] == 1
    assert d.iloc[0].legacy == "Fell" and d.iloc[0].export == "Rose"


def test_an_explanation_covers_only_the_aspects_it_lists():
    aspects = {"rows_only_export", "cells:payments"}
    assert pp.classify(aspects, {"rows_only_export", "cells:payments"}) == ("difference explained", [])
    assert pp.classify(aspects, {"rows_only_export"}) == ("difference to explain", ["cells:payments"])
    assert pp.classify(aspects, None) == ("difference to explain", ["cells:payments", "rows_only_export"])


def test_run_lists_files_without_a_legacy_counterpart_and_fails_on_unexplained(tmp_path):
    exp, leg, out = tmp_path / "export", tmp_path / "legacy", tmp_path / "out"
    exp.mkdir(), leg.mkdir(), out.mkdir()
    pd.DataFrame({"agency_code": ["D50"], "agency": ["Military"]}).to_csv(exp / "d_agency.csv", index=False)
    pd.DataFrame({"agency_code": ["D50"], "agency": ["Military Department"]}).to_csv(leg / "d_agency.csv", index=False)
    for name in pp.NO_COUNTERPART:
        pd.DataFrame({"vendor": ["X"]}).to_csv(exp / f"{name}.csv", index=False)
    pd.DataFrame({"file": ["x"]}).to_csv(exp / "manifest.csv", index=False)
    summ, diff = pp.run(exp, leg, {})
    st = summ.set_index("file").status
    assert st["d_agency"] == "difference to explain" and st["d_vendors"] == "no legacy counterpart" and "manifest" not in st
    assert summ.set_index("file").covered_by["d_vendors"] == pp.NO_COUNTERPART["d_vendors"]
    assert len(diff) == 1
    assert pp.main(["--export", str(exp), "--legacy", str(leg), "--out", str(out)]) == 1
    pd.DataFrame({"file": ["d_agency"], "covers": ["cells:agency"], "explanation": ["renamed"], "source": ["x"]}).to_csv(out / "published_explanations.csv", index=False)
    assert pp.main(["--export", str(exp), "--legacy", str(leg), "--out", str(out)]) == 0
    assert (out / "published_summary.csv").exists() and (out / "published_differences.csv").exists()
    (exp / "d_multi.csv").unlink()  # a newer export that goes missing fails the gate too
    assert pp.main(["--export", str(exp), "--legacy", str(leg), "--out", str(out)]) == 1


def test_every_published_file_has_a_key_or_a_coverage_note():
    assert not set(pp.KEYS) & set(pp.NO_COUNTERPART)
    assert len(pp.KEYS) == 30 and len(pp.NO_COUNTERPART) == 14


def test_site_totals_pass_within_ten_dollars_and_an_unreachable_site_never_passes():
    assert pp.site_status(100.0, 109.0) == "pass"
    assert pp.site_status(100.0, 111.0) == "fail"
    assert pp.site_status(None, 100.0) == pp.UNREACHABLE


def test_volume2_programs_are_read_from_the_first_total_expenditure_line():
    text = "\n".join([
        "Q00R02.02 Maryland Correctional Training Center - Division of Correction",
        "Appropriation Statement 2021", "Total Operating Expenses 36,550,632 39,107,244 31,864,493",
        "Total Expenditure 86,863,011 87,043,761 84,118,567", "Total Expenditure 86,863,011 87,043,761 84,118,567",
        "Q00R02.03 Roxbury Correctional Institution", "Total Expenditure 63,124,184 61,783,431 65,064,962",
        "Q00R02.02 Maryland Correctional Training Center (repeated page)", "Total Expenditure 1 2 3"])
    book = pp.parse_programs(text)
    assert book == {"Q00R02.02": 86863011.0, "Q00R02.03": 63124184.0}
    assert pp.program_match(book, {"Q00R02.02": 86863011.0, "Q00R02.03": 63124000.0, "X00A01.01": 5.0}) == (2, 1)
