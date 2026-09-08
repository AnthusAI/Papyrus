from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
FIXTURE_ROOT = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"
ANTHUS_PROFILE_PATH = REPO_ROOT / "publications" / "anthus" / "style-profile.yml"
EDITORIAL_SIGNALS_PATH = REPO_ROOT / "publications" / "anthus" / "editorial-signals.yml"
DENSITY_PROFILE_PATH = FIXTURE_ROOT / "density-enabled-profile.yml"


def _findings_by_kind(diagnosis: dict, kind: str) -> list[dict]:
    findings: list[dict] = []
    for key in ("generic_passages", "unsupported_claims", "voice_observations", "required_facts"):
        findings.extend(entry for entry in diagnosis.get(key, []) if entry.get("kind") == kind)
    return findings


@given("the editorial signals catalog")
def step_given_editorial_signals_catalog(context):
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

    from papyrus_content.editorial_signals import load_editorial_signals_catalog

    context.signals_catalog = load_editorial_signals_catalog(EDITORIAL_SIGNALS_PATH)


@then("it lists lexical density and gzip ratio as implemented")
def step_then_lists_density_signals(context):
    implemented_ids = {signal.id for signal in context.signals_catalog.signals if signal.implemented}
    assert "lexical_density" in implemented_ids
    assert "gzip_ratio" in implemented_ids


@then("it does not list sentence embeddings as a v1 implemented signal")
def step_then_sentence_embeddings_not_implemented(context):
    implemented_ids = {signal.id for signal in context.signals_catalog.signals if signal.implemented}
    assert "sentence_embedding_paraphrase" not in implemented_ids
    signal = next(
        entry for entry in context.signals_catalog.signals if entry.id == "sentence_embedding_paraphrase"
    )
    assert signal.implemented is False


@given("a loadable style profile with information density enabled")
def step_given_density_enabled_profile(context):
    context.profile_path = DENSITY_PROFILE_PATH
    assert context.profile_path.is_file()


@given("a draft of several sentences")
def step_given_density_summary_draft(context):
    context.draft_path = FIXTURE_ROOT / "density-summary-draft.md"
    assert context.draft_path.is_file()


@given("a draft longer than the profile minWords that is padded with function words and repeats")
def step_given_low_density_fluff_draft(context):
    context.profile_path = DENSITY_PROFILE_PATH
    context.draft_path = FIXTURE_ROOT / "low-density-fluff.md"
    assert context.draft_path.is_file()


@given("a must-pass excerpt from an Anth.us reference sample longer than minWords")
def step_given_house_voice_density_excerpt(context):
    context.draft_path = FIXTURE_ROOT / "house-voice-density-excerpt.md"
    assert context.draft_path.is_file()


@given("a draft shorter than the profile minWords")
def step_given_short_density_draft(context):
    context.profile_path = DENSITY_PROFILE_PATH
    context.draft_path = FIXTURE_ROOT / "short-density-draft.md"
    assert context.draft_path.is_file()


@then("the JSON includes density with wordCount, sentenceCount, lexicalDensity, and gzipRatio")
def step_then_density_summary_present(context):
    density = context.diagnosis.get("density")
    assert isinstance(density, dict)
    for key in ("wordCount", "sentenceCount", "lexicalDensity", "gzipRatio"):
        assert key in density


@then("the JSON does not include an embedder field")
def step_then_no_embedder_field(context):
    assert "embedder" not in context.diagnosis
    density = context.diagnosis.get("density")
    if isinstance(density, dict):
        assert "embedder" not in density


@then("there is a low_lexical_density or high_compressibility finding")
def step_then_density_fluff_finding(context):
    kinds = {finding.get("kind") for finding in context.diagnosis.get("generic_passages", [])}
    assert "low_lexical_density" in kinds or "high_compressibility" in kinds


@then("there is no low_lexical_density finding")
def step_then_no_low_lexical_density(context):
    assert not _findings_by_kind(context.diagnosis, "low_lexical_density")


@then("there is no high_compressibility finding")
def step_then_no_high_compressibility(context):
    assert not _findings_by_kind(context.diagnosis, "high_compressibility")
