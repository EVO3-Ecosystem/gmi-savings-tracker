"""Agency briefs: the template always passes the guardrail; crafted good sentences pass and bad ones (a number that is not
a fact, another agency, a wrong year or direction) are rejected and replaced by the template, with a log line."""
import logging
import re
from pathlib import Path

import pytest

from src.briefs import facts as F
from src.briefs import generate as G
from src.briefs import guardrail

ROOT = Path(__file__).resolve().parents[1]
FACTS = {"agency_code": "M00", "agency": "Maryland Department of Health", "fiscal_year": 2026, "prior_year": 2025,
         "payments": 17_466_051_234.56, "payments_prior": 16_592_921_743.08, "payments_change": 0.052621,
         "operating_spending": 23_871_234_567.0, "stage": "Working", "controllable": 412_345_678.0,
         "top_vendor": "PRIORITY PARTNERS MCO", "top_vendor_paid": 1_530_123_456.7}
FACTS["display"] = {"payments": "$17.47 billion", "payments_prior": "$16.59 billion", "payments_change": "up 5.3%",
                    "operating_spending": "$23.87 billion", "controllable": "$412.3 million", "top_vendor_paid": "$1.53 billion"}
AGENCIES = [("M00", "Maryland Department of Health"), ("J00", "Department of Transportation"), ("R00", "State Department of Education"),
            ("C00", "Judiciary"), ("D50", "Military Department")]

GOOD = {
    "template": G.TemplateGenerator().generate(FACTS),
    "rounded differently": "Maryland Department of Health payments rose 5.3% to about $17.5 billion in FY2026.",
    "whole billions": "In fiscal 2026 the Maryland Department of Health paid roughly $17 billion, up 5.3% from FY2025.",
    "by code, prior year figure": "M00 paid $16.59 billion in FY2025 and $17.47 billion in FY2026.",
    "controllable in millions": "Maryland Department of Health had $412.3 million in controllable purchases in FY2026.",
    "vendor amount": "Maryland Department of Health's largest private vendor, PRIORITY PARTNERS MCO, received $1.53 billion in FY2026.",
}
BAD = {
    "wrong total": ("Maryland Department of Health paid $18.2 billion to payees in FY2026.", "matches no fact"),
    "wrong percent": ("Maryland Department of Health payments rose 7.5% in FY2026.", "matches no fact"),
    "invented count": ("Maryland Department of Health paid 1,200 vendors $17.47 billion in FY2026.", "matches no fact"),
    "wrong year": ("Maryland Department of Health paid $17.47 billion in FY2019.", "year 2019"),
    "wrong direction": ("Maryland Department of Health payments fell 5.3% to $17.47 billion in FY2026.", "fell but they rose"),
    "another agency": ("Maryland Department of Health paid $17.47 billion in FY2026, more than the Department of Transportation.",
                       "another agency: Department of Transportation"),
    "another agency code": ("Maryland Department of Health (M00) paid $17.47 billion in FY2026, ahead of J00.", "another agency code: J00"),
    "agency missing": ("The agency paid $17.47 billion to payees in FY2026.", "does not name the agency"),
    "wrong scale": ("Maryland Department of Health paid $17.47 million to payees in FY2026.", "matches no fact"),
    "empty": ("", "empty"),
}


@pytest.mark.parametrize("s", GOOD.values(), ids=GOOD.keys())
def test_good_sentences_pass(s):
    assert guardrail.check(s, FACTS, AGENCIES) == []


@pytest.mark.parametrize("s,why", BAD.values(), ids=BAD.keys())
def test_bad_sentences_are_rejected_with_the_reason(s, why):
    problems = guardrail.check(s, FACTS, AGENCIES)
    assert problems and any(why in p for p in problems), problems


def test_numbers_are_parsed_with_their_unit_and_precision():
    got = guardrail.numbers("FY2026: $11.38 billion, $742.4 million, $512,300, 3.4%, 1,394")
    assert got[0] == (2026, 0, "year")
    vals = [(round(v, 2), k) for v, _, k in got[1:]]
    assert vals == [(11.38e9, "money"), (742.4e6, "money"), (512300.0, "money"), (3.4, "pct"), (1394.0, "plain")]
    assert got[1][1] == pytest.approx(0.005e9, rel=1e-6)  # two decimals of billions: half a cent of the unit


class FakeModels:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents))
        text = self.replies.pop(0)
        if isinstance(text, Exception):
            raise text
        return type("R", (), {"text": text})()


def test_rejected_sentences_are_replaced_by_the_template_and_logged(caplog):
    fake = type("C", (), {"models": FakeModels([GOOD["rounded differently"], BAD["another agency"][0], RuntimeError("quota")])})()
    gen = G.GeminiGenerator("gemini-test", client=fake)
    other = dict(FACTS, agency_code="R00", agency="State Department of Education", top_vendor="HCPPS")
    with caplog.at_level(logging.WARNING, logger="briefs"):
        rows = G.build([FACTS, FACTS, other], gen, AGENCIES, run_id="r1")
    assert [r["backend"] for r in rows] == ["gemini", "template", "template"]
    assert rows[0]["brief"] == GOOD["rounded differently"] and rows[0]["guardrail"] == "passed"
    assert rows[1]["brief"] == G.TemplateGenerator().generate(FACTS) and rows[1]["guardrail"].startswith("rejected gemini: names another agency")
    assert "backend error: RuntimeError: quota" in rows[2]["guardrail"]
    assert sum("rejected" in r.message for r in caplog.records) == 2
    model, prompt = fake.models.calls[0]
    assert model == "gemini-test" and '"payments": "$17.47 billion"' in prompt and "Maryland Department of Health" in prompt


def test_gemini_is_skipped_cleanly_without_a_key(monkeypatch, caplog):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger="briefs"):
        assert G.get_generator("gemini", {"gemini": {"model": "gemini-2.5-flash"}}) is None
    assert "GEMINI_API_KEY is not set" in caplog.text
    assert G.get_generator("template").name == "template"


def test_the_model_comes_from_config_and_no_key_is_stored():
    cfg = G.config()
    assert cfg["gemini"]["model"]
    text = (ROOT / "config" / "briefs.yaml").read_text()
    assert "AIza" not in text and not re.search(r"^\s*(api_)?key\s*:", text, re.I | re.M)


def test_template_briefs_from_the_snapshot_all_pass_and_match_the_sample():
    from src.mcp.store import Store
    st = Store(export_dir=ROOT / "site_data", prefer="export")
    rows = F.agency_facts(st)
    agencies = G.agency_list(st)
    out = G.build(rows, G.TemplateGenerator(), agencies, st.run["run_id"])
    assert len(out) > 50 and all(r["guardrail"] == "passed" for r in out)
    import csv
    sample = list(csv.DictReader(open(ROOT / "docs" / "briefs_sample.csv")))
    assert [r["brief"] for r in sample] == [r["brief"] for r in out], "regenerate with: python -m src.briefs.generate"
    assert list(sample[0]) == G.COLUMNS
