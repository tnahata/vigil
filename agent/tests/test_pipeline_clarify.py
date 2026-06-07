"""One-shot Tier-1 clarification: an ambiguous (drug, population) -> ask ONE
question, then resolve the reply to the right indication (or safe-fall-back).
The dose is always verbatim; the question never speaks a number.
"""
from vigil.core.errors import SAFE_FALLBACK_SPOKEN
from vigil.core.pipeline import resolve_clarification


def _ask(run):
    # ATROPINE adult: unstable bradycardia (1 mg) vs organophosphate (2 mg).
    ans = run("Vigil, how much atropine for an adult")
    assert ans is not None
    assert ans.found is False
    assert ans.clarification is not None, "ambiguous atropine must ask, not guess"
    return ans


def test_ambiguous_drug_asks_one_question(run):
    ans = _ask(run)
    q = ans.spoken_form.lower()
    assert "bradycardia" in q and "organophosphate" in q
    # the question must NOT speak a dose number
    for token in ("milligram", " mg", " 1 ", " 2 "):
        assert token not in f" {q} "


def test_clarification_reply_resolves_to_correct_dose(run):
    clar = _ask(run).clarification
    r1 = resolve_clarification("for unstable bradycardia", clarification=clar)
    assert r1.found and r1.doc_id == "atropine-unstable-bradycardia-adult-0"
    assert r1.spoken_form == "one milligram"
    r2 = resolve_clarification("organophosphate poisoning", clarification=clar)
    assert r2.found and r2.doc_id == "atropine-symptomatic-organophosphate-poisoning-adult-1"
    assert r2.spoken_form == "two milligrams"


def test_unmatched_reply_safe_fallbacks_and_never_reasks(run):
    r = resolve_clarification("uh the weather is nice", clarification=_ask(run).clarification)
    assert r.found is False
    assert r.spoken_form == SAFE_FALLBACK_SPOKEN
    assert r.clarification is None  # one-shot: never asks a second question


def test_indication_in_query_resolves_without_asking(run):
    # If the query already names the indication, answer directly -- no question.
    ans = run("Vigil, how much atropine for an adult with organophosphate poisoning")
    assert ans is not None and ans.found
    assert ans.clarification is None
    assert ans.spoken_form == "two milligrams"
