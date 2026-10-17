from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.convert_bodies_commands import convert_bodies  # noqa: E402
from papyrus_content.markus_renderer.derive import plain_paragraphs  # noqa: E402


class InMemoryAuthoringClient:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self.updates: list[dict] = []

    def list_records(self, model_name: str) -> list[dict]:
        return list(self.records) if model_name == "Item" else []

    def list_by_index(self, index_name: str, key_value: str, *, limit: int = 100) -> list[dict]:
        return []

    def update_record(self, model_name: str, input_payload: dict) -> None:
        self.updates.append(input_payload)


@given('an article whose body paragraphs are "{first}" and "{second}"')
def article_with_two_paragraphs(context, first: str, second: str) -> None:
    context.client = InMemoryAuthoringClient([{"id": "item-a", "slug": "a", "type": "article", "body": [first, second]}])


@given('an article whose body paragraphs are "{only}"')
def article_with_one_paragraph(context, only: str) -> None:
    context.client = InMemoryAuthoringClient([{"id": "item-a", "slug": "a", "type": "article", "body": [only]}])


@when("I convert the bodies and apply the changes")
def convert_and_apply(context) -> None:
    context.rows = convert_bodies(context.client, ["Item"], apply=True)


@then("the article is converted")
def article_is_converted(context) -> None:
    assert context.rows[0]["status"] == "converted", context.rows


@then("the stored Markus body escapes the special characters")
def markus_body_is_escaped(context) -> None:
    assert context.client.updates[0]["bodyMarkus"] == "Cats & dogs: \\*stars\\*\n\n\\# not a heading"


@then('the stored IR paragraphs are "{first}" and "{second}"')
def ir_paragraphs_match(context, first: str, second: str) -> None:
    envelope = json.loads(context.client.updates[0]["bodyIr"])
    assert plain_paragraphs(envelope) == [first, second], plain_paragraphs(envelope)


@then('the article is reported as "{status}"')
def article_is_reported(context, status: str) -> None:
    assert context.rows[0]["status"] == status, context.rows


@then("nothing is written")
def nothing_is_written(context) -> None:
    assert context.client.updates == []
