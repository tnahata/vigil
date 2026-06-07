"""
chunk.py — Stage 2 of the Vigil EMT ingestion pipeline.

Reads parsed_output.json (Unsiloed output) and produces chunks.json —
a flat list of Moss-ready documents, one per dose statement.

Chunking strategy (aligned with Moss best practices):
  - Target: 200-500 tokens per chunk.
  - Each dose chunk is the atomic clinical fact (drug + indication +
    population + dose), ENRICHED with class, mechanism, contraindications,
    and adverse effects from the same page.  This replaces sliding-window
    overlap: our data is structured tables, not prose, so context injection
    into each chunk is the correct analogue.
  - Whitespace is normalized (collapse runs, strip OCR artefacts).
  - Contraindications are emitted as a separate chunk AND embedded inline
    in every dose chunk for the same drug (so Tier-2 semantic search can
    match "Is X contraindicated for Y?" against dose records).

Record types stored in metadata["record_type"]:
  "dose"              — explicitly stated adult or pediatric dose
  "dose_weight_based" — peds dose deferred to a weight chart; route/admin
                        details still captured so agent can acknowledge
  "contraindication"  — standalone chunk for direct contraindication queries

Dev mode (default): processes only DEV_DRUGS so iteration is fast.
Run python3 chunk.py --all for the full 26-drug pass.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

HERE   = Path(__file__).parent.resolve()
INPUT  = HERE / "parsed_output.json"
OUTPUT = HERE / "chunks.json"
SOURCE = "CoSD-EMS-P-115-2025"

DEV_DRUGS = {"EPINEPHRINE (1:1,000)", "ATROPINE"}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-")


def normalize_ws(text: str) -> str:
    """Collapse whitespace runs and strip OCR line-break artefacts."""
    return re.sub(r"\s+", " ", text).strip()


def clean_text(text: str) -> str:
    """Final boilerplate strip applied to every embedded chunk text.

    Moss's chunking guidance is "normalize whitespace and strip boilerplate".
    This is the defensive backstop: even if a field-extraction regex ever lets
    a markdown artefact through, the text that actually gets embedded carries
    no ``**`` bold markers, no ``<br>`` tags, and no doubled punctuation.
    """
    text = text.replace("<br>", " ").replace("**", " ")
    text = re.sub(r"\s*\.\s*\.\s*", ". ", text)   # collapse ".." / ". ." -> "."
    text = re.sub(r"\s+([.,;:])", r"\1", text)     # no space before punctuation
    text = re.sub(r"(?<=[a-z])\.(?=[A-Z])", ". ", text)  # OCR seam: "...reassurance.If" -> ". If"
    return normalize_ws(text)


def split_bullet_items(raw: str) -> list[str]:
    """
    Split run-together OCR text into individual list items.

    Unsiloed concatenates bullet items without separators, e.g.:
      "Severe liver diseaseKnown or suspected dose exceeding 4,000 mg"
    Split on a capital letter that immediately follows a lower-case letter
    or digit (i.e., the seam between two items).
    """
    split = re.sub(r"(?<=[a-z0-9)])(?=[A-Z])", "\n", raw)
    items = [l.strip(" •-–\n") for l in split.splitlines()]
    return [i for i in items if i]


# Number → spoken-English words (covers the values that appear in EMT dosing)
_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty",
         "sixty", "seventy", "eighty", "ninety"]


def _int_to_words(n: int) -> str:
    if n == 0:   return "zero"
    if n < 20:   return _ONES[n]
    if n < 100:  return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        rem = n % 100
        return _ONES[n // 100] + " hundred" + (" " + _int_to_words(rem) if rem else "")
    if n < 10_000:
        rem = n % 1000
        return _int_to_words(n // 1000) + " thousand" + (" " + _int_to_words(rem) if rem else "")
    return str(n)


def number_to_words(token: str) -> str:
    """'1,000' → 'one thousand', '0.5' → 'zero point five'"""
    token = token.replace(",", "")
    if "." in token:
        integer, decimal = token.split(".", 1)
        int_part = _int_to_words(int(integer)) if integer else "zero"
        dec_part = " ".join((_ONES[int(d)] if d != "0" else "zero") for d in decimal)
        return f"{int_part} point {dec_part}"
    return _int_to_words(int(token))


_UNIT_SPOKEN = {
    "mg": "milligrams", "mcg": "micrograms",
    "g": "grams", "gm": "grams",
    "ml": "milliliters", "meq": "milliequivalents",
    "units": "units", "unit": "unit",
}

_ROUTE_RE = re.compile(r"\b(IV|IO|IM|SQ|SC|IN|PO|SL|ET|PR|NEB|MDI)\b")


def _spoken_unit(num_str: str, unit: str) -> str:
    """Map a unit token to its spoken word, singular when the value is exactly 1."""
    word = _UNIT_SPOKEN.get(unit, unit)
    if num_str.replace(",", "") == "1" and word.endswith("s"):
        word = word[:-1]
    return word


def value_spoken(dose_text: str) -> str | None:
    """
    Extract the administered dose + unit and return its spoken form.

    Safety ordering (each step exists to stop Vigil speaking a wrong number):
      1. A weight-normalised dose ("0.3 mg/kg") IS the dose — speak it verbatim
         as "... per kilogram". The medic multiplies by weight.
      2. A mass-over-volume total ("1 gm/10 mL") speaks the MASS ("one gram").
      3. Drop diluent volumes ("in 100 mL of NS") BEFORE the generic match, so
         a diluent is never mistaken for the dose. This was the Ketamine bug:
         "0.3 mg/kg in 100 mL of NS" wrongly spoke "one hundred milliliters".
      4. Drop concentration ratios in parens ("(1 mg/mL)").
      5. Fall back to the first plain number+unit that is not a ratio.
    """
    # 1. Weight-normalised dose takes priority — it is the real order.
    mkg = re.search(
        r"([\d,]+(?:\.\d+)?)\s*(mg|mcg|g|units?)\s*/\s*kg",
        dose_text, re.IGNORECASE,
    )
    if mkg:
        num, unit = mkg.group(1), mkg.group(2).lower().rstrip()
        return f"{number_to_words(num)} {_spoken_unit(num, unit)} per kilogram"

    # 2. Mass stated as a total over a volume ("1 gm/10 mL") -> the MASS is the
    #    dose, not the volume. (TXA: "1 gm/10 mL" must speak "one gram", never
    #    "ten milliliters".) The numeric denominator distinguishes this from a
    #    "per mL" concentration like epi's "0.01 mg/mL".
    mtot = re.search(
        r"([\d,]+(?:\.\d+)?)\s*(mg|mcg|g|gm)\s*/\s*[\d.]+\s*m[lL]\b",
        dose_text, re.IGNORECASE,
    )
    if mtot:
        num, unit = mtot.group(1), mtot.group(2).lower().rstrip()
        return f"{number_to_words(num)} {_spoken_unit(num, unit)}"

    # 3. Strip diluent volumes ("in 100 mL of NS", "in 250 mL D5W").
    cleaned = re.sub(
        r"\bin\s+[\d.,]+\s*m[lL]\b(?:\s+of\s+[\w%]+)?",
        " ", dose_text, flags=re.IGNORECASE,
    )
    # 4. Strip parenthetical concentration ratios.
    cleaned = re.sub(r"\([^)]*mg/[^)]*\)", "", cleaned)

    # 5. First plain number+unit that is not itself a ratio.
    m = re.search(
        r"([\d,]+(?:\.\d+)?)\s*(mg|mcg|g|gm|mL|mEq|units?)\b(?!\s*/)",
        cleaned, re.IGNORECASE,
    )
    if not m:
        return None
    num_str, unit = m.group(1), m.group(2).lower().rstrip()
    return f"{number_to_words(num_str)} {_spoken_unit(num_str, unit)}"


def extract_routes(text: str) -> list[str]:
    return sorted(set(_ROUTE_RE.findall(text)))


# ---------------------------------------------------------------------------
# Dose-text parsing
# ---------------------------------------------------------------------------

def split_conditions(dose_text: str) -> list[str]:
    """
    Split a multi-condition dose string into individual statements.
    Handles both '3 mgFor ...' (no separator) and '. For ...' patterns.
    """
    marked = re.sub(r"(?<=[^\s])(?=For )", "\x00", dose_text)
    return [p.strip() for p in marked.split("\x00") if p.strip()]


def parse_condition(part: str) -> tuple[str | None, str]:
    """
    'For unstable bradycardia, atropine 1 mg IV/IO'
    → ('unstable bradycardia', 'atropine 1 mg IV/IO')
    'Epinephrine 0.5 mg IM'
    → (None, 'Epinephrine 0.5 mg IM')
    """
    m = re.match(r"For ([^,]+),\s*(.*)", part, re.DOTALL)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, part.strip()


def clean_indication(raw: str) -> str:
    raw = re.sub(r"^Management of\s+", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*Protocols?:.*$", "", raw, flags=re.IGNORECASE)
    raw = raw.strip().rstrip(".")
    first = re.split(r",\s*(?:severe |symptomatic |and )", raw)[0].strip()
    if len(first) > 55:
        m = re.search(r"(?:from an?|of an?|presenting with|for )\s+(.+)$",
                      first, re.IGNORECASE)
        if m:
            first = m.group(1).strip()
    return first


# ---------------------------------------------------------------------------
# Field extraction from Unsiloed markdown
# ---------------------------------------------------------------------------

def extract_field(md: str, label: str) -> str | None:
    """Pull the value after **Label**<br> up to the NEXT field boundary.

    Unsiloed packs several **Label**<br>value pairs into one table cell,
    separated only by a space:

        | **Class**<br>Analgesic **Mechanism of Action**<br>... |

    So a field value ends at whichever comes first:
      * the next bold label  (``**``)            — sibling field in the same cell
      * a markdown cell pipe (``|``)             — end of the cell
      * end of string        (``\\Z``)

    The old pattern only stopped at a ``| | |`` row boundary, which let
    ``Class`` swallow ``**Mechanism of Action**<br>...`` and leak raw markdown
    into the embedded text. Stopping at ``**`` / ``|`` keeps each value clean.
    """
    pattern = rf"\*\*{re.escape(label)}\*\*\s*<br>(.*?)(?=\s*\*\*|\s*\||\Z)"
    m = re.search(pattern, md, re.DOTALL)
    return normalize_ws(m.group(1)) if m else None


def extract_field_any(md: str, *labels: str) -> str | None:
    """Try each label in order; return the first match."""
    for label in labels:
        val = extract_field(md, label)
        if val:
            return val
    return None


def build_context_suffix(
    drug_name: str,
    class_raw: str | None,
    mechanism_raw: str | None,
    contra_items: list[str],
    adverse_raw: str | None,
    notes_raw: str | None,
) -> str:
    """
    Build the context string appended to every dose chunk for this drug.

    Purpose: bring each chunk closer to Moss's 200-500 token target so the
    embedding model has enough signal for Tier-2 semantic search.  The dose
    itself stays at the front (highest retrieval weight); context follows.
    """
    parts: list[str] = []

    if class_raw:
        parts.append(f"Class: {class_raw}.")

    if mechanism_raw:
        # Trim to first two sentences — mechanism can be very long.
        sentences = re.split(r"(?<=[.!?])\s+", mechanism_raw)
        parts.append("Mechanism: " + " ".join(sentences[:2]).rstrip(".") + ".")

    if contra_items:
        parts.append("Contraindications: " + "; ".join(contra_items) + ".")

    if adverse_raw:
        items = split_bullet_items(adverse_raw)
        # Cap at 5 adverse effects to avoid bloating tokens.
        parts.append("Adverse effects: " + "; ".join(items[:5]) + ".")

    if notes_raw:
        # First sentence of notes only.
        first_note = re.split(r"(?<=[.!?])\s+", notes_raw)[0].strip().rstrip(".")
        if first_note:
            parts.append(f"Notes: {first_note}.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Table parser → list of Moss-ready records
# ---------------------------------------------------------------------------

def parse_table(seg: dict, drug_name: str) -> list[dict]:
    md   = seg["markdown"]
    page = seg["page_number"]
    conf = round(seg["confidence"], 2)

    # ---- extract every field from the table markdown ----
    raw_indication  = extract_field(md, "Indications")
    general_indication = clean_indication(raw_indication) if raw_indication else "unknown"

    adult_raw    = extract_field(md, "Adult Dose")
    peds_raw     = extract_field(md, "Pediatric Dose")
    contra_raw   = extract_field(md, "Contraindications")
    class_raw    = extract_field_any(md, "Classification", "Class")
    mechanism_raw = extract_field(md, "Mechanism of Action")
    adverse_raw  = extract_field(md, "Adverse Effects")
    notes_raw    = extract_field(md, "Notes")

    # Pre-process contraindications — used both in suffix and as standalone chunk.
    contra_items = split_bullet_items(contra_raw) if contra_raw else []

    # Context suffix shared by all dose chunks for this drug.
    context_suffix = build_context_suffix(
        drug_name, class_raw, mechanism_raw, contra_items, adverse_raw, notes_raw
    )

    records: list[dict] = []

    # ------------------------------------------------------------------ doses
    for patient_type, dose_raw in [("adult", adult_raw), ("pediatric", peds_raw)]:
        if not dose_raw:
            continue

        weight_based = "per drug chart" in dose_raw.lower()
        conditions   = split_conditions(dose_raw)

        for idx, part in enumerate(conditions):
            condition, dose_text = parse_condition(part)
            indication = condition if condition else general_indication

            dose_text_clean = normalize_ws(dose_text.rstrip("."))
            routes    = extract_routes(dose_text_clean)
            v_spoken  = value_spoken(dose_text_clean)

            if weight_based:
                record_type = "dose_weight_based"
                # SAFETY: the spoken dose for a weight-based order lives in the
                # drug chart, not the protocol cell. A regex on this cell tends
                # to grab a diluent volume ("in 100 ml of NS" -> "one hundred
                # milliliters") — speaking that as a dose is precisely the
                # hallucinated-number failure Vigil must never make. Speak an
                # explicit defer-to-chart message unless the cell states an
                # actual weight-normalised dose (mg/kg, mcg/kg).
                has_per_kg = re.search(r"/\s*kg\b", dose_text_clean, re.IGNORECASE)
                v_spoken = v_spoken if has_per_kg else "weight-based — see drug chart"
                core = (
                    f"{drug_name}, {indication}, {patient_type} (weight-based): "
                    f"{dose_text_clean}."
                )
            else:
                record_type = "dose"
                core = f"{drug_name}, {indication}, {patient_type}: {dose_text_clean}."

            # Enrich: append clinical context so the embedding has enough
            # signal for Tier-2 semantic matching.
            text = f"{core} {context_suffix}".strip() if context_suffix else core
            text = clean_text(text)

            chunk_id = (
                f"{slugify(drug_name)}-{slugify(indication)}-{patient_type}-{idx}"
            )

            records.append({
                "id":   chunk_id,
                "text": text,
                "metadata": {
                    "drug":          drug_name,
                    "indication":    indication,
                    "patient_type":  patient_type,
                    "record_type":   record_type,
                    "route":         ", ".join(routes) if routes else None,
                    "value_machine": dose_text_clean,
                    "value_spoken":  v_spoken,
                    "source":        SOURCE,
                    "page":          str(page),
                    "confidence":    str(conf),
                },
            })

    # ---------------------------------------------------- contraindications
    # Standalone chunk — supports direct Tier-1/2 contraindication queries.
    if contra_items:
        contra_text = (
            f"{drug_name} contraindications: "
            + "; ".join(contra_items)
            + "."
        )
        # Add class context so semantic search on "liver disease" or "pregnancy"
        # can surface the right drug's contraindication chunk.
        if class_raw:
            contra_text += f" Class: {class_raw}."

        records.append({
            "id":   f"{slugify(drug_name)}-contraindications",
            "text": clean_text(contra_text),
            "metadata": {
                "drug":          drug_name,
                "indication":    "contraindication",
                "patient_type":  "all",
                "record_type":   "contraindication",
                "route":         None,
                "value_machine": "; ".join(contra_items),
                "value_spoken":  None,
                "source":        SOURCE,
                "page":          str(page),
                "confidence":    str(conf),
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

    # Build page → drug-name map from SectionHeader segments (and Text fallback).
    headers: dict[int, str] = {}
    for s in all_segs:
        is_header = s["segment_type"] == "SectionHeader"
        # Fallback: Unsiloed occasionally labels drug-name banners as "Text"
        # instead of "SectionHeader" (observed on page 19 / Ketamine).
        is_text_header = (
            s["segment_type"] == "Text"
            and (s.get("markdown") or "").strip().isupper()
            and len((s.get("markdown") or "").strip()) < 80
        )
        if is_header or is_text_header:
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
            drug = " ".join(drug.split())   # collapse internal whitespace
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
            tok_est = len(r["text"]) // 4
            print(f"    [{r['metadata']['patient_type']:9}] [{tok_est:3d} tok] {r['id']}")
            print(f"      text:    {r['text'][:140]}")
            print(f"      route:   {r['metadata']['route']}")
            print(f"      spoken:  {r['metadata']['value_spoken']}")
            print()

    with open(OUTPUT, "w") as f:
        json.dump(all_chunks, f, indent=2)

    # ------------------------------------------------------------------ stats
    tok_sizes = [len(c["text"]) // 4 for c in all_chunks]
    by_type: dict[str, int] = {}
    by_pt: dict[str, int]   = {}
    drugs: set[str]         = set()
    for c in all_chunks:
        m = c["metadata"]
        by_type[m["record_type"]] = by_type.get(m["record_type"], 0) + 1
        by_pt[m["patient_type"]]  = by_pt.get(m["patient_type"], 0) + 1
        drugs.add(m["drug"])

    # Metadata field coverage (how many chunks carry a non-empty value).
    META_FIELDS = ["drug", "indication", "patient_type", "record_type",
                   "route", "value_machine", "value_spoken", "source",
                   "page", "confidence"]
    coverage = {
        f: sum(1 for c in all_chunks if c["metadata"].get(f) not in (None, ""))
        for f in META_FIELDS
    }

    # Token histogram (Moss target band is 200-500; usable band 50-500).
    bands = {"<50": 0, "50-199": 0, "200-500": 0, ">500": 0}
    for t in tok_sizes:
        if t < 50:      bands["<50"] += 1
        elif t < 200:   bands["50-199"] += 1
        elif t <= 500:  bands["200-500"] += 1
        else:           bands[">500"] += 1

    # Quality gate — the embedded text must carry NO markdown boilerplate.
    # This is what failed silently before: '**Mechanism of Action**<br>' was
    # leaking into chunk text and polluting the embeddings.
    dirty = [c["id"] for c in all_chunks
             if "**" in c["text"] or "<br>" in c["text"] or ".." in c["text"]]
    dup_ids = len(all_chunks) - len({c["id"] for c in all_chunks})

    print(f"\n{'=' * 64}")
    print("CHUNK STATS")
    print(f"{'=' * 64}")
    print(f"Total chunks         : {len(all_chunks)}")
    print(f"Unique drugs         : {len(drugs)}")
    print(f"By record_type       : {by_type}")
    print(f"By patient_type      : {by_pt}")
    print(f"Token sizes (est)    : min={min(tok_sizes)}  avg={sum(tok_sizes)//len(tok_sizes)}  max={max(tok_sizes)}")
    print(f"Token histogram      : {bands}")
    print(f"In 50-500 tok range  : {sum(1 for t in tok_sizes if 50 <= t <= 500)}/{len(all_chunks)}")
    print(f"Skipped tables       : {skipped}")
    print("\nMetadata coverage (non-empty / total):")
    for f in META_FIELDS:
        print(f"  {f:14}: {coverage[f]:3d}/{len(all_chunks)}")

    print(f"\n{'-' * 64}")
    print("QUALITY GATE")
    print(f"{'-' * 64}")
    print(f"  duplicate ids      : {dup_ids}")
    print(f"  markdown-leak rows : {len(dirty)}")
    if dirty:
        print("  FAIL — these chunk ids still contain **/<br>/.. boilerplate:")
        for cid in dirty[:10]:
            print(f"    - {cid}")
    else:
        print("  PASS — no markdown boilerplate in any embedded text")

    print(f"\nOutput               : {OUTPUT}")


if __name__ == "__main__":
    main()
