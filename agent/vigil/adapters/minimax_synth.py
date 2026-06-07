"""Tier-2 Synthesizer backed by Minimax's OpenAI-compatible chat endpoint.

Lives in adapters (NOT core): it lazily imports `openai`, so the core-purity test
stays green and the package stays importable without the SDK present. Sync client
on purpose -- the worker calls the pipeline in a thread executor, so a multi-second
LLM call never blocks the agent event loop.
"""
from __future__ import annotations

from ..core import prompt
from ..core.models import Doc


class MinimaxSynthesizer:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.minimax.io/v1",
        model: str = "MiniMax-M3",
        timeout: float = 30.0,
        max_tokens: int = 300,
        temperature: float = 0.2,
    ) -> None:
        from openai import OpenAI  # lazy import

        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def synthesize(self, query: str, chunks: "list[Doc]") -> str:
        messages = prompt.build_messages(query, chunks)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )
        return (resp.choices[0].message.content or "").strip()
