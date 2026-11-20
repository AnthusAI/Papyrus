"""Steps are found by their opening words, and the answer is always the one stock behave gives.

features/ci-behave-side-by-side.feature tells the story in prose.
"""
from __future__ import annotations

import importlib.util
from collections import namedtuple
from pathlib import Path

import pytest
from behave.step_registry import AmbiguousStep, StepRegistry

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "step_registry_indexed_by_opening_words", ROOT / "features_backend" / "step_registry_indexed_by_opening_words.py"
)
indexed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(indexed)

StepInAFeature = namedtuple("StepInAFeature", "step_type name")

DEFINITIONS_IN_REGISTRATION_ORDER = [
    ("given", "a published Story {slug}"),
    ("given", "a draft Story {slug} at version {version:d}"),
    ("given", "{count:d} References are pending"),
    ("when", "the editor publishes {slug}"),
    ("when", "the editor saves"),
    ("then", "the Story is live"),
    ("then", "the Story {slug} is live"),
    ("then", "{count:d} readers are told"),
    ("step", "the clock reads {time}"),
    ("step", "{count:d} minutes pass"),
]

STEPS_A_FEATURE_MIGHT_USE = [
    StepInAFeature("given", "a published Story slow-water"),
    StepInAFeature("given", "a draft Story slow-water at version 3"),
    StepInAFeature("given", "12 References are pending"),
    StepInAFeature("given", "the clock reads noon"),
    StepInAFeature("given", "5 minutes pass"),
    StepInAFeature("when", "the editor publishes slow-water"),
    StepInAFeature("when", "the editor saves"),
    StepInAFeature("when", "the editor sleeps"),
    StepInAFeature("then", "the Story is live"),
    StepInAFeature("then", "the Story slow-water is live"),
    StepInAFeature("then", "4 readers are told"),
    StepInAFeature("then", "nothing anyone defined"),
    StepInAFeature("step", "the clock reads noon"),
]


def registry_holding(registry_class, definitions):
    registry = registry_class()
    for number, (step_type, pattern) in enumerate(definitions):
        registry.add_step_definition(step_type, pattern, eval(f"lambda context, **arguments: {number}"))
    return registry


def test_every_step_finds_the_definition_stock_behave_finds():
    stock = registry_holding(StepRegistry, DEFINITIONS_IN_REGISTRATION_ORDER)
    by_opening_words = registry_holding(indexed.StepRegistryIndexedByOpeningWords, DEFINITIONS_IN_REGISTRATION_ORDER)
    for step in STEPS_A_FEATURE_MIGHT_USE:
        stock_definition = stock.find_step_definition(step)
        indexed_definition = by_opening_words.find_step_definition(step)
        assert (stock_definition and stock_definition.pattern) == (indexed_definition and indexed_definition.pattern), step
        assert bool(stock.find_match(step)) == bool(by_opening_words.find_match(step))


@pytest.mark.parametrize(
    "earlier_pattern, later_pattern",
    [
        ("a Story named {name} is saved", "a Story named slow-water is saved"),
        ("{count:d} References are pending", "3 References are pending"),
        ("The Story is live", "The Story is live"),
    ],
)
def test_a_definition_an_earlier_one_already_matches_is_still_refused(earlier_pattern, later_pattern):
    for registry_class in (StepRegistry, indexed.StepRegistryIndexedByOpeningWords):
        registry = registry_class()
        registry.add_step_definition("given", earlier_pattern, lambda context: None)
        with pytest.raises(AmbiguousStep):
            registry.add_step_definition("given", later_pattern, lambda context: None)


def test_the_same_definition_loaded_twice_is_kept_once():
    registry = indexed.StepRegistryIndexedByOpeningWords()

    def the_editor_saves(context):
        return None

    registry.add_step_definition("when", "the editor saves", the_editor_saves)
    registry.add_step_definition("when", "the editor saves", the_editor_saves)
    assert len(registry.steps["when"]) == 1


def test_a_definition_for_a_given_step_is_tried_before_one_for_any_step():
    registry = indexed.StepRegistryIndexedByOpeningWords()
    registry.add_step_definition("step", "the clock reads {time}", lambda context, time: "any step")
    registry.add_step_definition("given", "the clock reads noon", lambda context: "given")
    assert registry.find_step_definition(StepInAFeature("given", "the clock reads noon")).pattern == "the clock reads noon"
    assert registry.find_step_definition(StepInAFeature("then", "the clock reads noon")).pattern == "the clock reads {time}"


def test_a_registry_cleared_by_behave_forgets_its_definitions():
    registry = registry_holding(indexed.StepRegistryIndexedByOpeningWords, DEFINITIONS_IN_REGISTRATION_ORDER)
    registry.clear()
    assert registry.find_step_definition(StepInAFeature("when", "the editor saves")) is None
    registry.add_step_definition("when", "the editor saves", lambda context: None)
    assert registry.find_step_definition(StepInAFeature("when", "the editor saves")) is not None


def test_the_backend_features_load_the_lookup_before_any_step_file():
    environment = (ROOT / "features_backend" / "environment.py").read_text()
    assert "step_registry_indexed_by_opening_words.py" in environment
    assert environment.index("_look_steps_up_by_opening_words()\n\n\ndef before_all") > 0
