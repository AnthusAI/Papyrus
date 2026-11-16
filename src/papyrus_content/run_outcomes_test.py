import pytest

from papyrus_content import run_outcomes as ro


@pytest.mark.parametrize("output, expected", [
    ({"title": "x"}, ("acted", None)),
    (None, ("acted", None)),
    ({"run_outcome": "nothing", "run_outcome_reason": "no_new_filing"}, ("nothing", "no_new_filing")),
    ({"run_outcome": "asked", "run_outcome_reason": "needs_editor"}, ("asked", "needs_editor")),
])
def test_declared_outcomes(output, expected):
    assert ro.declared_outcome(output) == expected


@pytest.mark.parametrize("output", [
    {"run_outcome": "nothing"}, {"run_outcome": "unknown", "run_outcome_reason": "lost"},
    {"run_outcome": "failed", "run_outcome_reason": "x_y"}, {"run_outcome": "nothing", "run_outcome_reason": "No Reason"},
])
def test_invalid_declarations_are_refused(output):
    with pytest.raises(ro.InvalidOutcome):
        ro.declared_outcome(output)


def test_a_run_that_cannot_finish_is_failed():
    assert ro.finished_outcome(False, None, "timed out after 5 s")["outcomeReason"] == "timed_out"
    assert ro.finished_outcome(False, None, "boom")["outcomeReason"] == "procedure_error"


def test_every_outcome_has_a_word_and_a_mark():
    for outcome in ro.OUTCOMES:
        mark, words = ro.OUTCOME_SHOWN[outcome]
        assert mark and words
    assert ro.outcome_shown({"runStatus": "completed"}) == ro.BEFORE_OUTCOMES
