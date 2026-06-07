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
