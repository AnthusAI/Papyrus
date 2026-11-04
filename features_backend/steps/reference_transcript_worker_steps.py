"""Steps for features_backend/reference-transcript-worker.feature. In memory: no site, no AWS, no YouTube, no sleeping."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from curation_support import MemoryClient, Summarizer, page, services  # noqa: E402,F401
from papyrus_content import references_transcripts as worker  # noqa: E402
from papyrus_content.reference_curation_store import correct_reference_capture  # noqa: E402

CORPUS = "knowledge-corpus-demo"
NEWEST, SECOND, THIRD = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"
SPOKEN = ["Today we talk", "about   feeds.\n"]


class SignedInSite(MemoryClient):
    """Reference tables in memory plus the three calls the worker makes: the index, getReference, and the capture action."""

    def __init__(self, references):
        super().__init__(references)
        self.partitions_read: list[str] = []
        self.saved_calls: list[dict] = []
        self.services = services(self)

    def iterate_newest_first(self, index, partition):
        assert index == "referencesByContentNeededAndArrival"
        self.partitions_read.append(partition)
        rows = [row for row in self.tables["Reference"].values() if row.get("contentNeededKey") == partition]
        yield from [dict(row) for row in sorted(rows, key=lambda row: row["feedArrivalAt"], reverse=True)]

    def graphql(self, query, variables):
        assert "correctReferenceCapture" in query
        payload = json.loads(variables["input"])
        self.saved_calls.append(payload)
        row = self.tables["Reference"][payload["referenceId"]]
        answer = correct_reference_capture(self, payload, {"username": "editor-signed-in"}, store=self.services.store)
        return {"correctReferenceCapture": json.dumps(answer, default=str), "row": row}


def video(identifier, arrival, status):
    return {"id": f"reference-{identifier}-v1", "lineageId": f"reference-{identifier}", "versionNumber": 1, "versionState": "current", "corpusId": CORPUS,
            "curationStatus": status, "title": f"Talk {identifier}", "sourceUri": f"https://www.youtube.com/watch?v={identifier}", "medium": "video",
            "feedArrivalAt": arrival, "captureState": "thin", "mediumFeedKey": f"{CORPUS}#video#{status}",
            "contentNeededKey": f"{CORPUS}#video#needs_content#{status}"}


class Speaker:
    """YouTube, scripted per video id; counts every request."""

    def __init__(self):
        self.answers: dict[str, tuple[str | None, str | None]] = {}
        self.calls: list[str] = []

    def __call__(self, identifier):
        self.calls.append(identifier)
        return self.answers.get(identifier, (" ".join(SPOKEN), None))


def reference_id(identifier):
    return f"reference-{identifier}-v1"


@given("a site whose corpus holds accepted, pending and rejected videos that need content")
def _(context):
    context.site = SignedInSite([video(NEWEST, "2026-11-04T00:00:00.000Z", "accepted"), video(SECOND, "2026-11-03T00:00:00.000Z", "pending"),
                                 video(THIRD, "2026-11-02T00:00:00.000Z", "accepted"), video("ddddddddddd", "2026-11-05T00:00:00.000Z", "rejected")])
    context.speaker, context.sleeps, context.output, context.code = Speaker(), [], io.StringIO(), None
    context.library_installed = True
    environment = mock.patch.dict("os.environ", {}, clear=False)   # the command selects the signed-in lane in the environment; undo that after the scenario
    environment.start()
    context.add_cleanup(environment.stop)


@given("YouTube has no transcript for the second newest video")
def _(context):
    context.speaker.answers[SECOND] = (None, "no_transcript")


@given("YouTube gives an unreadable answer for the newest video")
def _(context):
    context.speaker.answers[NEWEST] = (None, "unreadable")


@given("YouTube blocks the request for the second newest video")
def _(context):
    context.speaker.answers[SECOND] = (None, "blocked")


@given("the optional transcript package is not installed")
def _(context):
    patcher = mock.patch.dict(sys.modules, {"youtube_transcript_api": None})
    patcher.start()
    context.add_cleanup(patcher.stop)
    context.library_installed = False


def run(context, *flags, repeat=False):
    stderr = io.StringIO()
    # The command checks for the optional package only when it is not handed a fetcher, so the "not installed" scenario runs it without one.
    fetch = context.speaker if context.library_installed else None
    out = io.StringIO()
    with mock.patch.object(sys, "stderr", stderr):
        context.code = worker.command(["--corpus-key", "demo", *flags], client=context.site, out=out, fetch=fetch, sleep=context.sleeps.append)
    context.output, context.errors = out.getvalue(), stderr.getvalue()


@when("the transcript worker runs")
def _(context):
    run(context)


@when('the transcript worker runs with the status "{status}"')
def _(context, status):
    run(context, "--status", status)


@when("the transcript worker runs as a dry run")
def _(context):
    run(context, "--dry-run")


@when("the transcript worker runs with a limit of {limit:d} and a pace of {pace:d} seconds")
def _(context, limit, pace):
    run(context, "--limit", str(limit), "--pace", str(pace))


@then('it read the "{first}" and "{second}" partitions of the content-needed index')
def _(context, first, second):
    assert sorted(context.site.partitions_read) == sorted(f"{CORPUS}#video#needs_content#{status}" for status in (first, second)), context.site.partitions_read


@then('it read the "{status}" partition of the content-needed index')
def _(context, status):
    assert f"{CORPUS}#video#needs_content#{status}" in context.site.partitions_read


@then('it did not read the "{status}" partition')
def _(context, status):
    assert f"{CORPUS}#video#needs_content#{status}" not in context.site.partitions_read


@then("it asked for the videos newest first")
def _(context):
    assert context.speaker.calls == [NEWEST, SECOND, THIRD], context.speaker.calls


@then("the transcript of the newest video was saved with the capture action as the signed-in editor")
def _(context):
    first = context.site.saved_calls[0]
    assert first["referenceId"] == reference_id(NEWEST) and first["assessment"] == "incomplete" and "editor" not in first
    assert context.site.card(reference_id(NEWEST))["edits"][0]["editedBy"] == "editor-signed-in"


@then("the saved text is the spoken words as one paragraph")
def _(context):
    row = context.site.get_record("Reference", reference_id(NEWEST))
    assert context.site.services.store.text(row, "curation-edit-0001-text") == " ".join(SPOKEN)


@then("the video is stored as captured in full and no longer needs content")
def _(context):
    row = context.site.get_record("Reference", reference_id(NEWEST))
    assert row["captureState"] == "full" and row["contentNeededKey"] is None


@then("one line was printed for each video as it was handled")
def _(context):
    handled = [line.split("\t") for line in context.output.splitlines() if "\tcaptured\t" in line]
    assert [line[3] for line in handled] == [reference_id(NEWEST), reference_id(SECOND), reference_id(THIRD)]


@then('the second newest video is recorded with the reason "{reason}"')
def _(context, reason):
    assert context.site.get_record("Reference", reference_id(SECOND))["captureReason"] == reason
    assert context.site.card(reference_id(SECOND))["capture"]["textReason"] == reason


@then("it is not in the list of videos that need content")
def _(context):
    assert context.site.get_record("Reference", reference_id(SECOND))["contentNeededKey"] is None


@then('it is still not captured, so the To capture queue lists it with the reason "{reason}"')
def _(context, reason):
    row = context.site.get_record("Reference", reference_id(SECOND))
    assert row["captureState"] != "full"
    assert context.site.card(reference_id(SECOND))["capture"]["textReason"] == reason


@then("running the worker again does not ask YouTube about it")
def _(context):
    before = list(context.speaker.calls)
    context.site.partitions_read.clear()
    run(context)
    assert context.speaker.calls == before, context.speaker.calls


@then("the newest video is reported as failed and nothing is saved for it")
def _(context):
    assert any(line.split("\t")[2] == "failed" and reference_id(NEWEST) in line for line in context.output.splitlines())
    assert all(call["referenceId"] != reference_id(NEWEST) for call in context.site.saved_calls)


@then("the other videos are still captured")
def _(context):
    for identifier in (SECOND, THIRD):
        assert context.site.get_record("Reference", reference_id(identifier))["captureState"] == "full"


@then("the newest video is still waiting for the next run")
def _(context):
    assert context.site.get_record("Reference", reference_id(NEWEST))["contentNeededKey"] == f"{CORPUS}#video#needs_content#accepted"


@then("the worker waited and tried that video again before it stopped")
def _(context):
    assert context.speaker.calls.count(SECOND) == len(worker.BACKOFF_SECONDS) + 1 and context.code == worker.EXIT_BLOCKED
    assert all(wait in context.sleeps for wait in worker.BACKOFF_SECONDS)


@then("the videos before it were saved")
def _(context):
    assert context.site.get_record("Reference", reference_id(NEWEST))["captureState"] == "full"


@then("the worker stopped with a message that it needs a non-cloud connection")
def _(context):
    assert "non-cloud connection" in context.errors and "stopped: blocked" in context.output


@then("the videos after it were not tried")
def _(context):
    assert THIRD not in context.speaker.calls


@then("every waiting video was listed")
def _(context):
    listed = [line for line in context.output.splitlines() if line.split("\t")[2:3] == ["would_read"]]
    assert [line.split("\t")[3] for line in listed] == [reference_id(NEWEST), reference_id(SECOND), reference_id(THIRD)]


@then("YouTube was not asked for anything")
def _(context):
    assert context.speaker.calls == []


@then("nothing was saved")
def _(context):
    assert context.site.saved_calls == [] and context.site.writes == 0


@then("only the {count:d} newest videos were handled")
def _(context, count):
    assert context.speaker.calls == [NEWEST, SECOND][:count]


@then("it waited {seconds:d} seconds between the requests to YouTube")
def _(context, seconds):
    assert context.sleeps == [float(seconds)]


@then('it stops with a message naming the "{extra}" extra')
def _(context, extra):
    assert context.code == 2 and f"--extras {extra}" in context.errors


@then("nothing was read from the site")
def _(context):
    assert context.site.partitions_read == [] and context.site.saved_calls == []


@then("it used the signed-in client and no AWS credentials")
def _(context):
    import os
    assert os.environ["PAPYRUS_GRAPHQL_AUTH"] == "user"
    assert "boto3" not in Path(worker.__file__).read_text()
