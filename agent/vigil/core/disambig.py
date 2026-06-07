"""One-shot Tier-1 indication disambiguation. Pure: stdlib only.

16 (drug, population) pairs in the protocol map to MORE THAN ONE dose, separated
only by indication (atropine adult: unstable bradycardia -> 1 mg vs symptomatic
organophosphate poisoning -> 2 mg). At top_k>1 the retriever returns all of them;
this module decides whether the query already pins one down, and if not, builds a
single clarifying question naming the indications (never a dose number).

Flow:
  Turn 1: choose_or_clarify(query, candidates)
            -> (Doc, None)            speak that dose
            -> (None, Clarification)  speak the question, remember candidates
            -> (None, None)           nothing speakable -> caller safe-falls-back
  Turn 2: resolve_reply(reply, clarification)
            -> Doc | None             pick by indication, else safe fallback
          (called exactly once -- never re-clarifies)
"""
from __future__ import annotations

import re

from .models import Clarification, Doc

_WORD_RE = re.compile(r"[a-z0-9]+")

# Words that carry no indication signal -- stripped before overlap scoring so a
# shared "for"/"adult" can't fake a match.
_STOP = frozenset({
    "a", "an", "the", "for", "of", "and", "or", "with", "in", "to", "is", "it",
    "this", "that", "my", "his", "her", "patient", "give", "giving", "push",
    "how", "much", "many", "what", "whats", "dose", "dosage", "mg", "mcg", "ml",
    "adult", "adults", "pediatric", "peds", "child", "children", "kid", "kids",
    "infant", "baby", "vigil", "i", "im", "we", "he", "she", "they",
})


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD_RE.findall((text or "").lower()) if t not in _STOP}


def _score(query_tokens: set[str], doc: Doc) -> int:
    """How strongly the query points at this candidate's indication."""
    return len(query_tokens & _tokens(doc.indication))


def _drug_short(drug: str) -> str:
    return drug.split("(")[0].strip().lower() or drug.lower()


def _question(drug: str, candidates: "list[Doc]") -> str:
    """A spoken clarifying question listing the distinct indications -- NO dose
    numbers (we only ever read `indication`, never value_spoken/value_machine)."""
    seen: list[str] = []
    for c in candidates:
        ind = (c.indication or "").strip()
        if ind and ind.lower() not in {s.lower() for s in seen}:
            seen.append(ind)
    if len(seen) >= 2:
        opts = ", ".join(seen[:-1]) + f", or {seen[-1]}"
    else:
        opts = seen[0] if seen else "which indication"
    return f"For {_drug_short(drug)}, is this for {opts}?"


def _best(scored: "list[tuple[int, Doc]]") -> Doc | None:
    """The single highest-scoring candidate, or None on a zero/tied top score."""
    if not scored:
        return None
    top = max(s for s, _ in scored)
    if top <= 0:
        return None
    leaders = [d for s, d in scored if s == top]
    return leaders[0] if len(leaders) == 1 else None


def choose_or_clarify(
    query: str, candidates: "list[Doc]"
) -> "tuple[Doc | None, Clarification | None]":
    """Turn 1: resolve directly, ask once, or signal nothing-speakable."""
    speakable = [c for c in candidates if (c.spoken_form or "").strip()]
    if not speakable:
        return (None, None)
    if len(speakable) == 1:
        return (speakable[0], None)
    # If every candidate speaks the SAME dose, the indication split is moot --
    # any pick is correct (e.g. calcium chloride adult is "one gram" for all
    # four indications). Speak it; don't ask a pointless question.
    if len({c.spoken_form.strip() for c in speakable}) == 1:
        return (speakable[0], None)

    q = _tokens(query)
    winner = _best([(_score(q, c), c) for c in speakable])
    if winner is not None:
        return (winner, None)

    drug = speakable[0].drug
    population = speakable[0].population
    clar = Clarification(
        drug=drug,
        population=population,
        question=_question(drug, speakable),
        candidates=tuple(speakable),
    )
    return (None, clar)


def resolve_reply(reply: str, clarification: Clarification) -> Doc | None:
    """Turn 2: pick the candidate whose indication best matches the reply.

    Returns None if the reply matches nothing (or ties) -> caller safe-falls-back.
    Called once; the agent never asks a second question.
    """
    r = _tokens(reply)
    return _best([(_score(r, c), c) for c in clarification.candidates])
