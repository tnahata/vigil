"""Core data models. Frozen dataclasses, stdlib only."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Tier(str, Enum):
    """Routing tiers. Tier 1 is the deterministic, life-critical dose path."""

    TIER1_DOSE = "tier1_dose"
    TIER2_SYNTHESIS = "tier2_synthesis"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StageTiming:
    """One pipeline stage's wall-clock cost, in milliseconds."""

    stage: str
    ms: float


@dataclass(frozen=True)
class Doc:
    """A verbatim protocol chunk. The dose number lives ONLY here and in TTS.

    `spoken_form` is the exact, TTS-safe string the agent speaks -- it is never
    assembled from a number in code, and never produced by a model.
    """

    doc_id: str
    text: str
    drug: str            # canonical name (post-alias-normalization)
    population: str       # "adult" | "pediatric"
    indication: str       # e.g. "anaphylaxis", "cardiac_arrest"
    dose_value: str       # machine-readable dose, e.g. "0.3 mg"
    spoken_form: str      # exact words for TTS
    protocol_id: str      # citation
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Doc":
        return cls(
            doc_id=d["doc_id"],
            text=d["text"],
            drug=d["drug"],
            population=d["population"],
            indication=d.get("indication", ""),
            dose_value=d["dose_value"],
            spoken_form=d["spoken_form"],
            protocol_id=d["protocol_id"],
            metadata=d.get("metadata", {}),
        )

    @classmethod
    def from_chunk(cls, chunk: dict) -> "Doc":
        """Map a Moss/ingestion chunk ({id, text, metadata}) onto a Doc.

        The single source of truth for the real-schema mapping -- used by BOTH
        the FakeIndex (loading chunks.json) and the MossIndex (mapping query
        results), so the two backends speak identical Docs.

          metadata.patient_type  -> population
          metadata.value_machine -> dose_value (machine string, for the card)
          metadata.value_spoken  -> spoken_form (TTS-safe; "" for contraindications)
          metadata.source + page -> protocol_id (citation)
        """
        m = chunk.get("metadata") or {}
        src, page = m.get("source", ""), m.get("page", "")
        protocol_id = f"{src} p.{page}" if (src and page) else (src or "")
        return cls(
            doc_id=chunk["id"],
            text=chunk.get("text") or m.get("value_machine", ""),
            drug=m.get("drug", ""),
            population=m.get("patient_type", ""),
            indication=m.get("indication", ""),
            dose_value=m.get("value_machine", ""),
            spoken_form=m.get("value_spoken") or "",
            protocol_id=protocol_id,
            metadata=dict(m),
        )


@dataclass(frozen=True)
class Clarification:
    """A pending one-shot Tier-1 disambiguation.

    Raised when a (drug, population) maps to >1 dose chunk distinguished only by
    indication and the query doesn't pick one (e.g. atropine: bradycardia 1 mg vs
    organophosphate 2 mg). The agent speaks `question` (which names indications,
    never a dose number) and holds the candidate Docs for the medic's reply. The
    reply is resolved against these candidates exactly once -- never re-asked.
    """

    drug: str
    population: str
    question: str
    candidates: tuple[Doc, ...] = ()


@dataclass(frozen=True)
class Answer:
    """What the worker speaks + renders. `found=False` => safe fallback.

    If `clarification` is set, this is NOT an answer yet: the worker speaks
    `spoken_form` (the clarifying question) and waits for one reply.
    """

    tier: Tier
    spoken_form: str
    card: dict
    citation: str | None
    doc_id: str | None
    found: bool
    timings: list[StageTiming] = field(default_factory=list)
    clarification: Clarification | None = None
