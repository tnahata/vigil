from vigil.core.wake import detect_wake, strip_wake


def test_detect_wake():
    assert detect_wake("Vigil what's the epi dose")
    assert detect_wake("hey vigil, dose?")
    assert not detect_wake("what's the epi dose")
    assert not detect_wake("")


def test_strip_wake():
    assert strip_wake("Vigil, what's the epi dose") == "what's the epi dose"
    assert strip_wake("no wake here") == "no wake here"
    # restart: takes the query after the LAST wake word
    assert strip_wake("Vigil uh Vigil what's the dose") == "what's the dose"


def test_no_wake_returns_none(run):
    # without the wake word the agent stays silent
    assert run("what's the adult epinephrine dose for anaphylaxis") is None
