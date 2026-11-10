"""Guardrail for generated briefs: a sentence passes only if every number in it is one of the agency's fact values and the
only agency it names is the one asked for.

Numbers: each number in the sentence ($11.38 billion, $742.4 million, $512,300, 3.4%, 1,394, FY2025) is parsed with its
unit and the precision it is written to; it matches a fact when the fact, rounded to that precision, gives the same number
(so "$11.4 billion" and "$11.38 billion" both match 11,381,120,168.34). Percentages are compared with the facts that are
shares or changes (times 100, sign carried by the words: a "down" or "fell" with a positive change is rejected, and the
reverse). Years must be the fact's fiscal year or the year before. Names: the asked agency's name (or code) must appear;
no other agency's name or code may. Names in the facts (the agency, the top vendor) are removed before numbers are read,
so digits inside a name are not taken for figures.
"""
import re

MULT = {"trillion": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
NUM = re.compile(r"(?P<cur>\$)?\s?(?<![A-Za-z\d.,])(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<unit>%|percent\b|trillion\b|billion\b|bn\b|million\b|mn\b|thousand\b|[bmk]\b)?", re.I)
YEAR = re.compile(r"\b(?:FY\s?|fiscal (?:year )?)?((?:19|20)\d{2})\b", re.I)
CODE = re.compile(r"\b[A-Z]\d{2}\b")
UP = re.compile(r"\b(up|rose|risen|increas\w*|grew|grow\w*|higher|more than the year)\b", re.I)
DOWN = re.compile(r"\b(down|fell|fallen|declin\w*|decreas\w*|dropp\w*|lower|less than the year|shrank|cut)\b", re.I)
PCT_FACTS = ("payments_change",)
MONEY_FACTS = ("payments", "payments_prior", "operating_spending", "controllable", "top_vendor_paid")


def numbers(text):
    """[(value, tolerance, kind)] for each number in text; kind is money, pct, year or plain."""
    out = []
    for m in YEAR.finditer(text):
        out.append((int(m.group(1)), 0, "year"))
    text = YEAR.sub(" ", text)
    for m in NUM.finditer(text):
        raw = m.group("num").replace(",", "")
        if not re.search(r"\d", raw):
            continue
        dec = len(raw.split(".")[1]) if "." in raw else 0
        v = float(raw)
        unit = (m.group("unit") or "").lower()
        half = 0.5 * 10 ** -dec
        if unit in ("%", "percent"):
            out.append((v, half + 1e-9, "pct"))
        elif unit in MULT:
            out.append((v * MULT[unit], half * MULT[unit] + 1e-6, "money"))
        elif m.group("cur"):
            out.append((v, half + 1e-6, "money"))
        else:
            out.append((v, half + 1e-6, "plain"))
    return out


def check(sentence, facts, agencies):
    """List of problems (empty when the sentence passes). agencies: [(code, name)] of every agency in the data."""
    problems = []
    s = " ".join(str(sentence or "").split())
    if not s:
        return ["empty sentence"]
    name, code = facts["agency"], facts["agency_code"]
    if name.lower() not in s.lower() and not re.search(rf"\b{re.escape(code)}\b", s):
        problems.append(f"does not name the agency asked for ({code} {name})")
    rest = s
    for n in sorted({x for x in (name, facts.get("top_vendor")) if x}, key=len, reverse=True):
        rest = re.sub(re.escape(n), " ", rest, flags=re.I)
    rest = re.sub(rf"\b{re.escape(code)}\b", " ", rest)
    for c, n in agencies:
        if c == code or not n or n.lower() in name.lower():
            continue
        if re.search(rf"\b{re.escape(n)}\b", rest, re.I):
            problems.append(f"names another agency: {n}")
    for c in set(CODE.findall(rest)) - {code}:
        if c in {a for a, _ in agencies}:
            problems.append(f"names another agency code: {c}")
    years = {facts["fiscal_year"], facts["prior_year"]}
    money = [abs(facts[k]) for k in MONEY_FACTS if facts.get(k)]
    pct = [abs(facts[k]) * 100 for k in PCT_FACTS if facts.get(k) is not None]
    for v, tol, kind in numbers(rest):
        if kind == "year":
            if v not in years:
                problems.append(f"year {v} is not FY{facts['prior_year']} or FY{facts['fiscal_year']}")
            continue
        pool = pct if kind == "pct" else money if kind == "money" else money + pct
        if not any(abs(f - v) <= tol for f in pool):
            problems.append(f"number {v:,.6g} ({kind}) matches no fact")
    ch = facts.get("payments_change")
    if ch is not None and pct and any(k == "pct" for _, _, k in numbers(rest)):
        if ch < 0 and UP.search(rest) and not DOWN.search(rest):
            problems.append("says payments rose but they fell")
        if ch > 0 and DOWN.search(rest) and not UP.search(rest):
            problems.append("says payments fell but they rose")
    return problems
