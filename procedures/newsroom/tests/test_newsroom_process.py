"""The Story procedure definition (PPY-c63c9f): the doc table lists every step, and assess is pure over facts."""
from pathlib import Path

from papyrus_content import newsroom_process as process

DOC = Path(__file__).resolve().parents[3] / "docs" / "story-procedure.md"


def facts(stage="reporting", **changes):
    base = {"lineage": "s1", "stage": stage, "versionId": "s1-v1", "versionNumber": 1, "body": "", "metadata": {}, "assignments": [],
            "checkRun": None, "checkRunError": False}
    return {**base, **changes}


def test_every_step_key_is_in_the_doc_table():
    rows = {line.split("|")[1].strip() for line in DOC.read_text(encoding="utf-8").splitlines() if line.startswith("|")}
    assert [step.key for step in process.STEPS if step.key not in rows] == []


def test_not_built_steps_are_never_done():
    states = {row["key"]: row["state"] for row in process.assess(facts("published"))["steps"]}
    assert states["fact_check"] == states["illustration"] == states["typesetting"] == "unknown"


def test_held_and_spiked_have_no_next_step():
    assert process.assess(facts("held"))["next"] is None
    assert process.assess(facts("spiked"))["next"] is None


def test_next_lines_for_an_idea():
    lines = process.next_lines(process.assess(facts("idea")))
    assert lines[0].split("\t")[:2] == ["next", "choose"]


def test_recorded_version_is_recorded_inferred_from_time_or_unknown():
    times = {1: "2026-11-03T09:01:00Z", 2: "2026-11-03T10:00:00Z", 3: "2026-11-03T11:00:00Z"}
    assert process.recorded_version({"storyVersion": 2, "changedAt": "2026-11-03T11:30:00Z"}, times) == (2, "recorded")
    assert process.recorded_version({"changedAt": "2026-11-03T10:30:00Z"}, times) == (2, "inferred from the time it was recorded")
    assert process.recorded_version({"changedAt": "2026-11-03T08:00:00Z"}, times) == (None, "unknown")
    assert process.recorded_version({}, times) == (None, "unknown")


def test_an_unknown_version_of_a_done_review_is_stale_and_a_skipped_one_is_not():
    facts = {"lineage": "s", "stage": "copywriting", "versionId": "s-v3", "versionNumber": 3, "body": "x", "metadata": {}, "assignments": [], "checkRun": None,
             "checkRunError": False, "versionTimes": {3: "2026-11-03T11:00:00Z"}}
    stored = [{"stepKey": "review_people", "state": "done", "changedAt": "2026-11-03T08:00:00Z"},
              {"stepKey": "review_search", "state": "skipped", "changedAt": "2026-11-03T08:00:00Z"}]
    resolved = process.resolve(process.assess(facts), stored, facts)
    rows = {row["key"]: row for row in resolved["steps"]}
    assert rows["review_people"]["state"] == "stale" and "unknown version" in rows["review_people"]["freshness"]
    assert rows["review_search"]["state"] == "skipped"
    assert [row["key"] for row in resolved["stale"]] == ["review_people"]
    assert resolved["status"] == "blocked"   # other required steps are open
