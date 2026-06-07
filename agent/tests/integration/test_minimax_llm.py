"""Opt-in live smoke test for the Minimax LLM path (Tier-2 backbone).

Runs ONLY when RUN_INTEGRATION=1 and MINIMAX_API_KEY is set. One tiny, token-capped
call -- credit-frugal. Run with:

    RUN_INTEGRATION=1 .venv/bin/python -m pytest tests/integration -v
"""
import os

import pytest

pytestmark = pytest.mark.integration

_RUN = os.getenv("RUN_INTEGRATION") == "1"


@pytest.mark.skipif(not _RUN, reason="opt-in: set RUN_INTEGRATION=1 to run")
def test_minimax_llm_smoke():
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        pytest.skip("MINIMAX_API_KEY not set")

    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
        timeout=30.0,
    )
    resp = client.chat.completions.create(
        model=os.getenv("MINIMAX_LLM_MODEL", "MiniMax-M3"),
        messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        max_tokens=5,
        temperature=0,
    )
    content = (resp.choices[0].message.content or "").strip()
    assert content, "empty response from Minimax LLM"


@pytest.mark.skipif(not _RUN, reason="opt-in: set RUN_INTEGRATION=1 to run")
def test_minimax_synthesizer_is_grounded():
    """End-to-end Tier-2: real Minimax synthesizer + our grounding guard.

    Asserts the synthesizer returns text AND that it introduces no number absent
    from the chunks (the production safety guard, exercised against the real LLM).
    """
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        pytest.skip("MINIMAX_API_KEY not set")

    from vigil.adapters.minimax_synth import MinimaxSynthesizer
    from vigil.core.grounding import ungrounded_numbers
    from vigil.core.models import Doc

    chunk = Doc(
        doc_id="epi_adult_anaphylaxis",
        text="Epinephrine (1 mg/mL) 0.3 mg IM, lateral thigh; may repeat every 5 to 15 minutes.",
        drug="epinephrine",
        population="adult",
        indication="anaphylaxis",
        dose_value="0.3 mg",
        spoken_form="Epinephrine zero point three milligrams intramuscular.",
        protocol_id="PROTO-AdultAnaphylaxis-2.1",
        metadata={},
    )
    synth = MinimaxSynthesizer(
        api_key=api_key,
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
        model=os.getenv("MINIMAX_LLM_MODEL", "MiniMax-M3"),
        max_tokens=120,
    )
    text = synth.synthesize("What should I consider before giving epinephrine for anaphylaxis?", [chunk])
    assert text, "empty synthesis"
    bad = ungrounded_numbers(text, [chunk.text, chunk.dose_value, chunk.spoken_form])
    assert bad == [], f"LLM introduced ungrounded numbers: {bad} in {text!r}"
