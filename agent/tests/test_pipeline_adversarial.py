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


def test_pediatric_query_never_returns_adult_dose(run):
    # Every protocol drug has both populations, so the safety property is
    # isolation: a pediatric query must surface the PEDIATRIC chunk, never the
    # adult dose (a wrong-population dose can be fatal).
    ans = run("Vigil, what's the pediatric epinephrine dose for anaphylaxis")
    assert ans is not None
    if ans.found:
        assert ans.card["population"] == "pediatric"
        assert ans.doc_id == "epinephrine-11000-anaphylaxis-pediatric-0"


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
