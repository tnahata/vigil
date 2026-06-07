"""Tier-1 100% gate. Because Tier 1 is verbatim-from-retrieval, anything below
100% is a routing/alias/retrieval bug to fix before demo -- not variance.

Anchors are verified-UNAMBIGUOUS (a single adult dose chunk for the drug, so
top_k ranking is irrelevant) and on PARAMEDIC-authorized pages (so role gating
leaves the spoken dose verbatim). This gate proves routing + alias + schema
plumbing + verbatim-copy; it does NOT prove Moss's BM25 ranking -- that's the
opt-in live parity test (tests/integration/test_moss_parity.py).
"""
import pytest

from vigil.core.pipeline import handle_transcript

# doc_id -> (spoken query with wake word, hardcoded expected spoken_form). The
# literal spoken_form catches a silent field-mapping swap (e.g. value_machine
# leaking into the spoken slot) that an all-from-the-same-dict check would miss.
GOLD = {
    "epinephrine-11000-anaphylaxis-adult-0": (
        "Vigil, what's the adult epinephrine dose for anaphylaxis", "zero point five milligrams"),
    "naloxone-reversal-of-acute-opioid-toxicity-adult-0": (
        "Vigil, what's the adult naloxone dose", "two milligrams"),
    "aspirin-acute-coronary-syndrome-adult-0": (
        "Vigil, how much aspirin for an adult", "three hundred twenty-four milligrams"),
    "dextrose-hypoglycemia-adult-0": (
        "Vigil, how much dextrose for an adult with hypoglycemia", "twenty-five grams"),
    "adenosine-supraventricular-tachycardia-svt-adult-0": (
        "Vigil, how much adenosine for an adult with SVT", "six milligrams"),
}


@pytest.fixture
def docs_by_id(gold_docs):
    return {d["id"]: d for d in gold_docs}


def test_gold_anchors_exist(docs_by_id):
    for doc_id in GOLD:
        assert doc_id in docs_by_id, f"gold anchor missing from chunks.json: {doc_id}"


def test_every_gold_query_hits_exact_dose(run, docs_by_id):
    for doc_id, (query, expected_spoken) in GOLD.items():
        ans = run(query)
        assert ans is not None, f"{doc_id}: no answer (routing/wake bug)"
        assert ans.found, f"{doc_id}: not found (alias/retrieval bug)"
        assert ans.doc_id == doc_id, f"{doc_id}: returned wrong doc {ans.doc_id}"
        m = docs_by_id[doc_id]["metadata"]
        assert ans.card["dose"] == m["value_machine"], f"{doc_id}: machine dose mismatch"
        assert ans.citation == f'{m["source"]} p.{m["page"]}', f"{doc_id}: citation mismatch"
        # SAFETY: spoken_form is byte-identical to the protocol's stored value_spoken
        assert ans.spoken_form == m["value_spoken"], f"{doc_id}: spoken_form not verbatim"
        # ...and to the hardcoded literal (guards against a field-mapping swap).
        assert ans.spoken_form == expected_spoken, f"{doc_id}: spoken_form != expected literal"


def test_aliases_still_hit_gold(run):
    ans = run("Vigil, adrenaline dose for an adult in anaphylaxis")
    assert ans is not None and ans.found
    assert ans.doc_id == "epinephrine-11000-anaphylaxis-adult-0"

    ans = run("Vigil, narcan dose for an adult")
    assert ans is not None and ans.found
    assert ans.doc_id == "naloxone-reversal-of-acute-opioid-toxicity-adult-0"


def test_stt_glued_words_still_hit_tier1(run):
    # Real transcript observed live: STT rendered "epi dose" as "epidose" and the
    # query fell through to UNKNOWN. split_glued_terms must repair it pre-routing.
    ans = run("It's Vigil, what's the adult epidose for anaphylaxis?")
    assert ans is not None and ans.found, "glued 'epidose' must still route to Tier-1"
    assert ans.doc_id == "epinephrine-11000-anaphylaxis-adult-0"
    assert ans.spoken_form == "zero point five milligrams"
