"""
chunk.py — Stage 2 of the Vigil EMT ingestion pipeline.

Reads parsed_output.json (Unsiloed output) and produces chunks.json —
a flat list of Moss-ready documents, one per dose statement.

Chunking rules (from project spec):
  - Table rows → one chunk each (each row = one dose statement for one patient type)
  - Multi-condition doses (e.g. "For bradycardia, ... For organophosphate, ...") are
    split into separate chunks so each chunk is a single answerable dosage fact.
  - Prose segments (SectionHeader / Text) are not dose facts; skipped for now.

Dev mode: set DEV_DRUGS to a subset of drug names to limit output during iteration.

Run: python3 chunk.py [--all]
     python3 chunk.py          # dev mode: 2 drugs only
     python3 chunk.py --all    # full 26-drug run
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent.resolve()
INPUT  = HERE / "parsed_output.json"
OUTPUT = HERE / "chunks.json"
SOURCE = "CoSD-EMS-P-115-2025"

# Dev mode: process only these two drugs (covers simple + multi-condition cases)
DEV_DRUGS = {"EPINEPHRINE (1:1,000)", "ATROPINE"}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-")


# Number → spoken-English words (covers the values that appear in EMT dosing)
_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

def _int_to_words(n: int) -> str:
    if n == 0:
        return "zero"
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        rem = n % 100
        return _ONES[n // 100] + " hundred" + (" " + _int_to_words(rem) if rem else "")
    if n < 10000:
        rem = n % 1000
        return _int_to_words(n // 1000) + " thousand" + (" " + _int_to_words(rem) if rem else "")
    return str(n)

def number_to_words(token: str) -> str:
    """'1,000' → 'one thousand', '0.5' → 'zero point five', '300' → 'three hundred'"""
    token = token.replace(",", "")
    if "." in token:
        integer, decimal = token.split(".", 1)
        int_part = _int_to_words(int(integer)) if integer else "zero"
        dec_part = " ".join(_ones_digit(d) for d in decimal)
        return f"{int_part} point {dec_part}"
    return _int_to_words(int(token))

def _ones_digit(d: str) -> str:
    return _ONES[int(d)] if d != "0" else "zero"

_UNIT_SPOKEN = {
    "mg":    "milligrams",
    "mcg":   "micrograms",
    "g":     "grams",
    "gm":    "grams",
    "ml":    "milliliters",
    "ml ":   "milliliters",
    "meq":   "milliequivalents",
    "units": "units",
    "unit":  "unit",
}

def value_spoken(dose_text: str) -> str | None:
    """
    Extract the administered dose + unit and return spoken form.
    e.g. 'Epinephrine 1:1,000 (1 mg/mL) 0.5 mg IM' → 'zero point five milligrams'
         '1,000 mg IV over 15 min' → 'one thousand milligrams'

    Skips concentrations written as X unit/unit (e.g. '1 mg/mL') or inside parens.
    """
    # Strip parenthetical concentration annotations like '(1 mg/mL)' or '(0.01 mg/mL)'
    cleaned = re.sub(r"\([^)]*mg/[^)]*\)", "", dose_text)
    # Match dose values NOT followed immediately by '/' (which signals a ratio/concentration)
    m = re.search(
        r"([\d,]+(?:\.\d+)?)\s*(mg|mcg|g|gm|mL|mEq|units?)\b(?!\s*/)",
        cleaned,
        re.IGNORECASE,
    )
    if not m:
        return None
    num_str = m.group(1)
    unit = m.group(2).lower().rstrip()
    spoken_num = number_to_words(num_str)
    spoken_unit = _UNIT_SPOKEN.get(unit, unit)
    return f"{spoken_num} {spoken_unit}"


_ROUTE_RE = re.compile(
    r"\b(IV|IO|IM|SQ|SC|IN|PO|SL|ET|PR|NEB|MDI)\b"
)

def extract_routes(text: str) -> list[str]:
    return sorted(set(_ROUTE_RE.findall(text)))


# ---------------------------------------------------------------------------
# Dose-text parsing
# ---------------------------------------------------------------------------

def split_conditions(dose_text: str) -> list[str]:
    """
    Split a multi-condition dose string into individual statements.

    Handles two patterns seen in this document:
      1. 'For [condition], [dose]For [condition2], [dose2]'   (no separator, e.g. '3 mgFor')
      2. 'For [condition], [dose]. For [condition2], [dose2]' (period+space)
      3. Single dose with no 'For' prefix
    """
    # Insert a split marker before each 'For ' that is preceded by a non-space char
    # (catches both '3 mgFor' and '. For' patterns)
    marked = re.sub(r"(?<=[^\s])(?=For )", "\x00", dose_text)
    parts = marked.split("\x00")
    return [p.strip() for p in parts if p.strip()]


def parse_condition(part: str) -> tuple[str | None, str]:
    """
    'For unstable bradycardia, atropine 1 mg IV/IO ...'
    → condition='unstable bradycardia', dose='atropine 1 mg IV/IO ...'

    'Epinephrine 1:1,000 (1 mg/mL) 0.5 mg IM ...'
    → condition=None, dose=<full text>
    """
    m = re.match(r"For ([^,]+),\s*(.*)", part, re.DOTALL)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, part.strip()


def clean_indication(raw: str) -> str:
    """
    'Management of acute painProtocols: S-141' → 'acute pain'
    'Management of anaphylaxis, severe respiratory distress/failure...' → 'anaphylaxis'
    'Antiplatelet agent for the care of patients suspected of suffering from an
     acute coronary syndrome' → 'acute coronary syndrome'

    When multiple indications are listed (comma-separated), returns the first one.
    """
    raw = re.sub(r"^Management of\s+", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*Protocols?:.*$", "", raw, flags=re.IGNORECASE)
    raw = raw.strip().rstrip(".")
    # If multiple indications, use the first
    first = re.split(r",\s*(?:severe |symptomatic |and )", raw)[0].strip()
    # If still long (e.g. class-description preamble), extract the terminal clinical phrase
    if len(first) > 55:
        m = re.search(
            r"(?:from an?|of an?|presenting with|for )\s+(.+)$",
            first,
            re.IGNORECASE,
        )
        if m:
            first = m.group(1).strip()
    return first


# ---------------------------------------------------------------------------
# Table parser → list of dose records
# ---------------------------------------------------------------------------

def extract_field(md: str, label: str) -> str | None:
    """Pull the text after **Label**<br> up to the next | | | boundary."""
    pattern = rf"\*\*{re.escape(label)}\*\*\s*<br>(.*?)(?=\s*\|\s*\|\s*\||\Z)"
    m = re.search(pattern, md, re.DOTALL)
    return m.group(1).strip() if m else None


def parse_table(seg: dict, drug_name: str) -> list[dict]:
    """Return a list of dose-record dicts from one drug Table segment."""
    md = seg["markdown"]
    page = seg["page_number"]
    conf = round(seg["confidence"], 2)

    raw_indication = extract_field(md, "Indications")
    general_indication = clean_indication(raw_indication) if raw_indication else "unknown"

    adult_raw = extract_field(md, "Adult Dose")
    peds_raw  = extract_field(md, "Pediatric Dose")

    records: list[dict] = []

    for patient_type, dose_raw in [("adult", adult_raw), ("pediatric", peds_raw)]:
        if not dose_raw or "per drug chart" in dose_raw.lower():
            # 'per drug chart' means the dose isn't stated — skip (weight-based lookup)
            continue

        conditions = split_conditions(dose_raw)
        for idx, part in enumerate(conditions):
            condition, dose_text = parse_condition(part)
            indication = condition if condition else general_indication

            routes = extract_routes(dose_text)
            v_spoken = value_spoken(dose_text)

            # Natural-language sentence for embedding + TTS
            text = (
                f"{drug_name}, {indication}, {patient_type}: {dose_text.rstrip('.')}."
            )

            chunk_id = f"{slugify(drug_name)}-{slugify(indication)}-{patient_type}-{idx}"

            records.append({
                "id": chunk_id,
                "text": text,
                "metadata": {
                    "drug":          drug_name,
                    "indication":    indication,
                    "patient_type":  patient_type,
                    "route":         ", ".join(routes) if routes else None,
                    "value_machine": dose_text,
                    "value_spoken":  v_spoken,
                    "source":        SOURCE,
                    "page":          page,
                    "confidence":    conf,
                },
            })

    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    dev_mode = "--all" not in sys.argv

    with open(INPUT) as f:
        data = json.load(f)

    all_segs = [s for c in data["chunks"] for s in c.get("segments", [])]

    headers: dict[int, str] = {}
    for s in all_segs:
        if s["segment_type"] == "SectionHeader":
            name = (s.get("markdown") or "").strip().lstrip("#").strip()
            if name and len(name) < 80:
                headers[s["page_number"]] = name

    tables = [s for s in all_segs if s["segment_type"] == "Table"]

    mode_label = f"DEV ({', '.join(sorted(DEV_DRUGS))})" if dev_mode else "FULL"
    print(f"\nChunker running in {mode_label} mode\n")

    all_chunks: list[dict] = []
    skipped = 0

    for seg in tables:
        drug = headers.get(seg["page_number"])
        if drug:
            drug = " ".join(drug.split())   # collapse internal newlines/whitespace
        if not drug:
            skipped += 1
            continue
        if dev_mode and drug not in DEV_DRUGS:
            continue

        records = parse_table(seg, drug)
        if not records:
            skipped += 1
            continue

        all_chunks.extend(records)
        print(f"  {drug} (p{seg['page_number']}) → {len(records)} chunk(s)")
        for r in records:
            print(f"    [{r['metadata']['patient_type']:9}] {r['id']}")
            print(f"      text:    {r['text'][:120]}")
            print(f"      route:   {r['metadata']['route']}")
            print(f"      spoken:  {r['metadata']['value_spoken']}")
            print()

    with open(OUTPUT, "w") as f:
        json.dump(all_chunks, f, indent=2)

    print(f"{'=' * 60}")
    print(f"Total chunks written : {len(all_chunks)}")
    print(f"Skipped (no drug name or no dose): {skipped}")
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()
