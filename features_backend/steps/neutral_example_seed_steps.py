from __future__ import annotations

from pathlib import Path

import yaml
from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPORA = REPO_ROOT / "corpora"
FORBIDDEN = ("threat", "security", "attacker", "defender", "anthus", "ai/ml", "cloud")


def _text(*names: str) -> str:
    return "\n".join((CORPORA / name).read_text(encoding="utf-8") for name in names).lower()


@given("the bundled example mission, policy and sections")
def given_bundled_example(context):
    context.example_names = ("example-publication-doctrine.yml", "example-newsroom-sections.yml")


@then("none of them names a publication or a security subject")
def then_example_is_neutral(context):
    text = _text(*context.example_names)
    for word in FORBIDDEN:
        assert word not in text, f"the bundled example mentions {word!r}"


@then("the sections are neutral news, analysis and explainer sections")
def then_example_sections(context):
    parsed = yaml.safe_load((CORPORA / "example-newsroom-sections.yml").read_text(encoding="utf-8"))
    assert [section["id"] for section in parsed["sections"]] == ["news", "analysis", "explainers"]


@given("the Threat Intelligence mission, policy and sections")
def given_ti(context):
    context.ti_names = ("threat-intelligence-publication-doctrine.yml", "threat-intelligence-newsroom-sections.yml")
    for name in context.ti_names:
        assert (CORPORA / name).is_file(), name


@then("they are separate files from the bundled example files")
def then_ti_separate(context):
    assert _text(*context.ti_names) != _text("example-publication-doctrine.yml", "example-newsroom-sections.yml")
    assert "threat" in _text(*context.ti_names)


@then("the command line default for sections and doctrine is the neutral example")
def then_defaults(context):
    from papyrus_content.newsroom_doctrine import DEFAULT_PUBLICATION_DOCTRINE_PATH
    from papyrus_content.newsroom_sections import DEFAULT_NEWSROOM_SECTIONS_PATH

    assert Path(DEFAULT_PUBLICATION_DOCTRINE_PATH).name == "example-publication-doctrine.yml"
    assert Path(DEFAULT_NEWSROOM_SECTIONS_PATH).name == "example-newsroom-sections.yml"
