from vigil.core.models import Tier
from vigil.core.router import classify


def test_dose_questions_route_tier1():
    assert classify("what's the adult epinephrine dose for anaphylaxis") == Tier.TIER1_DOSE
    assert classify("how much naloxone for an adult") == Tier.TIER1_DOSE
    assert classify("epinephrine") == Tier.TIER1_DOSE


def test_synthesis_routes_tier2():
    assert classify("what should i consider before epinephrine") == Tier.TIER2_SYNTHESIS
    assert classify("is it safe to give naloxone here") == Tier.TIER2_SYNTHESIS
    assert classify("is epinephrine contraindicated given beta blockers") == Tier.TIER2_SYNTHESIS


def test_unknown():
    assert classify("what's the weather today") == Tier.UNKNOWN
    assert classify("") == Tier.UNKNOWN
