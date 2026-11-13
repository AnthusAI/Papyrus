"""The real candidate store and apply writer over an in-memory backend (features_backend/image-generate-persistence.feature). No AWS, no provider."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.images.candidate_store import ItemCandidateStore  # noqa: E402
from papyrus_content.images.generation_binding import signed_in_generation_handlers  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402

PERSON = Caller(kind="person", subject="Edie Editor")
ALLOWED_INDEXES = {"itemBySlug", "itemsByParent", "modelAttachmentsByOwnerRoleAndSortKey", "itemsByLineageAndVersion", "mediaAssetsByItemAndSortKey", "knowledgeCorporaByRoleAndName"}
CLOCK = lambda: "2026-11-10T12:00:00Z"  # noqa: E731


def backend(context):
    return context.image_backends["ours"]


def fresh_store(context):
    return ItemCandidateStore(backend(context), backend(context).document_files, now=CLOCK, delete_object=lambda path: None)


def rows_of(context, type_):
    return [row for row in backend(context).items if row.get("type") == type_]


@given("the site keeps rounds in the backend")
def step_persistent(context):
    context.persistent = True


@then("the backend holds one round row and {count:d} candidate rows of private type with no body text")
def step_rows(context, count):
    rounds, candidates = rows_of(context, "image-round"), rows_of(context, "image-candidate")
    assert len(rounds) == 1 and len(candidates) == count, (len(rounds), len(candidates))
    for row in rounds + candidates:
        assert row["status"] == "private" and row["bodyMarkus"] == "" and row["body"] == [], row


@then("the prompt and the brief are in record files and not in any row")
def step_text_in_files(context):
    row_text = json.dumps([row for row in backend(context).items if str(row.get("type", "")).startswith("image-")])
    assert "locked filing cabinet" not in row_text and "Flat shapes" not in row_text
    records = [body.decode() for path, body in backend(context).document_bodies.items() if "image-record" in path]
    assert records and any("A locked filing cabinet" in text for text in records)


@then("a fresh store reads the round back with {count:d} ready candidates")
def step_fresh_round(context, count):
    store = fresh_store(context)
    round_id = context.answer["result"]["roundId"]
    assert store.get_round(round_id)["brief"] == "A locked filing cabinet"
    found = store.candidates_of(round_id)
    assert len(found) == count and all(row["status"] == "ready" for row in found), found


@then("every read the stores made was by a named index")
def step_indexes(context):
    used = {index for index, _ in backend(context).reads}
    assert used <= ALLOWED_INDEXES, used - ALLOWED_INDEXES


@then("the picture file is stored under the newsroom's private payload prefix")
def step_private_prefix(context):
    paths = [path for path in backend(context).document_bodies if "image-candidate-file" in path]
    assert len(paths) == 1 and paths[0].startswith("newsroom/payloads/"), paths


@then("no object was written to the site's media")
def step_no_media(context):
    assert context.put_calls == [] and backend(context).media_assets == []


@then("a fresh store says {amount:f} dollars were spent on the day")
def step_spent(context, amount):
    assert fresh_store(context).spent_on("2026-11-10") == amount


def latest_round_candidates(context):
    return context.answer["result"]["candidates"]


@then('candidate {number:d} of the latest round is "{status}"')
def step_latest_status(context, number, status):
    assert latest_round_candidates(context)[number - 1]["status"] == status


@then('candidate {number:d} of the latest round failed with the error "{code}"')
def step_latest_failed(context, number, code):
    row = latest_round_candidates(context)[number - 1]
    assert row["status"] == "failed" and row["error"]["code"] == code, row


@then("the stored object was deleted and the file can no longer be read")
def step_deleted(context):
    store = fresh_store(context)
    candidate = store.get_candidate(context.all_ids[0])
    assert context.deleted_objects and store.read_file(candidate.get("filePath") or "none") is None
    pictures = [a for a in backend(context).document_attachments if a["role"] == "image_candidate_file"]
    assert pictures and all(a["status"] == "deleted" for a in pictures), pictures


@then('the candidate\'s record is still there as "{status}" with its earlier version kept')
def step_record_kept(context, status):
    rows = [row for row in rows_of(context, "image-candidate")]
    assert len(rows) == 2 and sorted(row["versionState"] for row in rows) == ["current", "superseded"], rows
    assert fresh_store(context).get_candidate(context.all_ids[0])["status"] == status


@then('the picture was copied to the site\'s media under "{prefix}"')
def step_copied(context, prefix):
    assert len(context.put_calls) == 1 and context.put_calls[0][0].startswith(prefix) and context.put_calls[0][2] == "image/png", context.put_calls


def story_rows(context):
    return sorted((row for row in backend(context).items if row["lineageId"] == "story-1"), key=lambda row: row["versionNumber"])


@then("the Story's new version is a draft that starts with the picture and has the cover set")
def step_draft(context):
    new = story_rows(context)[-1]
    assert new["versionNumber"] == 2 and new["status"] == "draft" and not new.get("publishedAt"), new
    assert new["bodyMarkus"].startswith('::image{src="assets/story-1/') and "assets/story-1/" in json.loads(new["metadata"])["frontMatterYaml"], new["bodyMarkus"]
    assert "credit" not in new["bodyMarkus"]


@then("the picture's media record says it was generated, by which model, and has no credit")
def step_media_record(context):
    row = backend(context).media_assets[0]
    metadata = json.loads(row["metadata"])
    assert row["itemId"] == story_rows(context)[-1]["id"] and metadata["generated"] is True and metadata["model"] == "gpt-image-2.5-flare", row
    assert not row.get("credit") and metadata["reviewStatus"] == "human-verified"
    assert row["storagePath"] == context.put_calls[0][0]


@then("the earlier Story version is superseded and nothing was published")
def step_superseded(context):
    old, new = story_rows(context)[:2]
    assert old["versionState"] == "superseded" and new["versionState"] == "current" and new["status"] == "draft"
    assert all(row.get("status") != "published" for row in story_rows(context))


@when('a person generates through the default handlers a "{use}" picture of type "{image_type}" with no Story and no section with the brief "{brief}"')
def step_default_handlers(context, use, image_type, brief):
    context.writes_before = len(backend(context).writes)
    table = signed_in_generation_handlers(client_factory=lambda: backend(context), providers=lambda: {"fake": context.provider})
    context.answer = execute("image_generate", {"use": use, "imageType": image_type, "brief": brief}, PERSON, table)


@then("the backend wrote nothing")
def step_wrote_nothing(context):
    assert len(backend(context).writes) == context.writes_before
