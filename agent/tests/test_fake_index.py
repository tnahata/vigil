import pytest

from vigil.adapters.fake_index import FakeIndex
from vigil.core.models import Doc

_EPI = "EPINEPHRINE (1:1,000)"


def _docs():
    return [
        Doc("a", "Epinephrine 0.5 mg IM", _EPI, "adult", "anaphylaxis", "0.5 mg", "spoken a", "P1", {}),
        Doc("b", "Epinephrine 1 mg IV", _EPI, "adult", "cardiac_arrest", "1 mg", "spoken b", "P2", {}),
        Doc("c", "Epi peds", _EPI, "pediatric", "anaphylaxis", "0.01 mg/kg", "spoken c", "P3", {}),
    ]


def test_eq_filter_population_namespacing():
    idx = FakeIndex(_docs())
    res = idx.query(
        "epinephrine anaphylaxis",
        alpha=0.0,
        filters={"drug": {"$eq": _EPI}, "population": {"$eq": "adult"}},
    )
    ids = {r.doc.doc_id for r in res}
    assert "c" not in ids  # a peds doc is never returned for an adult query


def test_alias_keyword_match_alpha0_with_indication_tiebreak():
    idx = FakeIndex(_docs())
    res = idx.query(
        "adrenaline for anaphylaxis",  # alias must normalize to the canonical name
        alpha=0.0,
        filters={"drug": {"$eq": _EPI}, "population": {"$eq": "adult"}},
    )
    assert res
    assert res[0].doc.doc_id == "a"  # anaphylaxis beats cardiac_arrest via indication


def test_in_operator():
    idx = FakeIndex(_docs())
    res = idx.query(
        "epinephrine",
        alpha=0.0,
        filters={"drug": {"$eq": _EPI}, "population": {"$in": ["adult", "all"]}},
    )
    assert res and all(r.doc.population == "adult" for r in res)


def test_unsupported_operator_raises():
    idx = FakeIndex(_docs())
    with pytest.raises(NotImplementedError):
        idx.query("epinephrine", alpha=0.0, filters={"drug": {"$regex": "epi"}})
