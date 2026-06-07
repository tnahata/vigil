"""Role-based administration authorization for Vigil.

Every protocol drug page colors the three provider levels — EMT / AEMT /
PARAMEDIC — by who may administer that drug:

    green   authorized by state regulation + local protocol
    yellow  conditional: authorized by the LEMSA Medical Director (Title 22, Div 9,
            Ch 3.1, §100066.02L) or an EMSA-approved LOSOPS — usually a limited
            scope spelled out in the Notes caveat
    red     NOT authorized

Source of truth: the header-cell fill colors in the protocol PDF
(unsiloed-test/sd_ems_p115.pdf). The parser only preserved those colors in the
HTML for 13 of 27 pages, so the per-page states below were extracted directly
from the PDF's vector fills by `extract_role_auth.py` and VALIDATED 13/13
against the pages where the inline-HTML color *was* present. Nothing here is
clinically inferred — it is transcribed from the document.

States are keyed by PDF page number, which equals the `page` metadata on each
retrieved Moss chunk, so authorization joins to a dose with no extra lookup.
Per-role scope limitations (the "EMT: ... auto-injector only" lines) are read
live from parsed_output.json when available.

See [[tier-1-population-routing]] for the retrieval side.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROLES = ("EMT", "AEMT", "PARAMEDIC")

AUTHORIZED = "authorized"
CONDITIONAL = "conditional"
NOT_AUTHORIZED = "not_authorized"
UNKNOWN = "unknown"

# page -> {role: state}. Extracted from sd_ems_p115.pdf (header fills) by
# extract_role_auth.py; validated against the 13 pages whose colors also survived
# into parsed_output.json's HTML (100% agreement). Regenerate with that script if
# the protocol PDF changes. Page 1 is the title index (no role row).
_VERIFIED_PAGE_AUTH: dict[int, dict[str, str]] = {
    2:  {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    3:  {"EMT": NOT_AUTHORIZED, "AEMT": AUTHORIZED,     "PARAMEDIC": AUTHORIZED},
    4:  {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    5:  {"EMT": NOT_AUTHORIZED, "AEMT": AUTHORIZED,     "PARAMEDIC": AUTHORIZED},
    6:  {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    7:  {"EMT": CONDITIONAL,    "AEMT": AUTHORIZED,     "PARAMEDIC": AUTHORIZED},
    8:  {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    9:  {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": CONDITIONAL},
    10: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    11: {"EMT": NOT_AUTHORIZED, "AEMT": AUTHORIZED,     "PARAMEDIC": AUTHORIZED},
    12: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    13: {"EMT": CONDITIONAL,    "AEMT": AUTHORIZED,     "PARAMEDIC": AUTHORIZED},
    14: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    15: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    16: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    17: {"EMT": NOT_AUTHORIZED, "AEMT": AUTHORIZED,     "PARAMEDIC": AUTHORIZED},
    18: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    19: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    20: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    21: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    22: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    23: {"EMT": CONDITIONAL,    "AEMT": AUTHORIZED,     "PARAMEDIC": AUTHORIZED},
    24: {"EMT": AUTHORIZED,     "AEMT": AUTHORIZED,     "PARAMEDIC": AUTHORIZED},
    25: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    26: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
    27: {"EMT": NOT_AUTHORIZED, "AEMT": NOT_AUTHORIZED, "PARAMEDIC": AUTHORIZED},
}

_TAG_RE = re.compile(r"<[^>]+>")
_LI_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.I | re.S)
_ROLE_NOTE_RE = re.compile(r"^\s*(EMT|AEMT|PARAMEDIC)\s*:\s*(.+)$", re.I)

# Role mentions in a spoken query, most specific first so "advanced EMT" -> AEMT.
_ROLE_PATTERNS = [
    ("AEMT", re.compile(r"\b(?:aemt|a\.e\.m\.t|advanced\s+emt)\b", re.I)),
    ("PARAMEDIC", re.compile(r"\b(?:paramedics?|medics?)\b", re.I)),
    ("EMT", re.compile(r"\b(?:emt|emt-?b|e\.m\.t)\b", re.I)),
]


def _strip(html_fragment: str) -> str:
    return _TAG_RE.sub("", html_fragment).replace("&amp;", "&").strip()


def _load_caveats(parsed_path: Path) -> dict[int, dict[str, str]]:
    """page -> {role: limitation note}, from role-prefixed Notes list items."""
    if not parsed_path.exists():
        return {}
    with parsed_path.open() as f:
        data = json.load(f)
    segs = [s for c in data.get("chunks", []) for s in c.get("segments", [])]
    caveats: dict[int, dict[str, str]] = {}
    for s in segs:
        html = s.get("html") or ""
        page = s.get("page_number")
        if page is None or "Notes" not in html:
            continue
        for frag in _LI_RE.findall(html):
            m = _ROLE_NOTE_RE.match(_strip(frag))
            if m:
                caveats.setdefault(page, {})[m.group(1).upper()] = m.group(2).strip()
    return caveats


def load_role_table(parsed_path: Path | None = None) -> dict[int, dict]:
    """page -> {"roles": {role: state}, "caveats": {role: text}}.

    States come from the validated baked map (full coverage); caveats are layered
    on from parsed_output.json when that file is present.
    """
    caveats = _load_caveats(parsed_path) if parsed_path else {}
    return {
        page: {"roles": dict(states), "caveats": caveats.get(page, {})}
        for page, states in _VERIFIED_PAGE_AUTH.items()
    }


def extract_role_from_query(query: str) -> str | None:
    """Return 'EMT' | 'AEMT' | 'PARAMEDIC' if the speaker states their role."""
    for role, pat in _ROLE_PATTERNS:
        if pat.search(query):
            return role
    return None


def authorized_roles(page_auth: dict) -> list[str]:
    """Roles that may administer this drug (green or yellow), EMT->PARAMEDIC order."""
    return [r for r in ROLES if page_auth["roles"].get(r) in (AUTHORIZED, CONDITIONAL)]


def decide(page_auth: dict, role: str) -> tuple[str, str | None, list[str]]:
    """Return (state, caveat_or_None, authorized_roles) for one role on one drug."""
    return (
        page_auth["roles"].get(role, UNKNOWN),
        page_auth["caveats"].get(role),
        authorized_roles(page_auth),
    )


def _say_role(role: str) -> str:
    return "paramedic" if role == "PARAMEDIC" else role


def _join_roles(roles: list[str]) -> str:
    pretty = [_say_role(r) for r in roles]
    if not pretty:
        return "an authorized provider"
    if len(pretty) == 1:
        return pretty[0]
    return " or ".join([", ".join(pretty[:-1]), pretty[-1]])


def _drug_short(drug: str) -> str:
    return drug.split("(")[0].strip().lower() or drug.lower()


def spoken_answer(
    drug: str,
    dose_spoken: str,
    role: str,
    state: str,
    caveat: str | None,
    allowed: list[str],
) -> str:
    """Build the role-gated line the agent would hand to TTS."""
    short = _drug_short(drug)
    article = "an" if role in ("EMT", "AEMT") else "a"
    if state == NOT_AUTHORIZED:
        return (
            f"As {article} {_say_role(role)}, you are not authorized to administer "
            f"{short}. Seek {_join_roles(allowed)}."
        )
    if state == CONDITIONAL:
        note = caveat or "limited authorization — confirm per LEMSA Medical Director."
        return f"{dose_spoken}. Note for {_say_role(role)}: {note}"
    if state == AUTHORIZED:
        # Green roles can still carry a scope note (e.g. EMT + nitro: assist only).
        return f"{dose_spoken}. Note for {_say_role(role)}: {caveat}" if caveat else dose_spoken
    return dose_spoken  # UNKNOWN -> ungated
