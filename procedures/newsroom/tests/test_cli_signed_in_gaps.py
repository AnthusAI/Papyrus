"""Signed-in CLI gaps: save-version names the signed-in person, assignments show prints the direction, the site file's bucket and
identity pool, and the root guard message. In-memory fakes only; no network, login or AWS."""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from fake_client import FakeAuthoringClient  # noqa: E402

from papyrus import cli as papyrus_cli  # noqa: E402
from papyrus_content import assignments_commands, media_store, site_document, story_commands, story_images  # noqa: E402
from papyrus_content.operator_errors import OperatorError  # noqa: E402

LINEAGE = "story-gap"
BUCKET, POOL = "example-site-media-bucket", "us-east-1:00000000-0000-4000-8000-000000000000"


class Client(FakeAuthoringClient):
    endpoint = "https://example.test/graphql"
    tenant_id = None


def story_client():
    return Client({"Item": [{"id": f"{LINEAGE}-v1", "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current", "headline": "A",
                             "title": "A", "stage": "idea", "slug": "a", "type": "untyped", "section": "news"}]})


def save(client, *flags, signed_in, label="Ada Example"):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            mock.patch.object(story_commands, "create_authoring_client", return_value=(client, {})), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=signed_in), \
            mock.patch("papyrus_content.cli_user_auth.signed_in_label", return_value=label), \
            mock.patch("papyrus_content.story_triggers.deliver_from_environment"), \
            mock.patch.object(story_commands, "print_reminder"), \
            mock.patch.object(story_commands, "reminder_assessment", return_value=None):
        try:
            story_commands.stories_save_version(["--story", LINEAGE, "--body", "text", "--reason", "r", "--no-check", *flags])
            failure = None
        except BaseException as error:  # noqa: BLE001
            failure = error
    return out.getvalue(), err.getvalue(), failure


def newest(client):
    return max(client.tables["Item"].values(), key=lambda row: int(row["versionNumber"]))


def test_signed_in_save_version_needs_no_author_label_and_names_the_session():
    client = story_client()
    out, err, failure = save(client, signed_in=True)
    assert failure is None and err == "" and newest(client)["versionCreatedBy"] == "Ada Example"
    assert out.splitlines()[0].endswith("write")


def test_signed_in_a_supplied_author_label_is_ignored_with_a_warning():
    client = story_client()
    _out, err, failure = save(client, "--author-label", "Someone Else", signed_in=True)
    assert failure is None and newest(client)["versionCreatedBy"] == "Ada Example" and "is ignored" in err


def test_signed_in_with_a_session_that_names_no_one_saves_nothing():
    client = story_client()
    out, _err, failure = save(client, signed_in=True, label=None)
    assert isinstance(failure, OperatorError) and "whoami" in str(failure) and out == "" and len(client.tables["Item"]) == 1


def test_signed_in_dry_run_needs_no_label():
    client = story_client()
    out, _err, failure = save(client, "--dry-run", signed_in=True, label=None)
    assert failure is None and out.strip().endswith("dry run") and client.write_calls() == []


def test_the_iam_lane_still_requires_the_author_label_and_records_it_as_given():
    client = story_client()
    _out, _err, failure = save(client, signed_in=False)
    assert isinstance(failure, ValueError) and "--author-label is required" in str(failure) and len(client.tables["Item"]) == 1
    _out, _err, failure = save(client, "--author-label", "ChatGPT", signed_in=False)
    assert failure is None and newest(client)["versionCreatedBy"] == "ChatGPT"


# --- assignments show: the direction ----------------------------------------------------------------------------

def show(metadata=None, attachment=None):
    row = {"id": "as-1", "status": "open", "assignmentTypeKey": "research.multi", "title": "Look", "queueKey": "q"}
    if metadata is not None:
        row["metadata"] = json.dumps(metadata) if not isinstance(metadata, str) else metadata
    tables = {"Assignment": [row]}
    if attachment is not None:
        tables["ModelAttachment"] = [{"id": "att-1", "ownerId": "as-1", "role": "metadata", "sortKey": "metadata", "status": "ready"}]
    out = io.StringIO()
    with mock.patch.object(assignments_commands, "create_authoring_client", return_value=(Client(tables), {})), \
            mock.patch("papyrus_content.assignments.download_attachment_buffer", lambda client, a: json.dumps(attachment).encode()), \
            contextlib.redirect_stdout(out):
        assignments_commands.assignments_show(["--assignment", "as-1"])
    return [line.split("\t") for line in out.getvalue().splitlines()]


