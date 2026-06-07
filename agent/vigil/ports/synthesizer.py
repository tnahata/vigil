"""Synthesizer port: Tier-2 soft synthesis from retrieved chunks.

The implementation is an LLM (Minimax), but it sits behind this interface so
`vigil.core` never imports an LLM SDK -- the core-purity test still holds.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.models import Doc


@runtime_checkable
class Synthesizer(Protocol):
    def synthesize(self, query: str, chunks: "list[Doc]") -> str:
        """Return a short, spoken-friendly answer grounded ONLY in `chunks`."""
        ...
