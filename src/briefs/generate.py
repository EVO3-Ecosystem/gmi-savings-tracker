"""One-line agency briefs from computed facts, with two generator backends and a guardrail.

    python -m src.briefs.generate [--backend template|gemini] [--out docs/briefs_sample.csv] [--source export|duckdb] [--limit N]

Backends: `template` (deterministic, no network) and `gemini` (google-genai SDK, model and settings from config/briefs.yaml,
key from the environment variable GEMINI_API_KEY; when the key or the SDK is missing it is skipped with a notice and the
template is used). Every generated sentence goes through guardrail.check: a sentence with a number that is not a fact value
or that names another agency is rejected, logged, and replaced by the template sentence. The output is a mart-ready CSV
(agency_code, agency, fiscal_year, brief, backend, guardrail, run_id); it is not wired into the build yet.
"""
import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path

import yaml

from src.mcp.store import ROOT, Store

from . import facts as F
from . import guardrail

log = logging.getLogger("briefs")
CONFIG = ROOT / "config" / "briefs.yaml"
COLUMNS = ["agency_code", "agency", "fiscal_year", "brief", "backend", "guardrail", "run_id"]


def config():
    return yaml.safe_load(CONFIG.read_text()) if CONFIG.exists() else {}


class TemplateGenerator:
    name = "template"

    def generate(self, f):
        d = f["display"]
        s = f"{f['agency']} paid {d['payments']} to payees in FY{f['fiscal_year']}"
        if "payments_change" in d:
            s += f", {d['payments_change']} from FY{f['prior_year']}"
        if "operating_spending" in d:
            s += f"; its FY{f['fiscal_year']} operating budget ({(f['stage'] or 'budget').lower()}) was {d['operating_spending']}"
        if f.get("top_vendor") and "top_vendor_paid" in d:
            s += f", and its largest private vendor was {f['top_vendor']} at {d['top_vendor_paid']}"
        return s + "."


class GeminiGenerator:
    """Gemini through the google-genai SDK. client: an object with .models.generate_content (tests pass a fake)."""
    name = "gemini"
    PROMPT = ("Write one plain sentence of at most 40 words summarizing this Maryland State agency's spending for a public dashboard. "
              "Use only the facts below, and write each number exactly as its display value shows. Name only this agency, by its exact "
              "name; do not name any other agency, compare, speculate, or add numbers that are not in the facts. Reply with the sentence only.\n\n")

    def __init__(self, model, client=None, temperature=0.0, max_output_tokens=120):
        self.model, self.temperature, self.max_output_tokens = model, temperature, max_output_tokens
        if client is None:
            from google import genai  # optional dependency: pip install -e ".[ai]"
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.client = client

    def generate(self, f):
        payload = {k: f[k] for k in ("agency", "agency_code", "fiscal_year", "prior_year", "stage", "top_vendor") if f.get(k)}
        payload["display"] = f["display"]
        cfg = {"temperature": self.temperature, "max_output_tokens": self.max_output_tokens}
        try:
            from google.genai import types
            cfg = types.GenerateContentConfig(**cfg)
        except ImportError:
            pass
        r = self.client.models.generate_content(model=self.model, contents=self.PROMPT + json.dumps(payload, indent=1), config=cfg)
        return (getattr(r, "text", None) or "").strip()


def get_generator(name, cfg=None):
    """The requested generator, or None (with a notice) when gemini cannot run here."""
    cfg = cfg if cfg is not None else config()
    if name == "template":
        return TemplateGenerator()
    if name == "gemini":
        g = cfg.get("gemini", {})
        if not os.environ.get("GEMINI_API_KEY"):
            log.warning("gemini backend skipped: GEMINI_API_KEY is not set; using the template backend")
            return None
        try:
            import google.genai  # noqa: F401
        except ImportError:
            log.warning("gemini backend skipped: google-genai is not installed (pip install -e \".[ai]\"); using the template backend")
            return None
        return GeminiGenerator(g.get("model", "gemini-2.5-flash"), temperature=g.get("temperature", 0.0),
                               max_output_tokens=g.get("max_output_tokens", 120))
    raise ValueError(f"unknown backend {name!r}: template or gemini")


def build(fact_rows, generator, agencies, run_id=None):
    """Mart-ready rows; any sentence that fails the guardrail (or the backend call) is replaced by the template's."""
    tmpl = TemplateGenerator()
    out = []
    for f in fact_rows:
        backend, note = generator.name, "passed"
        try:
            s = generator.generate(f)
        except Exception as e:  # a backend failure must not stop the build: fall back like a rejection
            s, problems = "", [f"backend error: {type(e).__name__}: {e}"]
        else:
            problems = guardrail.check(s, f, agencies)
        if problems:
            log.warning("brief for %s rejected (%s): %r; using the template", f["agency_code"], "; ".join(problems), s)
            s, backend, note = tmpl.generate(f), "template", "rejected " + generator.name + ": " + "; ".join(problems)
            left = guardrail.check(s, f, agencies)
            if left:  # the template must always pass; a failure here is a bug in facts.py or the template
                raise AssertionError(f"template brief for {f['agency_code']} fails the guardrail: {left}")
        out.append({"agency_code": f["agency_code"], "agency": f["agency"], "fiscal_year": f["fiscal_year"], "brief": s,
                    "backend": backend, "guardrail": note, "run_id": run_id})
    return out


def agency_list(store):
    return [(r["agency_code"], r["agency"]) for r in store.sql("SELECT DISTINCT agency_code, agency FROM mart.f_agency WHERE agency IS NOT NULL")]


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", choices=["template", "gemini"], default="template")
    ap.add_argument("--out", default=str(ROOT / "docs" / "briefs_sample.csv"))
    ap.add_argument("--source", choices=["export", "duckdb"], default="export", help="export: site_data/ (reproducible); duckdb: the database file")
    ap.add_argument("--fiscal-year", type=int)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    store = Store(export_dir=ROOT / "site_data", prefer="export") if a.source == "export" else Store(prefer="duckdb")
    rows = F.agency_facts(store, a.fiscal_year)[: a.limit]
    gen = get_generator(a.backend) or TemplateGenerator()
    out = build(rows, gen, agency_list(store), store.run.get("run_id"))
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(out)
    rej = sum(r["guardrail"] != "passed" for r in out)
    print(f"briefs: {len(out)} agencies, FY{rows[0]['fiscal_year'] if rows else '?'}, backend {gen.name}, {rej} rejected and replaced -> {Path(a.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
