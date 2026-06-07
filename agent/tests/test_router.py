from vigil.core.models import Tier
from vigil.core.router import classify, has_intent


def test_has_intent_true_for_real_asks():
    # The medic clearly asked something -- dose lookup or synthesis.
    assert has_intent("how much amiodarone for an adult")
    assert has_intent("what's the dosage")
    assert has_intent("what should i consider before epinephrine")
    assert has_intent("is nitroglycerin contraindicated")
    assert has_intent("give 5 mg")


def test_has_intent_false_for_fragments():
    # Half-formed turns -> the wake state machine keeps listening, never answers.
    assert not has_intent("")
    assert not has_intent("vigil")
    assert not has_intent("what")
    assert not has_intent("stable vt")
    assert not has_intent("epinephrine")  # a NAME, not yet an ask


def test_dose_questions_route_tier1():
    assert classify("what's the adult epinephrine dose for anaphylaxis") == Tier.TIER1_DOSE
    assert classify("how much naloxone for an adult") == Tier.TIER1_DOSE
    assert classify("epinephrine") == Tier.TIER1_DOSE


def test_synthesis_routes_tier2():
    assert classify("what should i consider before epinephrine") == Tier.TIER2_SYNTHESIS
    assert classify("is it safe to give naloxone here") == Tier.TIER2_SYNTHESIS
    assert classify("is epinephrine contraindicated given beta blockers") == Tier.TIER2_SYNTHESIS


def test_broadened_synthesis_phrasings_route_tier2():
    # These synthesis phrasings used to fall through to Tier-1 (-> a pointless
    # dose clarification). They must reach the LLM path now.
    assert classify("what are the considerations for atropine") == Tier.TIER2_SYNTHESIS
    assert classify("any precautions with atropine") == Tier.TIER2_SYNTHESIS
    assert classify("what are the side effects of epinephrine") == Tier.TIER2_SYNTHESIS
    assert classify("tell me about atropine") == Tier.TIER2_SYNTHESIS
    assert classify("what are the risks of giving amiodarone") == Tier.TIER2_SYNTHESIS


def test_dose_question_with_should_i_give_stays_tier1():
    # Live bug: "what dosage ... should I give" was hijacked by the Tier-2
    # "should i give" cue and synthesized by the LLM ("Based on unstable
    # bradycardia..."). Explicit dose nouns must outrank the judgment cue.
    assert classify("what doses of atropine should I give to an adult") == Tier.TIER1_DOSE
    assert classify("What dosage of atropine should I give to an adult") == Tier.TIER1_DOSE
    assert classify("how much epinephrine should I give") == Tier.TIER1_DOSE


def test_should_i_use_judgment_routes_tier2():
    # Live bug: a contraindication/judgment question fell through to Tier-1 and
    # asked a pointless dose clarification instead of synthesizing a caution.
    assert classify("should I use atropine if the patient has a myocardial infarction") == Tier.TIER2_SYNTHESIS
    assert classify("should I give epinephrine to this patient") == Tier.TIER2_SYNTHESIS


def test_dose_queries_never_diverted_to_tier2():
    # SAFETY: the deterministic dose path must never be swallowed by the broadened
    # Tier-2 patterns. Common dose phrasings stay Tier-1.
    for q in (
        "how much atropine for an adult",
        "atropine dose",
        "what dosage of atropine for an adult",
        "give 1 mg of atropine",
        "push amiodarone",
        "epinephrine",
    ):
        assert classify(q) == Tier.TIER1_DOSE, q


def test_unknown():
    assert classify("what's the weather today") == Tier.UNKNOWN
    assert classify("") == Tier.UNKNOWN
