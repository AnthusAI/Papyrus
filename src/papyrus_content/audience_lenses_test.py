"""The lens definition and what is generated from it (features_backend/audience-lenses.feature has the narrative)."""

from pathlib import Path

import pytest

from papyrus_content import audience_lenses as lenses

DOC = Path(__file__).resolve().parents[2] / "docs" / "four-lens-review.md"


def test_keys_are_unique_and_prefixed_by_lens():
    keys = [check.key for check in lenses.CHECK_BY_KEY.values()]
    assert len(keys) == sum(len(lens.checks) for lens in lenses.LENSES)
    for lens, prefix in zip(lenses.LENSES, "PASC"):
        assert all(check.key.startswith(prefix) for check in lens.checks)


def test_mirrors_point_at_real_checks_and_point_back():
    for check in lenses.CHECK_BY_KEY.values():
        for other in check.mirrors:
            assert check.key in lenses.CHECK_BY_KEY[other].mirrors, (check.key, other)


def test_exactly_three_failures_are_errors():
    assert [check.key for check in lenses.CHECK_BY_KEY.values() if check.severity == lenses.ERROR] == ["P7", "P10", "A2", "C6"]


def test_every_role_that_is_named_exists_and_each_role_reads_something():
    known = {lenses.COPYWRITER, lenses.EDITOR, lenses.REPORTER}
    assert all(set(check.roles) <= known for check in lenses.CHECK_BY_KEY.values())
    for role in known:
        assert any(role in check.roles for check in lenses.CHECK_BY_KEY.values())


def test_the_reporter_reads_only_research_checks():
    text = lenses.layer_text(lenses.REPORTER)
    assert "Every image has alt text" not in text
    assert "Each outside claim cites a Reference" in text


def test_must_fix_checks_are_marked_in_the_text():
    assert "Every image has alt text; an empty alt counts only as a deliberate decoration (must be fixed before the step can close)" in lenses.layer_text(lenses.COPYWRITER)


def test_documentation_table_is_current():
    text = DOC.read_text(encoding="utf-8")
    assert lenses.docs_with_table(text) == text, "run: python -m papyrus_content.audience_lenses"


def test_lens_named_accepts_key_and_step_and_refuses_unknown():
    assert lenses.lens_named("people") is lenses.lens_named("review_people")
    with pytest.raises(ValueError):
        lenses.lens_named("seo")


def test_done_lens_steps_are_left_out_of_the_lines():
    steps = [line.split("\t")[1] for line in lenses.lens_lines({"review_search": "done"})]
    assert steps == ["review_people", "review_reader_agents", "review_social"]


def test_stored_counts_are_written_with_words():
    line = lenses.lens_lines(counts={"review_people": {"pass": 9, "concern": 2, "problem": 1, "not_assessable": 1}})[0]
    assert "Looks fine: 9\tNeeds a look: 2\tProblem: 1\tCould not check: 1" in line
