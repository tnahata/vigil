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


# Every indication-dependent drug must ask, and no clarifying question may speak a
# number (some indication strings embed thresholds/doses, e.g. nitroglycerin's
# "...NTG 0.4 mg SL" -- which must never be read aloud).
AMBIGUOUS_DRUGS = {
    "amiodarone": "Vigil, how much amiodarone for an adult",
    "atropine": "Vigil, how much atropine for an adult",
    "glucagon": "Vigil, how much glucagon for an adult",
    "lidocaine": "Vigil, how much lidocaine for an adult",
    "nitroglycerin": "Vigil, how much nitroglycerin for an adult",
    "buprenorphine": "Vigil, how much buprenorphine for an adult",
}


def test_all_indication_dependent_drugs_ask_with_number_free_questions(run):
    for name, query in AMBIGUOUS_DRUGS.items():
        ans = run(query)
        assert ans is not None and ans.clarification is not None, f"{name}: must ask, not guess"
        assert not any(ch.isdigit() for ch in ans.spoken_form), f"{name}: question spoke a number: {ans.spoken_form!r}"


def test_nitroglycerin_resolves_both_indications(run):
    # Regression: "ntg" appears inside one indication string and used to spuriously
    # auto-resolve to 0.8 mg instead of asking.
    clar = run("Vigil, how much nitroglycerin for an adult").clarification
    chf = resolve_clarification("CHF", clarification=clar)
    assert chf.found and chf.spoken_form == "zero point eight milligrams"
    pain = resolve_clarification("cardiac chest pain", clarification=clar)
    assert pain.found and pain.spoken_form == "zero point four milligrams"


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


def test_positional_reply_resolves_when_symptom_word_mangled(run):
    # Live failure: STT mangles "stable VT" -> "Abel VT"/"Double VT", so symptom
    # scoring whiffs and the shared "VT" ties across candidates. The medic can
    # instead say "the first one" / "number two" and still resolve deterministically.
    clar = run("Vigil, how much amiodarone for an adult").clarification
    assert clar is not None and len(clar.candidates) >= 2
    first = resolve_clarification("the first one", clarification=clar)
    assert first.found and first.doc_id == clar.candidates[0].doc_id
    second = resolve_clarification("number two", clarification=clar)
    assert second.found and second.doc_id == clar.candidates[1].doc_id


def test_shared_word_reply_never_guesses_a_dose(run):
    # A reply of only the word the candidates SHARE ("VT", common to the stable-VT
    # and VF/pulseless-VT indications) does not uniquely distinguish -> safe
    # fallback, never a guessed dose. This is the safety side of the live bug.
    clar = run("Vigil, how much amiodarone for an adult").clarification
    assert clar is not None
    r = resolve_clarification("VT", clarification=clar)
    assert r.found is False and r.spoken_form == SAFE_FALLBACK_SPOKEN


def test_indication_in_query_resolves_without_asking(run):
    # If the query already names the indication, answer directly -- no question.
    ans = run("Vigil, how much atropine for an adult with organophosphate poisoning")
    assert ans is not None and ans.found
    assert ans.clarification is None
    assert ans.spoken_form == "two milligrams"
