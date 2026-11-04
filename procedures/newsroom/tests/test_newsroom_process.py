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
