"""Tier-2 (soft synthesis) hermetic tests. Uses FakeSynthesizer -- no network.

The safety property under test: Tier 2 may use an LLM, but PII is stripped first,
and any answer that introduces a number absent from the retrieved chunks is
discarded in favor of the safe fallback.
"""
from vigil.adapters.fake_index import FakeIndex
from vigil.core.errors import SAFE_FALLBACK_SPOKEN
from vigil.core.models import Tier
from vigil.core.pipeline import handle_transcript

from tests.fakes import FakeSynthesizer

TIER2_Q = "Vigil, what should I consider before giving epinephrine to an adult in anaphylaxis"


def test_tier2_routes_and_synthesizes(run_tier2):
    ans = run_tier2(TIER2_Q)
    assert ans is not None
    assert ans.tier == Tier.TIER2_SYNTHESIS
    assert ans.found is True
    assert ans.card["citations"], "expected protocol citations on the card"
    assert ans.spoken_form  # non-empty grounded text


def test_tier2_no_synthesizer_falls_back(run_tier2):
    ans = run_tier2(TIER2_Q, synthesizer=None)
    assert ans is not None
    assert ans.found is False
    assert ans.spoken_form == SAFE_FALLBACK_SPOKEN


def test_tier2_ungrounded_number_is_discarded(run_tier2):
    # LLM tries to invent a dose not present in any chunk -> safe fallback
    bad = FakeSynthesizer(reply="Administer 999 milligrams immediately.")
    ans = run_tier2(TIER2_Q, synthesizer=bad)
    assert ans.found is False
    assert ans.spoken_form == SAFE_FALLBACK_SPOKEN


def test_tier2_pii_redacted_before_synthesis(fake_index):
    synth = FakeSynthesizer()
    q = "Vigil, patient MRN 12345678, what should I consider before epinephrine for an adult in anaphylaxis"
    handle_transcript(q, index=fake_index, synthesizer=synth)
    assert synth.last_query is not None
    assert "12345678" not in synth.last_query
    assert "[MRN]" in synth.last_query


def test_tier2_no_chunks_falls_back():
    # Empty index -> retrieval returns nothing -> safe fallback (no LLM call)
    synth = FakeSynthesizer(reply="should not be used")
    ans = handle_transcript(TIER2_Q, index=FakeIndex([]), synthesizer=synth)
    assert ans.found is False
    assert synth.last_query is None  # synthesizer never invoked
