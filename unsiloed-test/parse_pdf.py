"""
Unsiloed PDF parse POC — Stage 1 of the Vigil EMT voice-assistant ingestion pipeline.

Goal: verify that Unsiloed preserves dosage table row/column structure well enough to
map to the Moss document schema (drug / indication / patient_type / route / dose).

CACHE-FIRST: if parsed_output.json already contains a Succeeded result, the API is
never called and no page credits are consumed.

Usage:
    python parse_pdf.py [path-to-pdf]

Env:
    UNSILOED_API_KEY  — required only when running a fresh parse

Outputs (all written to the same directory as this script):
    parsed_output.json    raw API response (written on first run; reused thereafter)
    tables_inspection.md  human-readable table analysis for schema-mapping review
"""

import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HERE = Path(__file__).parent.resolve()

BASE_URL = "https://prod.visionapi.unsiloed.ai"
DEFAULT_PDF_URL = (
    "https://www.sandiegocounty.gov/content/dam/sdc/ems/Policies_Protocols"
    "/2025/100/CoSD%20EMS%20P-115%202025.pdf"
)
OUTPUT_JSON = HERE / "parsed_output.json"
TABLES_MD   = HERE / "tables_inspection.md"
LOCAL_PDF   = HERE / "sd_ems_p115.pdf"

POLL_INTERVAL = 5    # seconds
MAX_WAIT      = 600  # 10 minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    key = os.environ.get("UNSILOED_API_KEY", "").strip()
    if not key:
        raise EnvironmentError(
            "UNSILOED_API_KEY is not set.\n"
            "  export UNSILOED_API_KEY=your_key_here"
        )
    return key


def load_cached() -> dict | None:
    if not OUTPUT_JSON.exists():
        return None
    with open(OUTPUT_JSON) as f:
        data = json.load(f)
    if data.get("status") == "Succeeded":
        print(f"[cache] Reusing existing {OUTPUT_JSON.name} — no API call made.")
        return data
    return None


def download_pdf(url: str, dest: Path) -> None:
    print(f"Downloading PDF...\n  {url}")
    urllib.request.urlretrieve(url, dest)
    print(f"  Saved: {dest.name} ({dest.stat().st_size / 1024:.1f} KB)")


def submit_job(pdf_path: Path, api_key: str) -> str:
    print(f"\nSubmitting {pdf_path.name} to Unsiloed...")
    with open(pdf_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/parse",
            headers={"api-key": api_key},
            files={"file": (pdf_path.name, f, "application/pdf")},
            data={
                "use_high_resolution": "true",
                "layout_analysis": "smart_layout_detection",
                "merge_tables": "false",
            },
            timeout=60,
        )
    resp.raise_for_status()
    body = resp.json()
    job_id = body["job_id"]
    print(f"  Job ID: {job_id}")
    print(f"  Credits used: {body.get('credit_used', '?')}  |  "
          f"Quota remaining: {body.get('quota_remaining', '?')}")
    return job_id


