from vigil.core.aliases import extract_drug, normalize_drug, split_glued_terms


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


def test_split_glued_terms_repairs_stt_gluing():
    # STT drops the space: "epi dose" -> "epidose". We split it back.
    assert split_glued_terms("the adult epidose for anaphylaxis") == "the adult epi dose for anaphylaxis"
    assert split_glued_terms("epinephrinedose") == "epinephrine dose"
    assert split_glued_terms("narcandose") == "narcan dose"
    assert split_glued_terms("d50bolus") == "d50 bolus"


def test_split_glued_terms_no_false_positives():
    # Drug-alias PREFIX + an unknown suffix must be left untouched.
    for s in ("epidural hematoma", "the episode resolved", "epinephrine episode", ""):
        assert split_glued_terms(s) == s
