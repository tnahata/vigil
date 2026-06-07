from vigil.core.trace import StageTimer


def test_stage_timer_records_timing():
    sink = []
    with StageTimer("demo", sink=sink) as st:
        st.note(foo="bar")
    assert len(sink) == 1
    assert sink[0].stage == "demo"
    assert sink[0].ms >= 0.0


def test_stage_timer_records_on_exception():
    sink = []
    try:
        with StageTimer("boom", sink=sink):
            raise ValueError("x")
    except ValueError:
        pass
    assert len(sink) == 1 and sink[0].stage == "boom"


def test_pipeline_emits_per_stage_timings(run):
    ans = run("Vigil, what's the adult epinephrine dose for anaphylaxis")
    stages = [t.stage for t in ans.timings]
    for expected in ("wake", "route", "normalize", "retrieve", "answer"):
        assert expected in stages, f"missing stage timing: {expected}"
    assert all(t.ms >= 0.0 for t in ans.timings)
