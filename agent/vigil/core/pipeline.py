"""The orchestrator: transcript string -> Answer (or None).

Pure and synchronous. Dependency-injected retrieval (RetrievalIndex) and, for
Tier 2, a Synthesizer. Imports nothing external -- no livekit, no LLM, no Moss.

Tier 1 (dose): the number is copied verbatim from retrieval; never computed,
generated, or model-produced. When a (drug, population) has >1 dose separated
only by indication and the query doesn't pick one, the agent asks ONE clarifying
question (see disambig) instead of guessing. The chosen dose is then role-gated
(see roles) for the provider's authorization level.

Tier 2 (synthesis): an LLM answers, but constrained to retrieved chunks, with PII
redacted from the query and a number-grounding guard that discards any answer
introducing a number absent from the chunks. Any failure on either tier degrades
to the safe fallback -- the agent never crashes and never guesses a dose.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Callable, Optional

from . import aliases, disambig, errors, grounding, redact, roles, router, wake
from .models import Answer, Clarification, Doc, StageTiming, Tier
from .trace import StageTimer
from ..ports.retrieval import QueryResult, RetrievalIndex
from ..ports.synthesizer import Synthesizer

DEFAULT_ROLE = "PARAMEDIC"

# Word-boundary matched (so "kid" can't match inside "kidney" and an explicit
# "adult" is detected positively rather than assumed). Default population is adult.
_PEDS_RE = re.compile(
    r"\b(?:peds|pediatric|pediatrics|paediatric|paediatrics|child|children|kid|kids|"
    r"infant|infants|baby|babies|newborn|neonate|neonatal|toddler)\b",
    re.IGNORECASE,
)
_ADULT_RE = re.compile(r"\b(?:adult|adults|elderly|geriatric)\b", re.IGNORECASE)


def _detect_population(query: str) -> str:
    peds = _PEDS_RE.search(query) is not None
    adult = _ADULT_RE.search(query) is not None
    if peds and not adult:
        return "pediatric"
    return "adult"  # adult terms, neither, or ambiguous -> protocol default


def _page_of(doc: Doc) -> Optional[int]:
    try:
        return int(str(doc.metadata.get("page", "")).strip())
    except (TypeError, ValueError):
        return None


def _build_dose_answer(
    doc: Doc,
    timings: list[StageTiming],
    *,
    role: str = DEFAULT_ROLE,
    caveats: Optional[dict] = None,
) -> Answer:
    # SAFETY INVARIANT: the dose NUMBER is copied verbatim from the doc. Role
    # gating only wraps it (authorized -> unchanged; conditional -> + caveat;
    # not_authorized -> withholds the number, never invents one).
    state, caveat, allowed = roles.decide(_page_of(doc), role, caveats)
    spoken = roles.spoken_answer(doc.drug, doc.spoken_form, role, state, caveat, allowed)
    withheld = state == roles.NOT_AUTHORIZED
    card = {
        "found": True,
        "tier": Tier.TIER1_DOSE.value,
        "drug": doc.drug,
        "population": doc.population,
        "indication": doc.indication,
        "dose": None if withheld else doc.dose_value,
        "citation": doc.protocol_id,
        "role": role,
        "authorization": state,
    }
    if withheld:
        card["withheld"] = True
        card["authorized_roles"] = allowed
    return Answer(
        tier=Tier.TIER1_DOSE,
        spoken_form=spoken,
        card=card,
        citation=doc.protocol_id,
        doc_id=doc.doc_id,
        found=True,
        timings=timings,
    )


def _build_clarify_answer(clar: Clarification, timings: list[StageTiming]) -> Answer:
    card = {
        "found": False,
        "tier": "tier1_clarify",
        "drug": clar.drug,
        "population": clar.population,
        "question": clar.question,
        "options": [c.indication for c in clar.candidates],
    }
    return Answer(
        tier=Tier.TIER1_DOSE,
        spoken_form=clar.question,
        card=card,
        citation=None,
        doc_id=None,
        found=False,
        timings=timings,
        clarification=clar,
    )


def handle_transcript(
    transcript: str,
    *,
    index: RetrievalIndex,
    synthesizer: Optional[Synthesizer] = None,
    clock: Callable[[], float] = time.perf_counter,
    logger: Optional[logging.Logger] = None,
    tier2_alpha: float = 0.6,
    tier2_top_k: int = 4,
    provider_role: str = DEFAULT_ROLE,
    caveats: Optional[dict] = None,
) -> Optional[Answer]:
    """Returns None if no wake word (reactive only: the agent stays silent)."""
    log = logger or logging.getLogger("vigil.pipeline")
    timings: list[StageTiming] = []

    with StageTimer("wake", log, clock, timings) as st:
        triggered = wake.detect_wake(transcript)
        st.note(triggered=triggered)
    if not triggered:
        return None

    # Repair STT word-gluing ("epidose" -> "epi dose") before routing so a real
    # query isn't lost to UNKNOWN on phrasing alone (see aliases.split_glued_terms).
    query = aliases.split_glued_terms(wake.strip_wake(transcript))

    with StageTimer("route", log, clock, timings) as st:
        tier = router.classify(query)
        st.note(tier=tier.value, query=query)

    if tier == Tier.TIER1_DOSE:
        return _tier1(
            query, index=index, clock=clock, log=log, timings=timings,
            role=provider_role, caveats=caveats,
        )

    if tier == Tier.TIER2_SYNTHESIS:
        return _tier2(
            query, index=index, synthesizer=synthesizer, clock=clock, log=log,
            timings=timings, alpha=tier2_alpha, top_k=tier2_top_k,
        )

    # UNKNOWN -> degrade safely.
    with StageTimer("unknown", log, clock, timings) as st:
        st.note(reason="unrouted")
    log.info("answer", extra={"vigil": {"tier": tier.value, "found": False}})
    return errors.safe_not_in_protocol(tier=tier, timings=timings)


def _tier1(
    query: str,
    *,
    index: RetrievalIndex,
    clock: Callable[[], float],
    log: logging.Logger,
    timings: list[StageTiming],
    role: str = DEFAULT_ROLE,
    caveats: Optional[dict] = None,
) -> Answer:
    # Alias normalization happens BEFORE retrieval -- the make-or-break detail.
    with StageTimer("normalize", log, clock, timings) as st:
        drug = aliases.extract_drug(query)
        population = _detect_population(query)
        st.note(drug=drug, population=population)

    if drug is None:
        log.info("answer", extra={"vigil": {"tier": "tier1_dose", "found": False, "reason": "no_drug"}})
        return errors.safe_not_in_protocol(tier=Tier.TIER1_DOSE, timings=timings)

    # Deterministic exact retrieval: alpha=0 (pure keyword) + $eq metadata filter.
    # top_k>1 so multi-indication drugs surface all candidate doses for disambig.
    results: list[QueryResult] = []
    with StageTimer("retrieve", log, clock, timings) as st:
        try:
            results = index.query(
                query,
                alpha=0.0,
                filters={"drug": {"$eq": drug}, "population": {"$eq": population}},
                top_k=5,
            )
        except Exception as exc:  # safe degradation -- never crash, never guess
            st.note(hit=False, error=repr(exc))
            log.exception("retrieval_failed")
            return errors.safe_not_in_protocol(tier=Tier.TIER1_DOSE, timings=timings)
        st.note(hit=bool(results), n=len(results),
                doc_id=results[0].doc.doc_id if results else None,
                score=results[0].score if results else None)

    if not results:
        log.info("answer", extra={"vigil": {"tier": "tier1_dose", "found": False, "drug": drug, "population": population}})
        return errors.safe_not_in_protocol(tier=Tier.TIER1_DOSE, timings=timings)

    # One-shot disambiguation: pick the right indication, or ask once.
    candidates = [r.doc for r in results]
    with StageTimer("disambiguate", log, clock, timings) as st:
        doc, clar = disambig.choose_or_clarify(query, candidates)
        st.note(resolved=bool(doc), clarify=bool(clar), n=len(candidates))

    if clar is not None:
        log.info("answer", extra={"vigil": {"tier": "tier1_clarify", "drug": drug, "options": clar.question}})
        return _build_clarify_answer(clar, timings)

    if doc is None:  # nothing speakable (e.g. only empty-spoken chunks) -> never guess
        log.info("answer", extra={"vigil": {"tier": "tier1_dose", "found": False, "reason": "no_spoken_form", "drug": drug}})
        return errors.safe_not_in_protocol(tier=Tier.TIER1_DOSE, timings=timings)

    with StageTimer("answer", log, clock, timings) as st:
        st.note(found=True, citation=doc.protocol_id, doc_id=doc.doc_id)
    return _build_dose_answer(doc, timings, role=role, caveats=caveats)


def resolve_clarification(
    reply: str,
    *,
    clarification: Clarification,
    index: Optional[RetrievalIndex] = None,
    provider_role: str = DEFAULT_ROLE,
    caveats: Optional[dict] = None,
    clock: Callable[[], float] = time.perf_counter,
    logger: Optional[logging.Logger] = None,
) -> Answer:
    """Resolve the medic's reply to a pending clarification -- called EXACTLY once.

    Matches the reply to one candidate by indication; on no match returns the safe
    fallback (never re-asks, never guesses). The picked dose is role-gated. The
    reply does not need the wake word -- the agent already knows it's mid-clarify.
    """
    log = logger or logging.getLogger("vigil.pipeline")
    timings: list[StageTiming] = []
    with StageTimer("resolve_clarify", log, clock, timings) as st:
        doc = disambig.resolve_reply(reply, clarification)
        st.note(resolved=bool(doc), doc_id=doc.doc_id if doc else None)
    if doc is None:
        log.info("answer", extra={"vigil": {"tier": "tier1_dose", "found": False, "reason": "clarify_unmatched"}})
        return errors.safe_not_in_protocol(tier=Tier.TIER1_DOSE, timings=timings)
    return _build_dose_answer(doc, timings, role=provider_role, caveats=caveats)


def _tier2(
    query: str,
    *,
    index: RetrievalIndex,
    synthesizer: Optional[Synthesizer],
    clock: Callable[[], float],
    log: logging.Logger,
    timings: list[StageTiming],
    alpha: float,
    top_k: int,
) -> Answer:
    if synthesizer is None:
        with StageTimer("tier2_unavailable", log, clock, timings) as st:
            st.note(reason="no_synthesizer")
        log.info("answer", extra={"vigil": {"tier": "tier2_synthesis", "found": False, "reason": "no_synthesizer"}})
        return errors.safe_not_in_protocol(tier=Tier.TIER2_SYNTHESIS, timings=timings)

    population = _detect_population(query)

    # Hybrid retrieval (semantic-leaning); keyword anchors keep exact protocol
    # terms. Filter $in [population, "all"] so population-agnostic chunks
    # (contraindications are patient_type="all") are reachable without pulling the
    # OPPOSITE population's doses into the LLM context.
    results: list[QueryResult] = []
    with StageTimer("retrieve", log, clock, timings) as st:
        try:
            results = index.query(
                query,
                alpha=alpha,
                filters={"population": {"$in": [population, "all"]}},
                top_k=top_k,
            )
        except Exception as exc:
            st.note(hit=False, error=repr(exc))
            log.exception("retrieval_failed")
            return errors.safe_not_in_protocol(tier=Tier.TIER2_SYNTHESIS, timings=timings)
        st.note(hit=bool(results), n=len(results))

    if not results:
        log.info("answer", extra={"vigil": {"tier": "tier2_synthesis", "found": False, "reason": "no_chunks"}})
        return errors.safe_not_in_protocol(tier=Tier.TIER2_SYNTHESIS, timings=timings)

    chunks = [r.doc for r in results]

    # Strip patient identifiers BEFORE anything leaves for the LLM.
    with StageTimer("redact", log, clock, timings) as st:
        safe_query = redact.redact(query)
        st.note(redacted=(safe_query != query))

    with StageTimer("synthesize", log, clock, timings) as st:
        try:
            text = synthesizer.synthesize(safe_query, chunks)
        except Exception as exc:
            st.note(error=repr(exc))
            log.exception("synthesis_failed")
            return errors.safe_not_in_protocol(tier=Tier.TIER2_SYNTHESIS, timings=timings)
        text = (text or "").strip()
        st.note(chars=len(text))

    if not text:
        return errors.safe_not_in_protocol(tier=Tier.TIER2_SYNTHESIS, timings=timings)

    # Number-grounding guard: discard any answer that introduces a number not in
    # the retrieved chunks. This is what keeps Tier 2 from inventing a dose.
    with StageTimer("ground_check", log, clock, timings) as st:
        allowed: list[str] = []
        for c in chunks:
            allowed.extend(
                (c.text, c.dose_value, c.spoken_form, c.protocol_id,
                 c.drug, c.population, c.indication, str(c.metadata))
            )
        bad = grounding.ungrounded_numbers(text, allowed)
        st.note(ungrounded=bad)
    if bad:
        log.warning("tier2_ungrounded_number", extra={"vigil": {"ungrounded": bad}})
        return errors.safe_not_in_protocol(tier=Tier.TIER2_SYNTHESIS, timings=timings)

    citations = [c.protocol_id for c in chunks]
    card = {
        "found": True,
        "tier": Tier.TIER2_SYNTHESIS.value,
        "text": text,
        "citations": citations,
        "population": population,
    }
    with StageTimer("answer", log, clock, timings) as st:
        st.note(found=True, citations=citations)
    return Answer(
        tier=Tier.TIER2_SYNTHESIS,
        spoken_form=text,
        card=card,
        citation=citations[0] if citations else None,
        doc_id=chunks[0].doc_id,
        found=True,
        timings=timings,
    )
