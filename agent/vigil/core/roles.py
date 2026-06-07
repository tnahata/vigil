"""Role-based administration authorization (EMT / AEMT / PARAMEDIC).

Every protocol drug page colors the three provider levels by who may administer
that drug:

    authorized      green   -- state regulation + local protocol
    conditional     yellow  -- LEMSA Medical Director-approved, usually a limited
                               scope spelled out in a Notes caveat
    not_authorized  red     -- prohibited for that role

Source of truth: the header-cell fill colors in the protocol PDF, extracted +
validated by moss-test/extract_role_auth.py. The states are keyed by PDF page
number, which equals the `page` metadata on each retrieved chunk, so a dose
joins to its authorization with no extra lookup.

PURE: stdlib only (re). The optional per-role caveat *text* (read from the parse)
is passed in by the caller -- this module never touches the filesystem, so
vigil.core stays import-clean. For the demo the provider role comes from the
user's auth profile (default PARAMEDIC), not a hands-free declaration.
"""
from __future__ import annotations

import re

ROLES = ("EMT", "AEMT", "PARAMEDIC")

AUTHORIZED = "authorized"
CONDITIONAL = "conditional"
NOT_AUTHORIZED = "not_authorized"
UNKNOWN = "unknown"

# page -> {role: state}. Extracted from sd_ems_p115.pdf header fills (validated
# 13/13 against the colors that survived into the parse). Regenerate with
# moss-test/extract_role_auth.py if the protocol PDF changes.
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

# Role mentions in a spoken query, most specific first so "advanced EMT" -> AEMT.
_ROLE_PATTERNS = [
    ("AEMT", re.compile(r"\b(?:aemt|a\.e\.m\.t|advanced\s+emt)\b", re.I)),
    ("PARAMEDIC", re.compile(r"\b(?:paramedics?|medics?)\b", re.I)),
    ("EMT", re.compile(r"\b(?:emt|emt-?b|e\.m\.t)\b", re.I)),
]


def extract_role_from_query(query: str) -> str | None:
    """Return 'EMT' | 'AEMT' | 'PARAMEDIC' if the speaker states their role,
    else None. (Demo uses the auth-profile role instead; kept for completeness.)"""
    for role, pat in _ROLE_PATTERNS:
        if pat.search(query):
            return role
    return None


def page_states(page: int | None) -> dict[str, str] | None:
    """The {role: state} row for a PDF page, or None if the page has no data."""
    if page is None:
        return None
    return _VERIFIED_PAGE_AUTH.get(page)


def authorized_roles(page: int | None) -> list[str]:
    """Roles that may administer the drug on this page (green or yellow)."""
    states = page_states(page) or {}
    return [r for r in ROLES if states.get(r) in (AUTHORIZED, CONDITIONAL)]


def decide(
    page: int | None, role: str, caveats: dict[str, str] | None = None
) -> tuple[str, str | None, list[str]]:
    """Return (state, caveat_or_None, authorized_roles) for one role on one drug.

    With no role-color data for the page, state is UNKNOWN (caller leaves the
    dose ungated). `caveats` is an optional {role: limitation-text} map the
    caller may supply from the parse; absent it, conditional roles get a generic
    note.
    """
    states = page_states(page)
    if not states:
        return (UNKNOWN, None, [])
    caveat = (caveats or {}).get(role)
    return (states.get(role, UNKNOWN), caveat, authorized_roles(page))


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
    """Build the role-gated line for TTS.

    SAFETY: the dose NUMBER is never altered -- on authorized roles this returns
    `dose_spoken` verbatim; on conditional it appends a non-numeric caveat after
    the verbatim dose; on not_authorized it withholds the number entirely.
    """
    short = _drug_short(drug)
    article = "an" if role in ("EMT", "AEMT") else "a"
    if state == NOT_AUTHORIZED:
        return (
            f"As {article} {_say_role(role)}, you are not authorized to administer "
            f"{short}. Seek {_join_roles(allowed)}."
        )
    if state == CONDITIONAL:
        note = caveat or "limited authorization -- confirm per LEMSA Medical Director."
        return f"{dose_spoken}. Note for {_say_role(role)}: {note}"
    if state == AUTHORIZED:
        return f"{dose_spoken}. Note for {_say_role(role)}: {caveat}" if caveat else dose_spoken
    return dose_spoken  # UNKNOWN -> ungated
