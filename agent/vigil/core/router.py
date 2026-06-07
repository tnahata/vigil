"""Route a query to Tier 1 (deterministic dose) or Tier 2 (soft synthesis).

Tier 2 phrasing (judgement: "what should I consider", "contraindicated given X")
wins first. Otherwise a known drug + dose intent -> Tier 1. Anything else ->
UNKNOWN (handled by the safe fallback).
"""
from __future__ import annotations

import re

from .aliases import extract_drug
from .models import Tier

# Judgement / synthesis questions -> Tier 2.
_TIER2_PATTERNS = [
    r"what should i consider",
    r"contraindicat",          # contraindicated / contraindication
    r"in what order",
    r"what.*\bsequence\b",
    r"should i give",
    r"can i give",
    r"is it safe",
    r"interact",
]
_TIER2_RE = re.compile("|".join(_TIER2_PATTERNS), re.IGNORECASE)

# Flat dose-lookup intent -> Tier 1.
_DOSE_PATTERNS = [
    r"\bdose\b", r"\bdosage\b", r"how much", r"how many",
    r"\bmg\b", r"\bmcg\b", r"\bml\b", r"\bgrams?\b",
    r"\bgive\b", r"\bpush\b", r"\badminister\b",
]
_DOSE_RE = re.compile("|".join(_DOSE_PATTERNS), re.IGNORECASE)


def classify(query: str) -> Tier:
    if not query:
        return Tier.UNKNOWN
    if _TIER2_RE.search(query):
        return Tier.TIER2_SYNTHESIS
    has_drug = extract_drug(query) is not None
    if has_drug and _DOSE_RE.search(query):
        return Tier.TIER1_DOSE
    # A bare known drug name (no explicit dose word) is still a dose lookup.
    if has_drug:
        return Tier.TIER1_DOSE
    return Tier.UNKNOWN