def poll(job_id: str, api_key: str) -> dict:
    print(f"\nPolling (every {POLL_INTERVAL}s)...")
    elapsed = 0
    while elapsed < MAX_WAIT:
        resp = requests.get(
            f"{BASE_URL}/parse/{job_id}",
            headers={"api-key": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        status = result.get("status", "Unknown")
        print(f"  [{elapsed:>4}s] {status}")
        if status == "Succeeded":
            return result
        if status in ("Failed", "Cancelled"):
            raise RuntimeError(f"Job {status}: {result.get('message', '')}")
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    raise TimeoutError(f"Job did not finish within {MAX_WAIT}s")


# ---------------------------------------------------------------------------
# Inspection logic (EMT-pipeline focused)
# ---------------------------------------------------------------------------

# Rows in each drug table that contain dosage data
_DOSE_ROWS = re.compile(
    r"\*\*(Adult Dose|Pediatric Dose|Indications|Contraindications)\*\*",
    re.IGNORECASE,
)

def parse_drug_table(seg: dict) -> dict:
    """Extract structured fields from one drug Table segment."""
    md = seg.get("markdown", "")
    drug: dict = {
        "page": seg["page_number"],
        "confidence": round(seg["confidence"], 2),
        "drug_name": None,
        "indication": None,
        "adult_dose": None,
        "pediatric_dose": None,
        "route": None,
        "raw_markdown": md,
    }

    # Drug name comes from the SectionHeader on the same page; we can approximate
    # it from the Classification row or fall back to the SectionHeader in the chunk.
    lines = md.splitlines()

    for line in lines:
        clean = line.strip("| ").strip()
        if "Adult Dose" in clean:
            m = re.search(r"Adult Dose\*\*\s*<br>(.*)", clean)
            if m:
                drug["adult_dose"] = m.group(1).strip()
        if "Pediatric Dose" in clean:
            m = re.search(r"Pediatric Dose\*\*\s*<br>(.*)", clean)
            if m:
                drug["pediatric_dose"] = m.group(1).strip()
        if "Indications" in clean and not drug["indication"]:
            m = re.search(r"Indications\*\*\s*<br>(.*?)(?:Protocols:|$)", clean)
            if m:
                drug["indication"] = m.group(1).strip()

    # Extract route tokens from adult dose text
    if drug["adult_dose"]:
        routes_found = re.findall(r"\b(IV|IO|IM|SQ|IN|PO|SL|ET|PR|NEB|MDI)\b",
                                  drug["adult_dose"])
        drug["route"] = ", ".join(sorted(set(routes_found))) or None

    return drug


def all_segments(data: dict) -> list[dict]:
    return [s for c in data["chunks"] for s in c.get("segments", [])]


def inspect(data: dict) -> None:
    segs = all_segments(data)
    type_counts = Counter(s["segment_type"] for s in segs)
    tables = [s for s in segs if s["segment_type"] == "Table"]
    headers = [s for s in segs if s["segment_type"] == "SectionHeader"]

    # Map page → drug name from SectionHeaders
    page_to_drug: dict[int, str] = {}
    for h in headers:
        name = (h.get("markdown") or h.get("content") or "").strip()
        if name and len(name) < 80:
            page_to_drug[h["page_number"]] = name

    # Parse every table
    drug_tables = []
    for seg in tables:
        parsed = parse_drug_table(seg)
        parsed["drug_name"] = page_to_drug.get(seg["page_number"])
        drug_tables.append(parsed)

    # ---- console summary ------------------------------------------------
    print("\n" + "=" * 65)
    print(f"PARSE SUMMARY  |  {data.get('page_count')} pages  |  "
          f"{data.get('credit_used')} credits used")
    print("=" * 65)
    print(f"{'Segment type':<22} {'Count':>6}")
    print("-" * 32)
    for t, n in type_counts.most_common():
        print(f"{t:<22} {n:>6}")
    print(f"\nTotal chunks:  {data.get('total_chunks')}")

    print("\n" + "=" * 65)
    print("TABLE STRUCTURE VERDICT")
    print("=" * 65)
    dose_tables = [dt for dt in drug_tables if dt["adult_dose"]]
    print(f"Drug Table segments parsed: {len(drug_tables)}")
    print(f"  → contain dosage data:    {len(dose_tables)}")
    print(f"  → no dosage data:         {len(drug_tables) - len(dose_tables)}  "
          f"(likely cover/legend pages)")

    print("\nSample drug entries (first 3 with dosage):")
    for dt in dose_tables[:3]:
        print(f"\n  Drug   : {dt['drug_name'] or '(name from SectionHeader)'}")
        print(f"  Page   : {dt['page']}")
        print(f"  Conf   : {dt['confidence']}")
        print(f"  Adult  : {(dt['adult_dose'] or '')[:120]}")
        print(f"  Peds   : {(dt['pediatric_dose'] or '')[:100]}")
        print(f"  Route  : {dt['route']}")
        print(f"  Indicat: {(dt['indication'] or '')[:80]}")

    print("\n" + "=" * 65)
    print("SCHEMA MAPPING ASSESSMENT")
    print("=" * 65)
    populated = {
        "metadata.drug":         sum(1 for d in dose_tables if d["drug_name"]),
        "metadata.indication":   sum(1 for d in dose_tables if d["indication"]),
        "metadata.route":        sum(1 for d in dose_tables if d["route"]),
        "metadata.value_machine (adult)":  len(dose_tables),
        "metadata.patient_type (peds)": sum(1 for d in dose_tables if d["pediatric_dose"]),
    }
    for field, count in populated.items():
        pct = 100 * count / len(dose_tables) if dose_tables else 0
        print(f"  {field:<38} {count:>3}/{len(dose_tables)}  ({pct:.0f}%)")

    print(f"\nFull output : {OUTPUT_JSON}")
    print(f"Tables MD   : {TABLES_MD}")

    # ---- write tables inspection markdown --------------------------------
    with open(TABLES_MD, "w") as f:
        f.write("# Unsiloed Table Inspection — CoSD EMS P-115 2025\n\n")
        f.write(f"Pages: {data.get('page_count')}  |  "
                f"Credits used: {data.get('credit_used')}  |  "
                f"Drug tables with dosage: {len(dose_tables)}\n\n")
        f.write("---\n\n")
        for dt in drug_tables:
            drug = dt["drug_name"] or f"Page {dt['page']}"
            f.write(f"## {drug}  (page {dt['page']}, conf={dt['confidence']})\n\n")
            f.write(f"**Adult dose:** {dt['adult_dose'] or '_not found_'}\n\n")
            f.write(f"**Pediatric dose:** {dt['pediatric_dose'] or '_not found_'}\n\n")
            f.write(f"**Route(s):** {dt['route'] or '_not extracted_'}\n\n")
            f.write(f"**Indication:** {dt['indication'] or '_not found_'}\n\n")
            f.write("<details><summary>Raw markdown</summary>\n\n")
            f.write("```\n")
            f.write(dt["raw_markdown"][:3000])
            if len(dt["raw_markdown"]) > 3000:
                f.write("\n... (truncated)")
            f.write("\n```\n\n</details>\n\n---\n\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Try cache first — no credits consumed if hit
    data = load_cached()

    if data is None:
        api_key = get_api_key()

        if len(sys.argv) > 1:
            pdf_path = Path(sys.argv[1])
            if not pdf_path.is_file():
                raise FileNotFoundError(f"Not found: {pdf_path}")
        else:
            pdf_path = LOCAL_PDF
            if not pdf_path.exists():
                download_pdf(DEFAULT_PDF_URL, pdf_path)
            else:
                print(f"Reusing local PDF: {pdf_path.name}")

        job_id = submit_job(pdf_path, api_key)
        data = poll(job_id, api_key)

        with open(OUTPUT_JSON, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nSaved raw output → {OUTPUT_JSON}")

    inspect(data)


if __name__ == "__main__":
    main()
