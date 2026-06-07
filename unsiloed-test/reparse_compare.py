"""Re-parse the protocol PDF with Unsiloed into a NEW file and diff it against the
existing parsed_output.json — to decide whether a fresh parse is "same content +
the missing header colors" (safe to adopt) or has drifted enough to be risky.

Why: Unsiloed dropped the EMT/AEMT/PARAMEDIC header `background-color` on 14 of 27
pages. Re-parsing might recover them, but it's a non-deterministic vision API, so
we must confirm it didn't also churn the text/structure that chunk.py depends on.

Usage:
    export UNSILOED_API_KEY=...           # credit-consuming; only for a fresh parse
    python reparse_compare.py             # parse -> parsed_output_v2.json, then diff
    python reparse_compare.py --compare-only   # just diff existing v1 vs v2

Outputs:
    parsed_output_v2.json   the fresh parse (never overwrites the cached v1)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from parse_pdf import LOCAL_PDF, get_api_key, poll, submit_job

HERE = Path(__file__).parent.resolve()
V1 = HERE / "parsed_output.json"
V2 = HERE / "parsed_output_v2.json"

_STYLE = re.compile(r'\s*style="[^"]*"')
_WS = re.compile(r"\s+")
_BG = re.compile(r"background-color:\s*([^;\"]+)", re.I)
_TH = re.compile(r"<th\b[^>]*>\s*(EMT|AEMT|PARAMEDIC)\b", re.I)


def _segments(data: dict) -> list[dict]:
    return [s for c in data.get("chunks", []) for s in c.get("segments", [])]


def _norm_text(s: str | None) -> str:
    return _WS.sub(" ", (s or "")).strip()


def _strip_style(html: str | None) -> str:
    """HTML with all style="" attributes removed, whitespace-collapsed."""
    return _WS.sub(" ", _STYLE.sub("", html or "")).strip()


def _pages_with_header_colors(data: dict) -> set[int]:
    pages = set()
    for s in _segments(data):
        html = s.get("html") or ""
        if "background-color" in html and _TH.search(html):
            pages.add(s.get("page_number"))
    return pages


def reparse() -> None:
    if V2.exists():
        print(f"[skip] {V2.name} already exists — using it. Delete it to force a re-parse.")
        return
    key = get_api_key()
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else LOCAL_PDF
    if not pdf.exists():
        raise SystemExit(f"PDF not found: {pdf}")
    print(f"Re-parsing {pdf.name} (fresh API call — consumes credits)...")
    data = poll(submit_job(pdf, key), key)
    V2.write_text(json.dumps(data, indent=2))
    print(f"Saved fresh parse -> {V2.name}")


def compare() -> None:
    if not V1.exists() or not V2.exists():
        raise SystemExit(f"Need both {V1.name} and {V2.name} to compare.")
    d1, d2 = json.loads(V1.read_text()), json.loads(V2.read_text())
    s1, s2 = _segments(d1), _segments(d2)

    print("\n" + "=" * 64)
    print("TOP-LEVEL")
    print("=" * 64)
    for k in ("status", "page_count", "total_chunks"):
        print(f"  {k:14} v1={d1.get(k)!s:8} v2={d2.get(k)!s}")
    print(f"  {'segments':14} v1={len(s1):<8} v2={len(s2)}")

    # Header-color coverage — the whole point of re-parsing.
    c1, c2 = _pages_with_header_colors(d1), _pages_with_header_colors(d2)
    print("\n" + "=" * 64)
    print("HEADER-COLOR COVERAGE (the fix we're after)")
    print("=" * 64)
    print(f"  pages with role colors: v1={len(c1)}  v2={len(c2)}")
    print(f"  newly colored in v2   : {sorted(c2 - c1)}")
    print(f"  lost in v2            : {sorted(c1 - c2)}")

    # Content drift — aligned by (page, segment_type, order).
    print("\n" + "=" * 64)
    print("CONTENT DRIFT (does the text chunk.py reads change?)")
    print("=" * 64)
    if len(s1) != len(s2):
        print(f"  ⚠ segment COUNT differs ({len(s1)} vs {len(s2)}) — alignment is approximate")
    n = min(len(s1), len(s2))
    same_text = style_only = text_diff = type_diff = 0
    diffs = []
    for a, b in zip(s1, s2):
        if a.get("segment_type") != b.get("segment_type") or a.get("page_number") != b.get("page_number"):
            type_diff += 1
            continue
        ta, tb = _norm_text(a.get("markdown")), _norm_text(b.get("markdown"))
        ca, cb = _norm_text(a.get("content")), _norm_text(b.get("content"))
        if ta == tb and ca == cb:
            same_text += 1
            if _strip_style(a.get("html")) != _strip_style(b.get("html")):
                style_only += 1
        else:
            text_diff += 1
            if len(diffs) < 8:
                diffs.append((a.get("page_number"), a.get("segment_type"), ta[:70], tb[:70]))

    print(f"  identical text (md+content) : {same_text}/{n}")
    print(f"    └ of those, html differs only in style/colors: {style_only}")
    print(f"  text DIFFERS                : {text_diff}/{n}")
    print(f"  type/page misaligned        : {type_diff}/{n}")
    for p, t, va, vb in diffs:
        print(f"\n  ~ p{p} [{t}]\n      v1: {va!r}\n      v2: {vb!r}")

    print("\n" + "=" * 64)
    print("VERDICT")
    print("=" * 64)
    if text_diff == 0 and type_diff == 0 and len(s1) == len(s2):
        print("  ✅ v2 is text-identical to v1. Difference is purely styling/colors.")
        print(f"     Recovered colors on pages: {sorted(c2 - c1) or 'none'}")
        print("     -> Safe to adopt v2 and switch roles.py to pure-HTML color parsing.")
    else:
        print(f"  ⚠ v2 has {text_diff} text diffs + {type_diff} structural diffs.")
        print("     -> Review the samples above; weigh re-chunk risk vs. the recovered colors.")


def main() -> None:
    if "--compare-only" not in sys.argv:
        reparse()
    compare()


if __name__ == "__main__":
    main()
