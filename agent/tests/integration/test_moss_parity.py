"""Opt-in LIVE parity: the real MossIndex must return the same doc_id as the
hermetic FakeIndex for each Tier-1 gold anchor. This is the ONLY test that
validates Moss's BM25 ranking -- the hermetic gate proves plumbing/routing but
cannot prove ordering. Runs only when RUN_MOSS=1 and Moss creds are present
(agent/.env is loaded by tests/integration/conftest.py).

    RUN_MOSS=1 .venv/bin/python -m pytest tests/integration/test_moss_parity.py -v
"""
import os

import pytest

pytestmark = pytest.mark.integration

_RUN = os.getenv("RUN_MOSS") == "1"

# doc_id -> spoken query. Same anchors as the hermetic gold gate.
GOLD = {
    "epinephrine-11000-anaphylaxis-adult-0": "Vigil, what's the adult epinephrine dose for anaphylaxis",
    "naloxone-reversal-of-acute-opioid-toxicity-adult-0": "Vigil, what's the adult naloxone dose",
    "aspirin-acute-coronary-syndrome-adult-0": "Vigil, how much aspirin for an adult",
    "dextrose-hypoglycemia-adult-0": "Vigil, how much dextrose for an adult with hypoglycemia",
    "adenosine-supraventricular-tachycardia-svt-adult-0": "Vigil, how much adenosine for an adult with SVT",
}


@pytest.fixture(scope="module")
def moss_index():
    pid, key = os.getenv("MOSS_PROJECT_ID"), os.getenv("MOSS_PROJECT_KEY")
    if not pid or not key:
        pytest.skip("MOSS_PROJECT_ID / MOSS_PROJECT_KEY not set")
    from vigil.adapters.moss_index import MossIndex

    idx = MossIndex(os.getenv("MOSS_INDEX_NAME", "vigil-protocol"), pid, key)
    yield idx
    idx.close()


@pytest.mark.skipif(not _RUN, reason="opt-in: set RUN_MOSS=1 (and Moss creds) to run live parity")
def test_moss_returns_expected_anchor(moss_index):
    from vigil.core.pipeline import handle_transcript

    misses = []
    for doc_id, query in GOLD.items():
        ans = handle_transcript(query, index=moss_index, provider_role="PARAMEDIC")
        if ans is None or not ans.found or ans.doc_id != doc_id:
            misses.append((doc_id, None if ans is None else ans.doc_id))
    assert not misses, f"Moss ranking diverged from gold: {misses}"
