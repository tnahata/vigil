"""The synthesizer must strip a reasoning model's <think> block before the text
reaches the grounding guard and TTS -- else the agent speaks its chain-of-thought.
(Pure function; importing it needs no openai SDK.)
"""
from vigil.adapters.minimax_synth import _strip_reasoning


def test_strips_inline_think_block():
    assert _strip_reasoning("<think>weighing options</think>The answer.") == "The answer."


def test_strips_multiline_think_block():
    s = "<think>\nstep 1\nstep 2\n</think>\nNitro is contraindicated [P1]."
    assert _strip_reasoning(s) == "Nitro is contraindicated [P1]."


def test_truncated_think_yields_empty():
    # Opened but never closed (max_tokens cut it off) -> no usable answer.
    assert _strip_reasoning("<think>still reasoning, no answer yet") == ""


def test_plain_answer_passthrough():
    assert _strip_reasoning("  Just the answer.  ") == "Just the answer."


def test_case_insensitive():
    assert _strip_reasoning("<THINK>x</THINK>ans") == "ans"
