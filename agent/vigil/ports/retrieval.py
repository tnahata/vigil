"""Retrieval port. One signature serves Tier-1 exact (alpha=0 + $eq filters) and
Tier-2 hybrid (alpha ~0.6). Filters use Moss-style operators ($eq/$in/$and) so
the FakeIndex and the real MossIndex share a contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..core.models import Doc


@dataclass(frozen=True)
class QueryResult:
    doc: Doc
    score: float


@runtime_checkable
class RetrievalIndex(Protocol):
    def query(
        self,
        text: str,
        *,
        alpha: float,
        filters: dict,
        top_k: int = 5,
    ) -> "list[QueryResult]":
        """alpha=0 => pure keyword; alpha=1 => pure semantic."""
        ...
