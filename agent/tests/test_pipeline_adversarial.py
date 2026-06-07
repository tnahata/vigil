"""The safety money-shot: out-of-protocol / errors must say "contact medical
control" rather than invent a dose -- and never crash.
"""
from vigil.core.errors import SAFE_FALLBACK_SPOKEN
from vigil.core.pipeline import handle_transcript


def test_unknown_drug_returns_safe_fallback(run):
    ans = run("Vigil, what's the adult dose of unobtainium for anaphylaxis")
    assert ans is not None
    assert ans.found is False
    assert ans.spoken_form == SAFE_FALLBACK_SPOKEN
    assert ans.card["found"] is False


def test_known_drug_wrong_population_returns_fallback(run):
    # naloxone is adult-only in the gold set; a peds query has no row
    ans = run("Vigil, what's the pediatric naloxone dose for opioid overdose")
    assert ans is not None and ans.found is False


def test_injected_index_error_degrades_safely():
    class BoomIndex:
        def query(self, *a, **k):
            raise RuntimeError("moss exploded")

    ans = handle_transcript("Vigil, adult epinephrine dose for anaphylaxis", index=BoomIndex())
    assert ans is not None
    assert ans.found is False
    assert ans.spoken_form == SAFE_FALLBACK_SPOKEN


def test_fallback_card_carries_no_invented_dose(run):
    ans = run("Vigil, what's the adult dose of unobtainium for anaphylaxis")
    assert "dose" not in ans.card  # no number is ever fabricated
