"""Speaker port backed by a LiveKit AgentSession.

session.say() speaks a fixed string and BYPASSES the LLM, keeping the dose path
deterministic. This module is one of the few that (indirectly) touch LiveKit; it
imports nothing at module load, so it stays import-safe without the SDK present.
"""
from __future__ import annotations


class LiveKitSpeaker:
    def __init__(self, session) -> None:
        self._session = session

    async def say(self, text: str) -> None:
        await self._session.say(text, allow_interruptions=False)
