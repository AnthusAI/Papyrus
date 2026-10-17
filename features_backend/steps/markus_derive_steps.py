from __future__ import annotations

import sys
from pathlib import Path

from behave import then, when

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.markus_renderer import derive_body  # noqa: E402

CITATION_FRONT_MATTER = "citations:\n  a:\n    type: webpage\n    title: Source A\n"


@when("I derive the body of an article with a paragraph and a citation")
def derive_valid_article(context) -> None:
    context.derivation = derive_body(CITATION_FRONT_MATTER, "\nA claim [@a].\n\n::citations{format=\"apa\"}\n")


@when('I derive the body of an article using the directive "{name}"')
def derive_unknown_directive(context, name: str) -> None:
    context.derivation = derive_body("", f":::{name}\nText.\n:::\n")


@when("I derive the body of an article citing a missing key")
def derive_missing_citation(context) -> None:
    context.derivation = derive_body(CITATION_FRONT_MATTER, "See [@missing].\n")


@when('I derive the body of an article with the image source "{source}"')
def derive_unsafe_image(context, source: str) -> None:
    context.derivation = derive_body("", f'::image{{src="{source}"}}\n')


@then("the derivation is ok")
def derivation_is_ok(context) -> None:
    assert context.derivation.ok, context.derivation.errors


@then("the envelope has schema version 1 and one paragraph block")
def envelope_shape(context) -> None:
    envelope = context.derivation.body_ir
    assert envelope["schemaVersion"] == 1
    assert envelope["document"]["schema_version"] == 1
    paragraphs = [b for b in envelope["document"]["children"] if b["type"] == "paragraph"]
    assert len(paragraphs) >= 1


@then("the bibliography has {count:d} entry")
def bibliography_size(context, count: int) -> None:
    assert len(context.derivation.body_ir["papyrus"]["bibliography"]) == count


@then('the derivation fails with code "{code}"')
def derivation_fails(context, code: str) -> None:
    assert not context.derivation.ok
    assert context.derivation.errors[0].code == code, context.derivation.errors


@then("no body IR is produced")
def no_body_ir(context) -> None:
    assert context.derivation.body_ir is None
