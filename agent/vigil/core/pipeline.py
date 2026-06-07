"""The orchestrator: transcript string -> Answer (or None).

Pure and synchronous. Dependency-injected retrieval (RetrievalIndex) and, for
Tier 2, a Synthesizer. Imports nothing external -- no livekit, no LLM, no Moss.

Tier 1 (dose): the number is copied verbatim from retrieval; never computed,
generated, or model-produced.

Tier 2 (synthesis): an LLM answers, but constrained to retrieved chunks, with PII
redacted from the query and a number-grounding guard that discards any answer
introducing a number absent from the chunks. Any failure on either tier degrades
to the safe fallback -- the agent never crashes and never guesses a dose.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from . import aliases, errors, grounding, redact, router, wake
from .models import Answer, Doc, StageTiming, Tier
from .trace import StageTimer
from ..ports.retrieval import QueryResult, RetrievalIndex
from ..ports.synthesizer import Synthesizer

_PEDS_TOKENS = (
    "peds", "pediatric", "paediatric", "child", "children",
    "kid", "infant", "baby", "neonate", "newborn",
)


def _detect_population(query: str) -> str:
    q = query.lower()
    return "pediatric" if any(t in q for t in _PEDS_TOKENS) else "adult"


def _build_dose_answer(doc: Doc, timings: list[StageTiming]) -> Answer:
    # SAFETY INVARIANT: spoken_form and dose are copied verbatim from the doc.
    card = {
        "found": True,
        "tier": Tier.TIER1_DOSE.value,
        "drug": doc.drug,
        "population": doc.population,
        "indication": doc.indication,
        "dose": doc.dose_value,
        "citation": doc.protocol_id,
    }
    return Answer(
        tier=Tier.TIER1_DOSE,
        spoken_form=doc.spoken_form,
        card=card,
        citation=doc.protocol_id,
        doc_id=doc.doc_id,
        found=True,
        timings=timings,
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
        return _tier1(query, index=index, clock=clock, log=log, timings=timings)

    if tier == Tier.TIER2_SYNTHESIS:
        return _tier2(
            query,
            index=index,
            synthesizer=synthesizer,
            clock=clock,
            log=log,
            timings=timings,
            alpha=tier2_alpha,
            top_k=tier2_top_k,
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
    results: list[QueryResult] = []
    with StageTimer("retrieve", log, clock, timings) as st:
        try:
            results = index.query(
                query,
                alpha=0.0,
                filters={"drug": {"$eq": drug}, "population": {"$eq": population}},
                top_k=1,
            )
        except Exception as exc:  # safe degradation -- never crash, never guess
            st.note(hit=False, error=repr(exc))
            log.exception("retrieval_failed")
            return errors.safe_not_in_protocol(tier=Tier.TIER1_DOSE, timings=timings)
        st.note(
            hit=bool(results),
            n=len(results),
            doc_id=results[0].doc.doc_id if results else None,
            score=results[0].score if results else None,
        )

    if not results:
        log.info(
            "answer",
            extra={"vigil": {"tier": "tier1_dose", "found": False, "drug": drug, "population": population}},
        )
        return errors.safe_not_in_protocol(tier=Tier.TIER1_DOSE, timings=timings)

    doc = results[0].doc
    with StageTimer("answer", log, clock, timings) as st:
        st.note(found=True, citation=doc.protocol_id, doc_id=doc.doc_id)
    return _build_dose_answer(doc, timings)


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

    # Hybrid retrieval (semantic-leaning); keyword anchors keep exact protocol terms.
    results: list[QueryResult] = []
    with StageTimer("retrieve", log, clock, timings) as st:
        try:
            results = index.query(
                query,
                alpha=alpha,
                filters={"population": {"$eq": population}},
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
        # "Grounded" = the number appears anywhere in the RETRIEVED record (dose,
        # text, spoken_form, citation id, metadata) -- only truly invented numbers
        # are flagged. A fabricated dose like "999" still has nowhere to hide.
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
