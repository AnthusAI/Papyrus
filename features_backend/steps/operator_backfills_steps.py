"""Steps for features_backend/operator-backfills.feature. Everything is in memory: no network, no AWS."""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import newsroom_commands, references_commands  # noqa: E402
from papyrus_content.operator_errors import OperatorError  # noqa: E402

HANDLERS = {
    "references backfill-medium": (references_commands, "references_backfill_medium", ["--site", "demo"]),
    "references backfill-public-fields": (references_commands, "references_backfill_public_fields", ["--site", "demo"]),
    "references backfill-feed-keys": (references_commands, "references_backfill_feed_keys", ["--site", "demo"]),
    "references backfill-reviewed-feed-key": (references_commands, "references_backfill_reviewed_feed_key", []),
    "references backfill-corpus-storage-paths": (references_commands, "references_backfill_corpus_storage_paths", []),
    "sections backfill-feed-fields": (newsroom_commands, "newsroom_backfill_feed_fields", []),
    "sections backfill-operational-indexes": (newsroom_commands, "newsroom_backfill_operational_indexes", []),
}


@given("the command line is signed in as an editor")
def signed_in(context) -> None:
    context.signed_in = True


@given("the command line uses the operator lane")
def operator_lane(context) -> None:
    context.signed_in = False


def run(context, command: str, extra: list[str]) -> None:
    module, name, flags = HANDLERS[command]
    context.client_factory = mock.Mock(side_effect=RuntimeError("stop: the backend client was opened"))
    context.error = None
    out = io.StringIO()
    with mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=context.signed_in), \
            mock.patch.object(module, "create_authoring_client", context.client_factory), \
            mock.patch("papyrus_content.reference_feed_backfill.corpus_ids_for", return_value=[]), \
            redirect_stdout(out):
        try:
            getattr(module, name)([*flags, *extra])
        except Exception as error:  # noqa: BLE001 - the scenario inspects whatever stopped the command
            context.error = error
    context.output = out.getvalue()


@when('"{command}" is run to write')
def run_write(context, command: str) -> None:
    run(context, command, ["--write"] if command in ("references backfill-medium", "references backfill-public-fields") else [])


@when('"{command}" is run as a preview')
def run_preview(context, command: str) -> None:
    run(context, command, [])


@then("it stops with a message that it is an operator command")
def stops(context) -> None:
    assert isinstance(context.error, OperatorError), repr(context.error)
    assert "is an operator command" in str(context.error), str(context.error)


@then("the message names the operator lane")
def names_lane(context) -> None:
    assert "operator lane" in str(context.error) and "PAPYRUS_GRAPHQL_AUTH=iam" in str(context.error), str(context.error)


@then("it says nothing was changed")
def nothing_changed(context) -> None:
    assert str(context.error).endswith("Nothing was changed."), str(context.error)


@then("no backend client was opened")
def no_client(context) -> None:
    context.client_factory.assert_not_called()


@then("the backend client was opened")
def client_opened(context) -> None:
    context.client_factory.assert_called()


@then("the first line it prints is an operator-lane notice")
def first_line_notice(context) -> None:
    assert context.error is not None  # the stub client stops it after the notice
    first = context.output.splitlines()[0]
    assert "\toperator-lane\tnotice\t" in first and "is an operator command" in first, first


@then("the notice says the preview only reads")
def notice_reads(context) -> None:
    assert "This preview only reads." in context.output.splitlines()[0]


@then("no operator-lane message is printed")
def no_message(context) -> None:
    assert "operator command" not in context.output
    assert not isinstance(context.error, OperatorError), repr(context.error)
