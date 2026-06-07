"""The wake state machine's pure decision.

The cross-turn STATE (sticky window, buffer, pending clarification) lives on the
LiveKit adapter and isn't hermetically testable. The DECISION it makes each turn --
"is this buffered query a real ask, or still forming?" -- is pure
(`vigil.core.dialog.query_has_substance`) and tested here, together with the
stitched-query routing through the real pipeline (what the agent does:
`handle_transcript("vigil " + buffer)`).
"""
from vigil.core import dialog
from vigil.core.errors import SAFE_FALLBACK_SPOKEN


def test_fragments_are_still_forming():
    # Bare "Vigil" (-> "") and trivial fragments must NOT answer -> the agent stays
    # silent and keeps listening. This is what kills the spurious "Not in protocol".
    assert dialog.query_has_substance("") is False
    assert dialog.query_has_substance("what") is False
    assert dialog.query_has_substance("the patient is") is False


def test_substance_when_intent_or_known_drug_present():
    assert dialog.query_has_substance("how much amiodarone for an adult") is True
    assert dialog.query_has_substance("what should i consider before epinephrine") is True
    assert dialog.query_has_substance("epinephrine") is True          # bare known drug
    assert dialog.query_has_substance("how much rocuronium") is True  # intent, unknown drug


def test_split_wake_then_query_stitches_and_answers(run):
    # Turn 1 "Vigil" -> buffer "" -> still forming (agent stays silent, no answer).
    assert dialog.query_has_substance("") is False
    # Turn 2 (in-window, no wake word) is stitched as "vigil " + buffer and routed.
    stitched = "what dosage of amiodarone should i administer to an adult"
    assert dialog.query_has_substance(stitched) is True
    ans = run(f"vigil {stitched}")
    assert ans is not None
    # amiodarone adult is indication-ambiguous -> a clarification, not a miss.
    assert ans.clarification is not None


def test_clarification_reply_vs_fresh_query_discriminator():
    # While a clarification is pending, a bare indication (names no drug) is the
    # REPLY; a turn that names a drug is a FRESH question that abandons it. This is
    # the fix for a stale clarification swallowing the next query.
    assert dialog.turn_is_fresh_query("stable VT") is False
    assert dialog.turn_is_fresh_query("bradycardia") is False
    assert dialog.turn_is_fresh_query("the first one") is False
    assert dialog.turn_is_fresh_query("organophosphate poisoning") is False
    # Fresh questions name a drug:
    assert dialog.turn_is_fresh_query("what dosage of atropine for an adult") is True
    assert dialog.turn_is_fresh_query("epinephrine") is True
    assert dialog.turn_is_fresh_query("how much amiodarone") is True


def test_unknown_drug_with_intent_still_reports_miss(run):
    # Adversarial: a real ask for a drug not in protocol must SAY "not in protocol",
    # never go silent-by-omission. has_intent gates it through to the safe fallback.
    assert dialog.query_has_substance("how much rocuronium for an adult") is True
    ans = run("vigil how much rocuronium for an adult")
    assert ans is not None and ans.found is False
    assert ans.spoken_form == SAFE_FALLBACK_SPOKEN
