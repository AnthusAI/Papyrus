from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.editorial_style import (  # noqa: E402
    DEFAULT_ANTHUS_STYLE_PROFILE_PATH,
    LoadedStyleProfile,
    StyleProfileValidationError,
    load_style_profile,
)


@given("a publication has an editable style profile on disk")
def step_given_publication_style_profile(context):
    context.style_profile_path = DEFAULT_ANTHUS_STYLE_PROFILE_PATH
    assert context.style_profile_path.is_file(), f"missing profile: {context.style_profile_path}"


@given(
    "the profile names voice, audience, tone, sentence style, structure, prefer and avoid lexicon, and evidence rules"
)
def step_given_profile_names_required_fields(context):
    import yaml

    raw = yaml.safe_load(context.style_profile_path.read_text(encoding="utf-8"))
    voice = raw.get("voice") or {}
    lexicon = raw.get("lexicon") or {}
    assert voice.get("name")
    assert raw.get("audience")
    assert raw.get("tone")
    assert raw.get("sentenceStyle")
    assert raw.get("structure")
    assert lexicon.get("prefer")
    assert lexicon.get("avoid")
    assert raw.get("evidenceRules")


@given("five to ten approved reference samples are linked for voice match")
def step_given_reference_samples_linked(context):
    import yaml

    raw = yaml.safe_load(context.style_profile_path.read_text(encoding="utf-8"))
    refs = raw.get("referenceSamples") or []
    assert 5 <= len(refs) <= 10


@when("an editorial pass loads the profile")
def step_when_editorial_pass_loads_profile(context):
    context.loaded = load_style_profile(context.style_profile_path)


@then("the loader returns the profile and the linked samples")
def step_then_loader_returns_profile_and_samples(context):
    loaded = context.loaded
    assert isinstance(loaded, LoadedStyleProfile)
    assert loaded.profile.publication_key == "anthus-blog"
    assert len(loaded.samples) == len(loaded.profile.reference_sample_refs)
    for sample in loaded.samples:
        assert sample.id
        assert sample.title
        assert sample.url.startswith("https://anth.us/blog/")
        assert sample.path.is_file()
        assert sample.body.strip()


@then("the profile does not contain detector scores")
def step_then_profile_has_no_detector_scores(context):
    import re

    import yaml

    from papyrus_content.editorial_style import _FORBIDDEN_KEY_PATTERN

    raw = yaml.safe_load(context.style_profile_path.read_text(encoding="utf-8"))

    def walk(value, key_path=""):
        if isinstance(value, dict):
            for key, nested in value.items():
                key_text = str(key)
                current_path = f"{key_path}.{key_text}" if key_path else key_text
                normalized = re.sub(r"[^a-z0-9]", "", key_text.lower())
                assert not _FORBIDDEN_KEY_PATTERN.search(normalized), current_path
                walk(nested, current_path)
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{key_path}[{index}]")

    walk(raw)


@given("a style profile that includes a detector score")
def step_given_profile_with_detector_score(context):
    context.style_profile_path = (
        REPO_ROOT / "features_backend" / "fixtures" / "editorial-style-profile" / "invalid-detector-score.yml"
    )
    context.load_error = None


@when("an editorial pass tries to load the profile")
def step_when_editorial_pass_tries_to_load_profile(context):
    try:
        context.loaded = load_style_profile(context.style_profile_path)
    except StyleProfileValidationError as exc:
        context.load_error = exc
        context.loaded = None


@then("loading fails with a validation error")
def step_then_loading_fails_with_validation_error(context):
    assert context.loaded is None
    assert isinstance(context.load_error, StyleProfileValidationError)
    assert "validation" in str(context.load_error).lower() or "forbidden" in str(context.load_error).lower()