def direction_rows(rows):
    return [row for row in rows if row[3:4] == ["direction"]]


def test_the_direction_is_printed_whole_and_before_the_events():
    rows = show({"direction": "Look into this."})
    assert [row[4] for row in direction_rows(rows)] == ["Look into this."]
    assert rows.index(direction_rows(rows)[0]) < next(i for i, row in enumerate(rows) if row[1] == "events")


def test_a_multi_line_direction_prints_one_row_per_line_and_keeps_blank_lines():
    text = "First.\n\nSecond with\ttab.\r\nThird."
    rows = direction_rows(show({"direction": text}))
    assert [row[4] for row in rows] == ["First.", "", "Second with tab.", "Third."]
    assert all(row[:4] == ["assignments", "show", "as-1", "direction"] for row in rows)


def test_the_direction_is_read_from_the_metadata_attachment_when_the_row_has_none():
    rows = direction_rows(show(None, {"direction": "From the attachment."}))
    assert [row[4] for row in rows] == ["From the attachment."]


def test_no_direction_prints_no_row():
    assert direction_rows(show({"kind": "x"})) == []
    assert direction_rows(show({"direction": "   "})) == []


# --- the site file: media bucket and identity pool ----------------------------------------------------------------

def test_the_site_file_keeps_a_valid_bucket_and_identity_pool():
    found = site_document.parse(json.dumps({"tenant_id": "t", "media_bucket": BUCKET, "identity_pool_id": POOL}).encode())
    assert found == {"tenant_id": "t", "media_bucket": BUCKET, "identity_pool_id": POOL}


@pytest.mark.parametrize("document", [{"media_bucket": "Not A Bucket!", "identity_pool_id": "pool"}, {"media_bucket": 7, "identity_pool_id": None}, {}])
def test_values_that_are_not_a_bucket_or_pool_are_dropped_not_fatal(document):
    assert site_document.parse(json.dumps({"papyrus_version": "5.86.0", **document}).encode()) == {"papyrus_version": "5.86.0"}


def test_the_sign_in_file_gained_no_field():
    from papyrus_content.cli_user_auth import _OPTIONAL_FIELDS, _PUBLIC_FIELDS
    assert not {"media_bucket", "identity_pool_id"} & (_PUBLIC_FIELDS | _OPTIONAL_FIELDS)


def test_a_signed_in_site_that_publishes_nothing_gives_errors_that_name_the_flags():
    from papyrus_content import env
    selection = mock.Mock()
    selection.host_for.return_value = "a.anth.us"
    selection.published.return_value = None
    selection.accepts_outputs.return_value = True
    with mock.patch.object(env, "_site_selection", selection), mock.patch.object(env, "amplify_outputs_path", lambda: pathlib.Path("/nonexistent/x.json")), \
            mock.patch.dict("os.environ", {}, clear=False):
        for name in ("PAPYRUS_MEDIA_BUCKET", "PAPYRUS_STORAGE_BUCKET", "PAPYRUS_IDENTITY_POOL_ID"):
            __import__("os").environ.pop(name, None)
        with pytest.raises(ValueError, match=r"a\.anth\.us does not publish one.*--bucket"):
            media_store.S3MediaStore(None)
        with pytest.raises(ValueError, match=r"a\.anth\.us does not publish one.*--identity-pool-id"):
            story_images.identity_pool_id(None)


# --- the root guard message -----------------------------------------------------------------------------------------

def test_the_root_guard_message_says_to_run_from_another_folder_and_calls_the_override_an_explicit_choice():
    module_root, operator_root = pathlib.Path("/tmp/module-root").resolve(), pathlib.Path("/tmp/operator-root").resolve()
    with mock.patch.object(papyrus_cli, "PAPYRUS_ROOT", module_root), mock.patch.object(papyrus_cli, "_find_operator_repo_root", return_value=operator_root):
        with pytest.raises(ValueError) as raised:
            papyrus_cli._enforce_root_guard(["stories", "show"], cwd=operator_root)
    message = str(raised.value)
    assert "papyrus-root-guard\tblocked" in message and "Run it from another folder" in message
    assert "--allow-cross-root" in message and "explicit choice" in message
