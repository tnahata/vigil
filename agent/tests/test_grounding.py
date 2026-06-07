from vigil.core.grounding import ungrounded_numbers


def test_grounded_numbers_pass():
    assert ungrounded_numbers("Give 0.3 mg IM", ["Epinephrine 0.3 mg IM"]) == []
    # value match, not substring: "0.30" grounds against "0.3"
    assert ungrounded_numbers("0.30 mg", ["0.3 mg"]) == []
    assert ungrounded_numbers("every 3 to 5 minutes", ["repeat every 3 to 5 minutes"]) == []


def test_ungrounded_numbers_flagged():
    assert ungrounded_numbers("Give 5 mg", ["only 0.3 mg here"]) == ["5"]
    # "1" must NOT be considered grounded by "15"
    assert ungrounded_numbers("give 1 mg", ["dose is 15 mg"]) == ["1"]


def test_no_numbers_is_grounded():
    assert ungrounded_numbers("contact medical control", ["0.3 mg"]) == []
    assert ungrounded_numbers("", ["0.3 mg"]) == []
