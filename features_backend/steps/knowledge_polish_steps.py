from __future__ import annotations

import copy
import re
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.standard.knowledge import KnowledgeSource  # noqa: E402
from papyrus_content.projection.standard.projector import ASSET_DIRECTORY  # noqa: E402
from procedures.newsroom.tests import knowledge_fixtures as data  # noqa: E402

BEAT_CLASSES = ("papyrus-knowledge-beat-trend", "papyrus-knowledge-beat-entities")


def rule_body(context, name: str) -> str:
    found = re.search(r"\." + re.escape(name) + r"\s*\{([^}]*)\}", context.knowledge_css)
    assert found, f"no rule for .{name}"
    return found.group(1)


@given("the default knowledge stylesheet")
def default_stylesheet(context) -> None:
    context.knowledge_css = (ASSET_DIRECTORY / "papyrus-knowledge.css").read_text(encoding="utf-8")


@then('the "{name}" rule lays its children out in a wrapping flex row with a gap')
def flex_with_gap(context, name: str) -> None:
    body = rule_body(context, name)
    assert "display: flex" in body and "flex-wrap: wrap" in body and "gap:" in body


@then('the "{name}" rule removes the list bullets and the padding')
def no_bullets(context, name: str) -> None:
    body = rule_body(context, name)
    assert "list-style: none" in body and "padding: 0" in body


@then('the beat rules use only "{prefix}" custom properties and no literal colours')
def theme_tokens_only(context, prefix: str) -> None:
    for name in BEAT_CLASSES:
        body = rule_body(context, name)
        assert not re.search(r"var\((?!" + re.escape(prefix) + ")", body)
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", body)


@given("a knowledge source with a store attached")
def source_with_store(context) -> None:
    context.knowledge_source = KnowledgeSource()
    context.knowledge_store = lambda key: None
    other = copy.deepcopy(data.INDEX)
    other["topicCount"] = 97
    context.knowledge_directory = data.write(Path(tempfile.mkdtemp(prefix="knowledge-dir-")) / "local", index=other)


@when("the knowledge directory is chosen and then the store is attached")
def directory_then_store(context) -> None:
    context.knowledge_source.use_directory(context.knowledge_directory)
    context.knowledge_source.attach_store(context.knowledge_store)


@when("the store is attached and then the knowledge directory is chosen")
def store_then_directory(context) -> None:
    context.knowledge_source.attach_store(context.knowledge_store)
    context.knowledge_source.use_directory(context.knowledge_directory)


@then("the snapshot is read from the directory")
def read_from_directory(context) -> None:
    assert context.knowledge_source.index()["topicCount"] == 97
