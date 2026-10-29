"""`papyrus references enrich-images`: one preview attachment per Reference, idempotent, never a write on a dry run. No network, no AWS."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from papyrus_content.link_exploration import Exploration, PageMetadata  # noqa: E402
from papyrus_content.reference_images import PREVIEW_ROLE, PREVIEW_SORT_KEY, enrich_reference_previews, preview_attachment  # noqa: E402

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, references, attachments=()):
        self.rows = {"Reference": list(references), "ReferenceAttachment": list(attachments)}
        self.written = []

    def list_records(self, model):
        return list(self.rows[model])

    def upsert(self, model, row):
        self.written.append((model, row))
        return "created"


def reference(name, **fields):
    return {"id": f"{name}-v1", "lineageId": name, "versionNumber": 1, "versionState": "current", "corpusId": "c", "sourceUri": f"https://{name}.example.org/a", **fields}


def explorer(results):
    asked = []

    def explore(url, **kwargs):
        asked.append((url, kwargs))
        return results.get(url, Exploration(False, None, failure="dns"))

    explore.asked = asked
    return explore


def found(url, **fields):
    return Exploration(True, url, via="direct", metadata=PageMetadata(**fields))


def test_a_preview_attachment_holds_the_image_in_source_uri_and_the_rest_in_metadata():
    row = preview_attachment(reference("a"), found("https://a.example.org/a", image_url="https://cdn.example.org/a.jpg", description="Dek.", site_name="A", title="T"), NOW)
    assert (row["role"], row["sortKey"], row["sourceUri"], row["mediaType"]) == (PREVIEW_ROLE, PREVIEW_SORT_KEY, "https://cdn.example.org/a.jpg", "image/jpeg")
    assert row["referenceVersionKey"] == "reference#a-v1" and row["referenceLineageId"] == "a"
    metadata = json.loads(row["metadata"])
    assert (metadata["description"], metadata["siteName"], metadata["checkedAt"]) == ("Dek.", "A", "2026-10-27T12:00:00Z")


def test_enrichment_writes_one_attachment_per_reference_and_reads_pages_without_search_or_text():
    client = FakeClient([reference("a"), reference("b"), reference("c")])
    fake = explorer({
        "https://a.example.org/a": found("https://a.example.org/a", image_url="https://cdn.example.org/a.jpg", description="Dek A."),
        "https://b.example.org/a": found("https://b.example.org/a", description="Only a dek."),
    })
    counts = enrich_reference_previews(client, explorer=fake, now=lambda: NOW)
    assert counts == {"considered": 3, "alreadyHave": 0, "withImage": 1, "withoutImage": 1, "failed": 1, "written": 2}
    assert [row["referenceLineageId"] for _, row in client.written] == ["a", "b"]
    assert all(kwargs == {"want_text": False, "use_search": False} for _, kwargs in fake.asked)


def test_a_second_run_skips_what_has_a_preview_and_refresh_reads_it_again():
    existing = {"role": PREVIEW_ROLE, "referenceVersionKey": "reference#a-v1"}
    client = FakeClient([reference("a"), reference("b")], [existing])
    fake = explorer({"https://b.example.org/a": found("https://b.example.org/a", image_url="https://cdn.example.org/b.png")})
    counts = enrich_reference_previews(client, explorer=fake, now=lambda: NOW)
    assert counts["alreadyHave"] == 1 and [row["referenceLineageId"] for _, row in client.written] == ["b"]
    again = enrich_reference_previews(FakeClient([reference("a")], [existing]), refresh=True, explorer=explorer({}), now=lambda: NOW)
    assert again["alreadyHave"] == 0 and again["failed"] == 1


def test_a_dry_run_reads_and_counts_but_writes_nothing_and_the_corpus_and_limit_narrow_the_work():
    client = FakeClient([reference("a"), reference("b", corpusId="other"), reference("c")])
    fake = explorer({url: found(url, image_url="https://cdn.example.org/x.jpg") for url in ("https://a.example.org/a", "https://c.example.org/a")})
    counts = enrich_reference_previews(client, corpus="c", limit=1, dry_run=True, explorer=fake, now=lambda: NOW)
    assert client.written == [] and counts["considered"] == 2 and counts["withImage"] == 1 and counts["written"] == 0
    assert len(fake.asked) == 1


def test_references_without_a_web_address_are_not_considered():
    client = FakeClient([reference("a", sourceUri="s3://bucket/file.pdf"), reference("b", versionState="superseded")])
    assert enrich_reference_previews(client, explorer=explorer({}), now=lambda: NOW)["considered"] == 0


# --- attach_preview: the automatic run when a Reference is created -------------------------------------------------------------------------


import io  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402

from papyrus_content.reference_images import attach_preview, exploration_from_preview  # noqa: E402


class StoreClient:
    def __init__(self, attachments=(), fail_with=None):
        self.rows = {row["id"]: row for row in attachments}
        self.fail_with = fail_with

    def get_record(self, model, record_id):
        assert model == "ReferenceAttachment"
        return self.rows.get(record_id)

    def upsert(self, model, row):
        if self.fail_with:
            raise self.fail_with
        self.rows[row["id"]] = row
        return "created"


def attach(client, ref, **kwargs):
    lines = []
    outcome = attach_preview(client, ref, now=lambda: NOW, log=lines.append, **kwargs)
    return outcome, [json.loads(line) for line in lines]


def test_a_new_reference_gets_its_preview_with_the_image_and_one_log_line():
    client, fake = StoreClient(), explorer({"https://a.example.org/a": found("https://a.example.org/a", image_url="https://cdn.example.org/a.jpg")})
    outcome, logs = attach(client, reference("a"), explorer=fake)
    (row,) = client.rows.values()
    assert outcome == "written" and row["sourceUri"] == "https://cdn.example.org/a.jpg" and row["role"] == PREVIEW_ROLE
    assert logs == [{"referencePreview": "written", "referenceId": "a-v1", "withImage": True, "reused": False}]
    assert fake.asked[0][1] == {"want_text": False, "use_search": False}


def test_a_page_without_an_image_gets_a_checked_row():
    client = StoreClient()
    outcome, logs = attach(client, reference("a"), explorer=explorer({"https://a.example.org/a": Exploration(True, "https://a.example.org/a", via="direct")}))
    (row,) = client.rows.values()
    assert outcome == "written" and row["sourceUri"] is None and "checkedAt" in json.loads(row["metadata"])
    assert logs[0]["withImage"] is False


def test_a_reference_that_already_has_a_preview_is_not_fetched_again():
    ref = reference("a")
    existing = preview_attachment(ref, found("https://a.example.org/a", image_url="https://cdn.example.org/a.jpg"), NOW)
    client, fake = StoreClient([existing]), explorer({})
    outcome, logs = attach(client, ref, explorer=fake)
    assert outcome == "exists" and fake.asked == [] and logs == []


def test_an_exploration_the_caller_already_has_is_used_without_a_fetch():
    client, fake = StoreClient(), explorer({})
    outcome, logs = attach(client, reference("a"), exploration=exploration_from_preview("https://a.example.org/a", {"imageUrl": "https://cdn.example.org/a.jpg", "siteName": "A"}), explorer=fake)
    assert outcome == "written" and fake.asked == [] and logs[0]["reused"] is True
    assert next(iter(client.rows.values()))["filename"] == "A"


def test_a_failure_is_logged_and_swallowed_whatever_it_is():
    for client, fake in ((StoreClient(), explorer({})),                                                      # page not readable
                         (StoreClient(fail_with=RuntimeError("AppSync down")), explorer({"https://a.example.org/a": found("https://a.example.org/a", image_url="https://c.example.org/x.jpg")})),
                         (object(), explorer({})),                                                           # a client with no such methods
                         (StoreClient(), lambda *a, **k: (_ for _ in ()).throw(TimeoutError("slow")))):
        outcome, logs = attach(client, reference("a"), explorer=fake)
        assert outcome == "failed" and logs[0]["referencePreview"] == "failed" and logs[0]["referenceId"] == "a-v1" and logs[0]["reason"]
        assert not getattr(client, "rows", None)


def test_the_default_logger_prints_one_json_line():
    out = io.StringIO()
    with redirect_stdout(out):
        attach_preview(StoreClient(), reference("a"), explorer=explorer({}), now=lambda: NOW)
    assert json.loads(out.getvalue())["referencePreview"] == "failed"
