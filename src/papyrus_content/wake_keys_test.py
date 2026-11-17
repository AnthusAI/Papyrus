import pytest

from papyrus_content import wake_keys as wk


def test_the_three_kinds_of_key_have_the_documented_shapes():
    assert wk.change_key("fact-check", "story-1", "v7", "story.stage_entered") == "fact-check|story-1|v7|story.stage_entered"
    assert wk.schedule_key("rating", "2026-11-17T08:00:00Z") == "rating|schedule|2026-11-17T08:00:00Z"
    assert wk.manual_key("rating", "r-1") == "rating|manual|r-1"
    assert wk.change_key("monitor", "ref-1", None, "monitor.new_reference") == "monitor|ref-1|unversioned|monitor.new_reference"


@pytest.mark.parametrize("key", [wk.change_key("a", "b", "c", "d"), wk.schedule_key("a", "t"), wk.manual_key("a", "r")])
def test_every_built_key_passes_the_check(key):
    assert wk.checked(key) == key


@pytest.mark.parametrize("key", [None, "", "a", "a|b", "a|b|c", "a|schedule|", "a|b|c|", "|b|c|d", "a|b|c|d|e", 3, "a|manual|" + "x" * 1000])
def test_a_malformed_key_is_refused(key):
    with pytest.raises(wk.InvalidWakeKey):
        wk.checked(key)


@pytest.mark.parametrize("build", [lambda: wk.manual_key("a|b", "r"), lambda: wk.manual_key("a", ""), lambda: wk.change_key("a", "s|t", "v", "w"),
                                   lambda: wk.owner(None, ""), lambda: wk.schedule_key("a", None)])
def test_a_part_cannot_hold_the_separator_or_be_empty(build):
    with pytest.raises(wk.InvalidWakeKey):
        build()


def test_the_owner_is_the_automation_or_else_the_procedure():
    assert wk.owner("rating", "newsroom.rate") == "rating"
    assert wk.owner(None, "newsroom.rate") == "procedure:newsroom.rate"
