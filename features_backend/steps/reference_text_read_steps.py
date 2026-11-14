from __future__ import annotations

from unittest.mock import patch

from behave import given, then, when

from papyrus_content import reference_text_read as module


def _card(truncated):
    return {"capture": {"status": "completed", "sourceKind": "html", "capturedAt": "2026-11-01T00:00:00Z", "via": "direct"},
            "signals": {"responseTruncated": truncated}, "current": {"textSortKey": "curation-text"}}


@given("a Reference whose captured text is {count:d} characters long and was cut at the size guard")
def step_long(context, count):
    context.card, context.stored_text = _card(True), "x" * count


@given("a Reference with no captured text")
def step_none(context):
    context.card, context.stored_text = {"capture": {"status": "failed", "reason": "blocked"}, "signals": {}}, None


def _read(context, offset, limit):
    context.result, context.missing = None, None
    with patch.object(module, "current_reference", lambda client, rid: {"id": rid, "sourceUri": "https://example.test/"}), \
            patch.object(module, "read_card", lambda client, ref: context.card), \
            patch.object(module, "current_text", lambda card, ref, store: context.stored_text):
        try:
            context.result = module.read_reference_text(object(), "ref-1", offset=offset, limit=limit)
        except module.NoCapturedText as error:
            context.missing = error


@when("an agent reads its text from offset {offset:d} with a limit of {limit:d}")
def step_read(context, offset, limit):
    _read(context, offset, limit)


@when("an agent reads its text from offset {offset:d} with no limit")
def step_read_all(context, offset):
    _read(context, offset, 0)


@then("it receives {count:d} characters, the total {total:d}, truncated yes, and the next offset {next_offset:d}")
def step_slice(context, count, total, next_offset):
    result = context.result
    assert (result["returnedCharacters"], result["totalCharacters"], result["truncated"], result["nextOffset"]) == (count, total, True, next_offset), result


@then("it receives {count:d} characters and no next offset")
def step_end(context, count):
    assert context.result["returnedCharacters"] == count and context.result["nextOffset"] is None, context.result


@then("the read reports that nothing was captured")
def step_missing(context):
    assert context.missing is not None and context.missing.details["captureReason"] == "blocked", context.missing
