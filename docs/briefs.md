# Agency briefs (Gemini, with a numeric guardrail)

`src/briefs/` writes one sentence per agency from facts computed from the marts, for a dashboard card. A language model may
word the sentence, but it may not supply a number: every figure in the sentence must be one of the agency's fact values,
and the only agency it may name is the one asked for. A sentence that fails is rejected, logged, and replaced by the
deterministic template sentence, so the output never depends on the model being right.

Independent prototype by Sierra Napier, built from Maryland's open data; not an official State of Maryland product.

## Run it

```bash
python -m src.briefs.generate                      # template backend, from site_data/ -> docs/briefs_sample.csv
pip install -e ".[ai]"                             # google-genai==2.29.0
GEMINI_API_KEY=... python -m src.briefs.generate --backend gemini --out /tmp/d_briefs.csv
```

Options: `--source export|duckdb` (the checked-in `site_data/` export, the default and reproducible, or the database file),
`--fiscal-year` (default: the latest year with payments), `--limit`.

## Pieces

| file | what it does |
|---|---|
| `facts.py` | Per agency, for the year: payments and the change from the year before, operating budget and its stage, controllable purchases, the private vendor paid most (`mart.f_agency`, `mart.f_vendor_pay`, read through the MCP server's read-only `Store`), and a display string for each number |
| `generate.py` | The generator interface (`generate(facts) -> str`) with two backends, `build()` (guardrail and fallback), and the CLI |
| `guardrail.py` | `check(sentence, facts, agencies) -> [problems]` |
| `config/briefs.yaml` | Gemini model, temperature, output length. No key: the key is read from `GEMINI_API_KEY` only |

Backends:

- **template**: deterministic, no network. "Maryland Department of Health paid $17.47 billion to payees in FY2026, up 5.3%
  from FY2025; its FY2026 operating budget (working) was $23.87 billion, and its largest private vendor was PRIORITY
  PARTNERS MCO at $1.53 billion."
- **gemini**: the google-genai SDK (`client.models.generate_content`, temperature 0), given the facts with their display
  strings and told to use only them. Skipped with a notice, and the template used, when `GEMINI_API_KEY` is unset or the
  SDK is not installed. A backend error (quota, network) is treated like a rejection.

## Guardrail

1. **Numbers.** Each number is read with its unit and the precision it is written to: `$11.38 billion`, `$742.4 million`,
   `$512,300`, `3.4%`, `1,394`. It passes when some fact value, rounded to that precision, gives the same number, so
   "$17.5 billion" and "$17 billion" both match 17,466,051,234.56 but "$18.2 billion" and "$17.47 million" do not.
   Percentages are checked against the change facts; years must be the fact year or the year before.
2. **Direction.** With a percentage, "fell"/"down" when payments rose (or the reverse) is rejected.
3. **Agency.** The asked agency's name or code must appear; no other agency's name or code may. Names in the facts (the
   agency, the top vendor) are removed before numbers are read, so digits inside a name are not taken as figures.

Rejected sentences are logged (`WARNING briefs: brief for M00 rejected (...)`) and recorded in the output's `guardrail`
column (`rejected gemini: <reasons>`), with `backend` set to `template`. `build()` also asserts that the template sentence
itself passes, so a template or facts bug fails loudly.

Tests (`tests/test_briefs.py`): six crafted good sentences pass (the template, other roundings, the code instead of the
name, the prior year, controllable purchases, the vendor amount); ten crafted bad ones are rejected for the right reason
(a wrong total, a wrong percentage, an invented count, a wrong year, the wrong direction, another agency's name, another
agency's code, no agency, the wrong scale, empty); a fake Gemini client checks the replacement, the logging, the error
fallback and the prompt; every template brief from the snapshot passes and equals `docs/briefs_sample.csv`.

## Output

`docs/briefs_sample.csv` (template backend, from `site_data/`): one row per agency with payments in the year.

| column | meaning |
|---|---|
| agency_code, agency, fiscal_year | the agency and year the facts are for |
| brief | the sentence |
| backend | `template` or `gemini` (the backend whose sentence was kept) |
| guardrail | `passed`, or `rejected <backend>: <reasons>` when the template replaced a generated sentence |
| run_id | the pipeline run of the data |

It is mart-ready (`d_briefs.csv`) but not wired into the build or the export yet.
