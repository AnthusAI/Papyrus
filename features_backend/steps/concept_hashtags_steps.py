"""Concept hashtags (features_backend/concept-hashtags.feature)."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.knowledge_snapshot.keys import concept_hashtag, concept_hashtag_label, concept_keys_for_hashtag  # noqa: E402


@given('the concept keys "{first}" and "{second}"')
def step_keys(context, first, second):
    context.concept_keys = [first, second]


@then('the hashtag of "{key}" is "{hashtag}"')
def step_hashtag(context, key, hashtag):
    assert concept_hashtag(key) == hashtag


@then('the hashtag of "{key}" is shown as "{label}"')
def step_label(context, key, label):
    assert concept_hashtag_label(key, context.concept_keys) == label


@then('typing "{text}" finds "{first}" and "{second}"')
def step_finds_two(context, text, first, second):
    assert concept_keys_for_hashtag(text, context.concept_keys) == [first, second]


@then('typing "{text}" finds "{key}"')
def step_finds_one(context, text, key):
    assert concept_keys_for_hashtag(text, context.concept_keys) == [key]
