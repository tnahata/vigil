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


@dataclass(frozen=True)
class Answer:
    """What the worker speaks + renders. `found=False` => safe fallback."""

    tier: Tier
    spoken_form: str
    card: dict
    citation: str | None
    doc_id: str | None
    found: bool
    timings: list[StageTiming] = field(default_factory=list)
