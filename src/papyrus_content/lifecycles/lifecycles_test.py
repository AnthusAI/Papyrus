import copy

import pytest
import yaml

from papyrus_content import lifecycles
from papyrus_content.lifecycles import LifecycleError, load, names, parse, problems_of

VALID = yaml.safe_load("""
schemaVersion: 1
record: Thing
title: Thing
summary: A thing.
stages:
  - id: made
    title: Made
    mover: intake
    person: never
    nobodyActs: {kind: moves_on, text: Nothing waits.}
""")


def changed(**stage):
    raw = copy.deepcopy(VALID)
    raw["stages"][0].update(stage)
    return raw


@pytest.mark.parametrize("record", names())
def test_every_lifecycle_file_is_valid_and_loads(record):
    lifecycle = load(record)
    assert lifecycle.record == record and lifecycle.stages
    assert lifecycles.describe(record).startswith(f"{lifecycle.title} lifecycle.")


def test_a_valid_file_has_no_problems():
    assert problems_of(VALID) == []
    assert parse(VALID).stages[0].mover == "intake"


@pytest.mark.parametrize("stage, fragment", [
    ({"mover": "an editor"}, "not a responsibility in the catalog"),
    ({"mover": "person"}, "a person is never a stage's mover"),
    ({"person": "sometimes"}, "person must be one of"),
    ({"person": "by_policy"}, "names the rung below which a person is asked"),
    ({"person": "by_policy", "rung": "sometimes"}, "names the rung below which a person is asked"),
    ({"rung": "propose"}, "only a stage asked by policy names a rung"),
    ({"person": "always"}, "says why"),
    ({"nobodyActs": {"kind": "spikes", "text": "It is spiked after a month."}}, "no kind removes, spikes or rejects"),
    ({"nobodyActs": {"kind": "stays", "text": "It stays."}}, "must be true"),
    ({"nobodyActs": {"kind": "moves_on", "counted": True, "text": "x"}}, "only a record that stays is counted"),
    ({"nobodyActs": {"kind": "retries", "text": "x"}}, "says what follows its failure"),
    ({"nobodyActs": {"kind": "moves_on", "then": "flags", "text": "x"}}, "only a retry names what follows it"),
    ({"nobodyActs": {"kind": "moves_on"}}, "says in words what happens"),
    ({"surprise": 1}, "unknown key"),
])
def test_a_stage_that_breaks_a_rule_is_refused_with_the_reason(stage, fragment):
    assert any(fragment in problem for problem in problems_of(changed(**stage))), problems_of(changed(**stage))
    with pytest.raises(LifecycleError, match="breaks"):
        parse(changed(**stage))


def test_every_problem_is_named_not_only_the_first():
    raw = changed(mover="an editor", person="sometimes")
    assert len(problems_of(raw)) == 2


def test_a_duplicate_stage_id_is_refused():
    raw = copy.deepcopy(VALID)
    raw["stages"].append(copy.deepcopy(raw["stages"][0]))
    assert any("used twice" in problem for problem in problems_of(raw))


def test_an_unknown_record_is_refused():
    with pytest.raises(LifecycleError, match="no lifecycle"):
        load("Nonsense")


def test_stages_where_a_record_waits_for_a_person():
    reference = load("Reference")
    assert [stage.id for stage in reference.waiting] == ["captured", "predicted", "decided", "rated", "grouped"]
    assert [stage.id for stage in reference.stages if stage not in reference.waiting] == ["collected", "delivered"]
