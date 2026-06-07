import json
import os

import pytest

from vigil.adapters.fake_index import FakeIndex
from vigil.core.pipeline import handle_transcript

# agent/tests/conftest.py -> agent/data/chunks.json (the SAME real chunks the live
# Moss index is built from, so the hermetic gate exercises the real schema).
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "chunks.json")


@pytest.fixture
def chunks_path():
    return DATA


@pytest.fixture
def gold_docs():
    """The raw chunk list ({id, text, metadata}), keyed elsewhere by id."""
    with open(DATA) as f:
        return json.load(f)


@pytest.fixture
def fake_index():
    return FakeIndex.from_chunks_json(DATA)


@pytest.fixture
def run(fake_index):
    """Run the full pipeline against the chunks-seeded fake index."""
    def _run(transcript):
        return handle_transcript(transcript, index=fake_index)
    return _run


@pytest.fixture
def fake_synth():
    from tests.fakes import FakeSynthesizer
    return FakeSynthesizer()


@pytest.fixture
def run_tier2(fake_index, fake_synth):
    """Run the pipeline with a fake synthesizer wired in (Tier-2 enabled)."""
    def _run(transcript, synthesizer="__default__"):
        synth = fake_synth if synthesizer == "__default__" else synthesizer
        return handle_transcript(transcript, index=fake_index, synthesizer=synth)
    return _run
