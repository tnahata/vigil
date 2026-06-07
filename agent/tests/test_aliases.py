from vigil.core.aliases import extract_drug, normalize_drug


def test_normalize_known_aliases():
    assert normalize_drug("adrenaline") == "epinephrine"
    assert normalize_drug("EPI") == "epinephrine"
    assert normalize_drug("epinephrine") == "epinephrine"
    assert normalize_drug("narcan") == "naloxone"
    assert normalize_drug("glucose") == "dextrose"


def test_normalize_unknown():
    assert normalize_drug("unobtainium") is None
    assert normalize_drug("") is None
    assert normalize_drug(None) is None


def test_extract_drug_from_query():
    assert extract_drug("Vigil what's the adrenaline dose") == "epinephrine"
    assert extract_drug("how much narcan for an adult") == "naloxone"
    assert extract_drug("what's the weather") is None
