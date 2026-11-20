"""features_backend/translation/localize-blocks.feature: how a body is cut into the blocks a translation works on."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from papyrus_content.localize.blocks import split_body  # noqa: E402

DIRECTIVE = '::image{\n  src="a.png"\n \n  alt="A picture."\n  credit="Drafted by AI."\n}'


@given("a body with a picture directive whose attributes have a blank line inside")
def step_body(context):
    context.body = f"Before.\n\n{DIRECTIVE}\n\nAfter.\n"


@when("the body is cut into blocks")
def step_cut(context):
    context.blocks = split_body(context.body)


@then("the picture directive is one block, whole, between the two paragraphs")
def step_whole(context):
    assert context.blocks == ["Before.", DIRECTIVE, "After."], context.blocks
