"""Speaker port: speak a fixed string. The LiveKit adapter uses session.say(),
which BYPASSES the LLM -- so the dose path stays deterministic.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Speaker(Protocol):
    async def say(self, text: str) -> None: ...
