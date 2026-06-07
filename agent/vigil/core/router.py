"""Route a query to Tier 1 (deterministic dose) or Tier 2 (soft synthesis).

Tier 2 phrasing (judgement: "what should I consider", "contraindicated given X")
wins first. Otherwise a known drug + dose intent -> Tier 1. Anything else ->
UNKNOWN (handled by the safe fallback).
"""
from __future__ import annotations

import re

from .aliases import extract_drug
from .models import Tier

# Judgement / synthesis questions -> Tier 2. Broad on SYNTHESIS wording (so
# "considerations", "precautions", "side effects", "should I use X if..." land on
# Tier 2 instead of a pointless Tier-1 dose clarification). NOTE: an explicit dose
# NOUN (below) outranks all of these, so a dose question that merely contains
# "should I give" ("what DOSAGE should I give") stays on the deterministic path.
_TIER2_PATTERNS = [
    r"\bconsider",                       # "what should I consider", "considerations"
    r"contraindicat",                    # contraindicated / contraindication
    r"in what order",
    r"what.*\bsequence\b",
    r"should i (give|use|administer|push|start)",   # judgment: "should I use X if..."
    r"can i (give|use|administer)",
    r"is it safe",
    r"interact",
    r"precaution",
    r"\bwarn",                           # warning / warnings
    r"side.?effects?",
    r"adverse",
    r"\brisks?\b",
    r"what should i know",
    r"tell me about",
]
_TIER2_RE = re.compile("|".join(_TIER2_PATTERNS), re.IGNORECASE)

# Explicit dose-LOOKUP nouns: an unambiguous "tell me the number" request. These
# OUTRANK Tier-2 cues (checked first in classify), so "what dosage of atropine
# should I give" stays Tier-1 even though it contains the "should I give" judgment
# phrase -- the deterministic dose path is never diverted to the LLM by phrasing.
_DOSE_NOUN_PATTERNS = [
    r"\bdoses?\b", r"\bdosages?\b", r"how much", r"how many",
    r"\bmg\b", r"\bmcg\b", r"\bml\b", r"\bgrams?\b",
]
_DOSE_NOUN_RE = re.compile("|".join(_DOSE_NOUN_PATTERNS), re.IGNORECASE)

# Dose VERBS ("give/push/administer X") are weaker intent -- imperative dosing --
# and do NOT outrank a judgment question ("SHOULD I give X"). Combined with the
# nouns they form the full dose-intent signal used by has_intent().
_DOSE_VERB_PATTERNS = [r"\bgive\b", r"\bpush\b", r"\badminister\b"]
_DOSE_RE = re.compile("|".join(_DOSE_NOUN_PATTERNS + _DOSE_VERB_PATTERNS), re.IGNORECASE)


def has_intent(query: str) -> bool:
    """True iff the query expresses an ASK -- dose-lookup ("how much", "dose")
    or synthesis ("what should I consider", "contraindicated") -- regardless of
    whether a known drug is present.

    This is the "the medic actually finished asking something" signal. The wake
    state machine uses it to tell a complete-but-unknown query ("how much
    rocuronium" -> safe fallback) apart from a half-formed fragment ("vigil",
    "vigil what" -> keep listening, don't answer "Not in protocol" prematurely).
    Reuses the same two regexes classify() routes on -- no new vocabulary.
    """
    if not query:
        return False
    return bool(_TIER2_RE.search(query) or _DOSE_RE.search(query))


def classify(query: str) -> Tier:
    if not query:
        return Tier.UNKNOWN
    has_drug = extract_drug(query) is not None
    # 1. Explicit dose lookup ("dose", "how much", "10 mg") + a drug wins outright.
    #    The deterministic dose path is NEVER diverted to the LLM even when the
    #    phrasing also carries a judgment cue ("what DOSAGE should I give").
    if has_drug and _DOSE_NOUN_RE.search(query):
        return Tier.TIER1_DOSE
    # 2. Judgment / synthesis framing -> Tier 2 ("should I use X if...", "is it
    #    contraindicated", "what should I consider").
    if _TIER2_RE.search(query):
        return Tier.TIER2_SYNTHESIS
    # 3. A drug with a dose verb ("give/push epi") or a bare drug name is a dose
    #    lookup.
    if has_drug:
        return Tier.TIER1_DOSE
    return Tier.UNKNOWN
