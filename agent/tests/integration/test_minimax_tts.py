"""Opt-in live smoke test for Minimax TTS (voice out).

Guards the base_url regression: the plugin appends /v1/t2a_v2, so MINIMAX_TTS_BASE_URL
must be the bare host (https://api.minimax.io), NOT the LLM's .../v1 base. Run with:

    RUN_INTEGRATION=1 .venv/bin/python -m pytest tests/integration/test_minimax_tts.py -v
"""
import os

import pytest

pytestmark = pytest.mark.integration

_RUN = os.getenv("RUN_INTEGRATION") == "1"


@pytest.mark.skipif(not _RUN, reason="opt-in: set RUN_INTEGRATION=1 to run")
async def test_minimax_tts_synthesizes_audio():
    if not os.getenv("MINIMAX_API_KEY"):
        pytest.skip("MINIMAX_API_KEY not set")

    from livekit.agents.utils import http_context
    from livekit.plugins import minimax

    ctx = getattr(http_context, "open", None) or http_context._new_session_ctx
    total = 0
    async with ctx():
        tts = minimax.TTS(
            base_url=os.getenv("MINIMAX_TTS_BASE_URL", "https://api.minimax.io"),
            model=os.getenv("MINIMAX_TTS_MODEL", "speech-2.8-hd"),
            voice=os.getenv("MINIMAX_TTS_VOICE", "English_expressive_narrator"),
        )
        async for ev in tts.synthesize("Epinephrine, zero point three milligrams."):
            frame = getattr(ev, "frame", None)
            if frame is not None:
                total += len(frame.data)
        await tts.aclose()

    assert total > 0, "no audio synthesized from Minimax TTS"
