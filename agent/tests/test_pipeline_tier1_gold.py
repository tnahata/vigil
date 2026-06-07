"""Tier-1 100% gate. Because Tier 1 is verbatim-from-retrieval, anything below
100% is a routing/alias/retrieval bug to fix before demo -- not variance.
"""
import pytest

# A realistic spoken query (with wake word) for each gold doc.
GOLD_QUERIES = {
    "epi_adult_anaphylaxis": "Vigil, what's the adult epinephrine dose for anaphylaxis",
    "epi_peds_anaphylaxis": "Vigil, what's the pediatric epi dose for anaphylaxis",
    "epi_adult_cardiac_arrest": "Vigil, how much epinephrine for an adult in cardiac arrest",
    "naloxone_adult_opioid": "Vigil, what's the adult naloxone dose for opioid overdose",
    "dextrose_adult_hypoglycemia": "Vigil, how much dextrose for an adult with hypoglycemia",
}


@pytest.fixture
def docs_by_id(gold_docs):
    return {d["doc_id"]: d for d in gold_docs}


def test_gold_queries_cover_every_doc(docs_by_id):
    assert set(GOLD_QUERIES) == set(docs_by_id), "gold queries must cover all gold docs"


def test_every_gold_query_hits_exact_dose(run, docs_by_id):
    for doc_id, query in GOLD_QUERIES.items():
        ans = run(query)
        assert ans is not None, f"{doc_id}: no answer (routing/wake bug)"
        assert ans.found, f"{doc_id}: not found (alias/retrieval bug)"
        gold = docs_by_id[doc_id]
        assert ans.doc_id == doc_id, f"{doc_id}: returned wrong doc {ans.doc_id}"
        assert ans.card["dose"] == gold["dose_value"], f"{doc_id}: dose mismatch"
        assert ans.citation == gold["protocol_id"], f"{doc_id}: citation mismatch"
        # SAFETY: spoken_form is byte-identical to the protocol's stored spoken_form
        assert ans.spoken_form == gold["spoken_form"], f"{doc_id}: spoken_form not verbatim"


def test_aliases_still_hit_gold(run):
    ans = run("Vigil, adrenaline dose for an adult in anaphylaxis")
    assert ans is not None and ans.found
    assert ans.doc_id == "epi_adult_anaphylaxis"

    ans = run("Vigil, narcan dose for an adult opioid overdose")
    assert ans is not None and ans.found
    assert ans.doc_id == "naloxone_adult_opioid"


def test_stt_glued_words_still_hit_tier1(run):
    # Real transcript observed live: STT rendered "epi dose" as "epidose" and the
    # query fell through to UNKNOWN. split_glued_terms must repair it pre-routing.
    ans = run("It's Vigil, what's the adult epidose for anaphylaxis?")
    assert ans is not None and ans.found, "glued 'epidose' must still route to Tier-1"
    assert ans.doc_id == "epi_adult_anaphylaxis"
    assert ans.card["dose"] == "0.3 mg"
