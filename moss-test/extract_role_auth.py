"""Extract per-role administration authorization from the protocol PDF.

The parser only preserved the EMT/AEMT/PARAMEDIC header colors in HTML for ~half
the pages, so we read them straight from the PDF's vector fills: for each role
word in the header band, find the smallest filled rectangle containing it and
classify its color (green=authorized, yellow=conditional, red=not authorized).

This is the generator behind roles._VERIFIED_PAGE_AUTH. It is a one-time/offline
tool (needs `pymupdf` and the local PDF, which is gitignored); the runtime uses
the baked constant and does NOT import this. Re-run if the protocol PDF changes:

    python3 extract_role_auth.py [path/to/protocol.pdf]

It prints both a validation line (agreement with the colors that DID survive into
parsed_output.json) and a paste-ready dict literal for roles.py.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PDF = BASE_DIR.parent / "unsiloed-test" / "sd_ems_p115.pdf"
PARSED_PATH = BASE_DIR.parent / "unsiloed-test" / "parsed_output.json"
ROLES = ("EMT", "AEMT", "PARAMEDIC")


def classify(rgb: tuple[float, float, float]) -> str | None:
    r, g, b = (int(c * 255) for c in rgb)
    if r > 200 and g > 200 and b < 160:
        return "conditional"        # yellow
    if g > 150 and g >= r:
        return "authorized"         # green
    if r > 150 and g < 140:
        return "not_authorized"     # red
    return None


def extract(pdf_path: Path) -> dict[int, dict[str, str]]:
    doc = fitz.open(pdf_path)
    out: dict[int, dict[str, str]] = {}
    for pno in range(doc.page_count):
        page = doc[pno]
        band = page.rect.height * 0.22  # header sits in the top fifth
        fills = [d for d in page.get_drawings() if d.get("fill")]
        found: dict[str, str] = {}
        for x0, y0, x1, y1, txt, *_ in page.get_text("words"):
            if txt not in ROLES or y0 >= band or txt in found:
                continue
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            best = None
            for d in fills:
                r = d["rect"]
                if r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1:
                    area = (r.x1 - r.x0) * (r.y1 - r.y0)
                    if best is None or area < best[1]:
                        best = (d, area)
            if best:
                state = classify(best[0]["fill"])
                if state:
                    found[txt] = state
        if len(found) == len(ROLES):
            out[pno + 1] = {r: found[r] for r in ROLES}
    return out


def _html_truth() -> dict[int, dict[str, str]]:
    """The colors that survived into parsed_output.json HTML, for validation."""
    if not PARSED_PATH.exists():
        return {}
    data = json.loads(PARSED_PATH.read_text())
    segs = [s for c in data.get("chunks", []) for s in c.get("segments", [])]
    th = re.compile(r'<th\b[^>]*\bstyle="([^"]*)"[^>]*>\s*(EMT|AEMT|PARAMEDIC)\b', re.I)
    bg = re.compile(r"background-color:\s*([^;\"]+)", re.I)
    green = {"lightgreen", "green", "#90ee90", "#92d050"}
    yellow = {"yellow", "#ffff00"}
    red = {"red", "#ff0000"}
    truth: dict[int, dict[str, str]] = {}
    for s in segs:
        html = s.get("html") or ""
        page = s.get("page_number")
        if page is None or "background-color" not in html:
            continue
        for style, role in th.findall(html):
            m = bg.search(style)
            if not m:
                continue
            c = m.group(1).strip().lower()
            state = ("authorized" if c in green else "conditional" if c in yellow
                     else "not_authorized" if c in red else None)
            if state:
                truth.setdefault(page, {})[role.upper()] = state
    return truth


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")
    table = extract(pdf_path)

    truth = _html_truth()
    checked = agree = 0
    for page, roles in truth.items():
        for role, state in roles.items():
            checked += 1
            agree += int(table.get(page, {}).get(role) == state)
    print(f"# validation vs parsed_output HTML colors: {agree}/{checked} agree "
          f"across {len(truth)} pages")
    print(f"# pages covered: {len(table)} of {fitz.open(pdf_path).page_count}\n")

    print("_VERIFIED_PAGE_AUTH = {")
    for page in sorted(table):
        r = table[page]
        print(f'    {page}: {{"EMT": "{r["EMT"]}", "AEMT": "{r["AEMT"]}", '
              f'"PARAMEDIC": "{r["PARAMEDIC"]}"}},')
    print("}")


if __name__ == "__main__":
    main()
