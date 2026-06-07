"""Test doubles shared across the suite."""
from __future__ import annotations


class FakeSynthesizer:
    """Deterministic stand-in for the Minimax LLM (hermetic tests, no network).

    Default reply is grounded: it echoes the top chunk's verbatim spoken_form, so
    the number-grounding guard passes. Pass `reply=` to simulate an ungrounded or
    custom answer. Records the (redacted) query it received for redaction tests.
    """

    def __init__(self, reply: str | None = None):
        self._reply = reply
        self.last_query = None
        self.last_chunks = None

    def synthesize(self, query, chunks):
        self.last_query = query
        self.last_chunks = chunks
        if self._reply is not None:
            return self._reply
        top = chunks[0]
        return f"Per protocol {top.protocol_id}: {top.spoken_form}"
