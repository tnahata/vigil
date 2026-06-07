"""Drug alias normalization -- the make-or-break detail for Tier 1.

Exact keyword retrieval whiffs on synonyms ("adrenaline" vs "epinephrine",
"epi", brand names). We map every spoken variant to one canonical name BEFORE
retrieval so a filtered exact lookup can hit.

NOTE: brand names are starter values and should be verified against the source
protocol set (teammate's ingestion branch) before the demo.
"""
from __future__ import annotations

import re

# canonical -> spoken variants (all lowercase)
_CANONICAL_TO_ALIASES: dict[str, list[str]] = {
    "epinephrine": ["adrenaline", "adrenalin", "epi", "epipen"],
    "naloxone": ["narcan", "evzio"],
    "dextrose": ["glucose", "d10", "d50", "d-10", "d-50", "d10w", "d50w"],
    "albuterol": ["salbutamol", "ventolin"],
    "amiodarone": ["cordarone", "pacerone"],
}

# alias (and canonical) -> canonical
ALIASES: dict[str, str] = {}
for _canon, _variants in _CANONICAL_TO_ALIASES.items():
    ALIASES[_canon] = _canon
    for _v in _variants:
        ALIASES[_v] = _canon

CANONICAL_DRUGS: set[str] = set(_CANONICAL_TO_ALIASES)

_WORD_RE = re.compile(r"[a-z0-9\-]+")

# STT often glues a drug name to a following intent word ("epi dose" -> "epidose",
# "epi drip" -> "epidrip"). These compounds whiff on whole-word alias + dose-intent
# matching, so a real query routes to UNKNOWN on phrasing, not retrieval. We split
# them back apart, but ONLY when BOTH halves are recognized tokens -- so "epidural"
# / "episode" (a drug-alias prefix + an UNknown suffix) are never touched.
_DOSE_SUFFIXES = ("dose", "dosage", "dosing", "drip", "bolus", "push")
# Longest aliases first so "epinephrine" wins over "epi" when both could match.
_ALIAS_ALT = "|".join(sorted(map(re.escape, ALIASES), key=len, reverse=True))
_GLUED_RE = re.compile(
    r"\b(" + _ALIAS_ALT + r")(" + "|".join(_DOSE_SUFFIXES) + r")\b",
    re.IGNORECASE,
)


def split_glued_terms(query: str) -> str:
    """Insert a space in glued <drug-alias><dose-word> compounds from STT.

    Safe by construction: only fires when the prefix is a known alias AND the
    suffix is a known dose-intent word, so non-drug words are left untouched.
    """
    if not query:
        return query
    return _GLUED_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}", query)


def normalize_drug(token: str | None) -> str | None:
    """Map a single drug token to its canonical name, or None if unknown."""
    if not token:
        return None
    return ALIASES.get(token.strip().lower())


def extract_drug(query: str) -> str | None:
    """Scan a free-text query for the first recognizable drug; canonical or None."""
    if not query:
        return None
    for tok in _WORD_RE.findall(query.lower()):
        canon = ALIASES.get(tok)
        if canon:
            return canon
    return None
