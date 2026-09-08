from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
FIXTURE_ROOT = REPO_ROOT / "features_backend" / "fixtures" / "editorial-diagnosis"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.editorial_diagnosis import diagnose_draft
from papyrus_content.editorial_embedders import SentenceEmbedder
from papyrus_content.editorial_style import load_style_profile


class FakeEmbedder(SentenceEmbedder):
    def __init__(self, vectors: list[list[float]], embedder_id: str = "fake-test-embedder") -> None:
        self._vectors = vectors
        self._embedder_id = embedder_id

    @property
    def embedder_id(self) -> str:
        return self._embedder_id

    def embed(self, sentences: tuple[str, ...]) -> list[list[float]]:
        if len(sentences) != len(self._vectors):
            raise ValueError("FakeEmbedder vector count does not match sentence count.")
        return [list(vector) for vector in self._vectors]


def _shared_four_word_shingles(sentences: list[str]) -> set[str]:
    shingles: list[set[str]] = []
    for sentence in sentences:
        words = re.findall(r"[A-Za-z0-9']+", sentence.lower())
        shingles.append({" ".join(words[index : index + 4]) for index in range(len(words) - 3)})
    shared = shingles[0]
    for other in shingles[1:]:
        shared &= other
    return shared


def _concept_restatement_groups(diagnosis: dict) -> list[dict]:
    return [group for group in diagnosis.get("repetition_groups", []) if group.get("kind") == "concept_restatement"]


def _redundancy_groups(diagnosis: dict) -> list[dict]:
    return [group for group in diagnosis.get("repetition_groups", []) if group.get("kind") == "redundancy"]


@given(
    "a draft that states the same claim three times in different words with no repeated four-word phrase"
)
def step_given_paraphrase_draft(context):
    context.draft_path = FIXTURE_ROOT / "paraphrase-triple.md"
    draft_text = context.draft_path.read_text(encoding="utf-8")
    from papyrus_content.editorial_text import sentence_spans

    sentences = [sentence for sentence, _, _ in sentence_spans(draft_text)]
    assert _shared_four_word_shingles(sentences) == set()


@given("a loadable style profile with semantic restatement enabled")
def step_given_semantic_restatement_profile(context):
    context.profile_path = FIXTURE_ROOT / "style-profile.yml"
    context.style_profile = load_style_profile(context.profile_path)


@given("a draft that repeats the same four-word phrase in two sentences")
def step_given_verbatim_repeat_draft(context):
    context.draft_path = FIXTURE_ROOT / "verbatim-repeat.md"
    context.profile_path = FIXTURE_ROOT / "style-profile.yml"


@given("a style profile with semantic restatement disabled")
def step_given_semantic_restatement_disabled_profile(context):
    context.profile_path = FIXTURE_ROOT / "semantic-restatement-off-profile.yml"
    context.style_profile = load_style_profile(context.profile_path)


@given("a paraphrase draft")
def step_given_paraphrase_draft_short(context):
    context.draft_path = FIXTURE_ROOT / "paraphrase-triple.md"
    if not getattr(context, "profile_path", None):
        context.profile_path = FIXTURE_ROOT / "style-profile.yml"


@when("I run the diagnose command with an injected embedder that places those sentences in one cluster")
def step_when_diagnose_with_injected_embedder(context):
    draft_text = context.draft_path.read_text(encoding="utf-8")
    from papyrus_content.editorial_text import sentence_spans

    sentence_count = len(sentence_spans(draft_text))
    embedder = FakeEmbedder([[1.0, 0.0, 0.0]] * sentence_count)
    context.diagnosis = diagnose_draft(
        draft_text,
        style_profile=context.style_profile,
        embedder=embedder,
    )


@then("there is a concept_restatement group with at least three member sentences")
def step_then_concept_restatement_group(context):
    groups = _concept_restatement_groups(context.diagnosis)
    assert groups, "expected a concept_restatement group"
    assert any(len(group.get("members", [])) >= 3 for group in groups)


@then("that group is not justified only by four-word shingles")
def step_then_not_only_shingles(context):
    redundancy_spans = {
        (member["span"]["start"], member["span"]["end"])
        for group in _redundancy_groups(context.diagnosis)
        for member in group.get("members", [])
    }
    for group in _concept_restatement_groups(context.diagnosis):
        member_spans = {(member["span"]["start"], member["span"]["end"]) for member in group["members"]}
        assert member_spans - redundancy_spans, group


@then("those sentences are a redundancy group")
def step_then_redundancy_group(context):
    groups = _redundancy_groups(context.diagnosis)
    assert groups, "expected a redundancy group"
    assert any(len(group.get("members", [])) >= 2 for group in groups)


@then("they are not also a concept_restatement group")
def step_then_not_concept_restatement(context):
    assert not _concept_restatement_groups(context.diagnosis)


@then("there is no concept_restatement group")
def step_then_no_concept_restatement(context):
    assert not _concept_restatement_groups(context.diagnosis)
