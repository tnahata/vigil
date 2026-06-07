"""Tier-2 Synthesizer backed by Minimax's OpenAI-compatible chat endpoint.

Lives in adapters (NOT core): it lazily imports `openai`, so the core-purity test
stays green and the package stays importable without the SDK present. Sync client
on purpose -- the worker calls the pipeline in a thread executor, so a multi-second
LLM call never blocks the agent event loop.
"""
from __future__ import annotations

from ..core import prompt
from ..core.models import Doc


def _strip_reasoning(text: str) -> str:
    """Drop the <think>...</think> chain-of-thought a reasoning model (MiniMax-M3)
    emits before its answer -- otherwise the agent speaks its own reasoning aloud.

    Take everything after the final </think>. If <think> opened but never closed
    (answer truncated by max_tokens), there is no usable answer -> "" (the pipeline
    then safe-falls-back rather than speaking half a thought).
    """
    low = text.lower()
    end = low.rfind("</think>")
    if end != -1:
        return text[end + len("</think>"):].strip()
    if "<think>" in low:
        return ""
    return text.strip()


class MinimaxSynthesizer:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.minimax.io/v1",
        model: str = "MiniMax-Text-01",  # non-reasoning: fast + concise (see config)
        timeout: float = 30.0,
        max_tokens: int = 256,  # a one-sentence answer needs little; caps rambling
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
        # Strip the reasoning block BEFORE the text reaches the grounding guard and
        # TTS -- the guard must check the actual answer, and TTS must not read CoT.
        return _strip_reasoning(resp.choices[0].message.content or "")
