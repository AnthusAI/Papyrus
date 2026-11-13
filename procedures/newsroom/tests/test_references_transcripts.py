"""`papyrus references capture-transcripts`: which videos it reads, what it writes, and how it stops. No network, no AWS, no real YouTube."""

from __future__ import annotations

import io
import json
import sys
from unittest import mock

import pytest

from papyrus_content import references_transcripts as worker
from papyrus_content.operator_errors import GraphQLRequestError

CORPUS = "knowledge-corpus-demo"
ACCEPTED = f"{CORPUS}#video#needs_content#accepted"
PENDING = f"{CORPUS}#video#needs_content#pending"
REJECTED = f"{CORPUS}#video#needs_content#rejected"


def video(identifier: str, arrival: str, address: str | None = None, **extra) -> dict:
    return {"id": f"reference-{identifier}-v1", "title": f"Talk {identifier}", "feedArrivalAt": arrival,
            "sourceUri": address or f"https://www.youtube.com/watch?v={identifier}", "contentNeededKey": ACCEPTED, **extra}


class Site:
    """The signed-in client: index partitions, `getReference`, and the `correctReferenceCapture` action."""

    def __init__(self, partitions: dict[str, list[dict]], refuse: dict[str, str] | None = None):
        self.partitions, self.refuse = partitions, refuse or {}
        self.asked: list[str] = []
        self.actions: list[dict] = []
        self.rows = {row["id"]: row for rows in partitions.values() for row in rows}
        self.kept_listings = 0

    def iterate_newest_first(self, index, partition):
        assert index == "referencesByContentNeededAndArrival"
        self.asked.append(partition)
        yield from sorted(self.partitions.get(partition, []), key=lambda row: row["feedArrivalAt"], reverse=True)

    def get_record(self, model, record_id):
        assert model == "Reference"
        return self.rows.get(record_id)

    def list_by_index(self, index, key_value, **_):
        assert (index, key_value) == ("knowledgeCorporaByRoleAndName", "canonical")   # the one corpus the site publishes, read through its role index
        return [{"id": CORPUS, "role": "canonical", "name": "Demo"}]

    def list_records(self, model):
        raise AssertionError(f"a whole-table list of {model}")

    def graphql(self, query, variables):
        assert "correctReferenceCapture" in query
        payload = json.loads(variables["input"])
        self.actions.append(payload)
        if payload["referenceId"] in self.refuse:
            return {"correctReferenceCapture": json.dumps({"ok": False, "errors": [{"code": "correction-rejected", "message": self.refuse[payload["referenceId"]]}]})}
        return {"correctReferenceCapture": json.dumps({"ok": True, "referenceId": payload["referenceId"]})}


def fetcher(answers: dict[str, tuple[str | None, str | None]]):
    calls: list[str] = []

    def fetch(identifier):
        calls.append(identifier)
        return answers[identifier]
    fetch.calls = calls
    return fetch


def run(site, *flags, answers=None, sleeps=None):
    out = io.StringIO()
    fetch = fetcher(answers or {})
    sleeps = [] if sleeps is None else sleeps
    code = worker.command(["--corpus-key", "demo", *flags], client=site, out=out, fetch=fetch, sleep=sleeps.append)
    return code, out.getvalue(), fetch, sleeps


def lines(output):
    return [line.split("\t") for line in output.splitlines() if line.startswith("references\tcapture-transcripts")]


def outcomes(output):
    return [(row[2], row[3]) for row in lines(output) if row[2] not in ("mode", "done", "next")]


def test_it_reads_the_accepted_and_pending_partitions_newest_first_and_never_the_rejected_one():
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-01T00:00:00.000Z"), video("ccccccccccc", "2026-11-03T00:00:00.000Z")],
                 PENDING: [video("bbbbbbbbbbb", "2026-11-02T00:00:00.000Z")], REJECTED: [video("ddddddddddd", "2026-11-04T00:00:00.000Z")]})
    answers = {key * 11: (f"words {key}", None) for key in "abc"}
    code, output, fetch, _ = run(site, answers=answers)
    assert code == 0
    assert sorted(site.asked) == sorted([ACCEPTED, PENDING])
    assert fetch.calls == ["ccccccccccc", "bbbbbbbbbbb", "aaaaaaaaaaa"]
    assert site.kept_listings == 0   # the corpus was named; no listing of anything


def test_the_status_flag_picks_the_partitions_and_all_includes_the_rejected_ones():
    site = Site({ACCEPTED: [], PENDING: [], REJECTED: [video("ddddddddddd", "2026-11-04T00:00:00.000Z")]})
    run(site, "--status", "rejected", answers={"d" * 11: ("x", None)})
    assert site.asked == [REJECTED]
    site = Site({})
    run(site, "--status", "all")
    assert sorted(site.asked) == sorted([ACCEPTED, PENDING, REJECTED])


def test_an_unknown_status_is_refused_in_one_line(capsys):
    assert worker.command(["--corpus-key", "demo", "--status", "published"], client=Site({}), out=io.StringIO(), fetch=fetcher({})) == 2
    assert "pending, accepted, rejected or all" in capsys.readouterr().err


def test_a_transcript_is_saved_through_the_capture_action_as_the_signed_in_editor_with_a_note_and_no_verdict_on_the_page():
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-01T00:00:00.000Z")]})
    code, output, _, _ = run(site, answers={"a" * 11: ("We talk about feeds.", None)})
    assert code == 0
    assert site.actions == [{"referenceId": "reference-aaaaaaaaaaa-v1", "text": "We talk about feeds.", "assessment": "incomplete", "note": worker.NOTE}]
    assert outcomes(output) == [("captured", "reference-aaaaaaaaaaa-v1")]
    assert "20 characters" in output
    assert "marked stale" in output   # the next curation run rewrites the summary from the transcript


def test_no_transcript_and_unavailable_are_recorded_so_the_video_is_not_tried_again():
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-02T00:00:00.000Z"), video("bbbbbbbbbbb", "2026-11-01T00:00:00.000Z")]})
    _, output, _, _ = run(site, answers={"a" * 11: (None, "no_transcript"), "b" * 11: (None, "unavailable")})
    assert site.actions == [{"referenceId": "reference-aaaaaaaaaaa-v1", "captureReason": "no_transcript"},
                            {"referenceId": "reference-bbbbbbbbbbb-v1", "captureReason": "unavailable"}]
    assert [row[2] for row in lines(output)[1:3]] == ["no_transcript", "unavailable"]
    assert "left for a person in To capture" in output


def test_a_video_on_another_platform_is_recorded_without_asking_youtube():
    site = Site({ACCEPTED: [video("v", "2026-11-01T00:00:00.000Z", "https://vimeo.com/123456789")]})
    _, output, fetch, _ = run(site)
    assert fetch.calls == [] and site.actions == [{"referenceId": "reference-v-v1", "captureReason": "unsupported_platform"}]
    assert outcomes(output) == [("unsupported_platform", "reference-v-v1")]


def test_a_failure_is_reported_and_the_run_goes_on_leaving_that_video_for_next_time():
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-02T00:00:00.000Z"), video("bbbbbbbbbbb", "2026-11-01T00:00:00.000Z")]})
    code, output, _, _ = run(site, answers={"a" * 11: (None, "unreadable"), "b" * 11: ("Spoken words.", None)})
    assert code == 0
    assert [row[2] for row in lines(output)[1:3]] == ["failed", "captured"]
    assert [action["referenceId"] for action in site.actions] == ["reference-bbbbbbbbbbb-v1"]   # nothing written for the unreadable one


def test_a_refusal_by_the_site_for_one_video_is_reported_and_the_run_goes_on():
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-02T00:00:00.000Z"), video("bbbbbbbbbbb", "2026-11-01T00:00:00.000Z")]},
                refuse={"reference-aaaaaaaaaaa-v1": "The Reference was not found."})
    _, output, _, _ = run(site, answers={"a" * 11: ("One.", None), "b" * 11: ("Two.", None)})
    assert [row[2] for row in lines(output)[1:3]] == ["failed", "captured"]
    assert "The Reference was not found." in output


def test_a_video_captured_by_someone_else_since_the_index_was_read_is_left_alone():
    done = video("aaaaaaaaaaa", "2026-11-01T00:00:00.000Z")
    site = Site({ACCEPTED: [done]})
    site.rows[done["id"]] = {**done, "contentNeededKey": None, "captureState": "full"}
    _, output, fetch, _ = run(site)
    assert fetch.calls == [] and site.actions == []
    assert outcomes(output) == [("already_handled", done["id"])]


def test_the_limit_stops_after_that_many_videos():
    site = Site({ACCEPTED: [video(key * 11, f"2026-11-0{index + 1}T00:00:00.000Z") for index, key in enumerate("abc")]})
    _, _, fetch, _ = run(site, "--limit", "2", answers={key * 11: ("x", None) for key in "abc"})
    assert fetch.calls == ["c" * 11, "b" * 11]


def test_without_a_limit_there_is_no_cap():
    keys = [f"{index:011d}" for index in range(120)]
    site = Site({ACCEPTED: [video(key, f"2026-10-{(index % 28) + 1:02d}T{index // 28:02d}:00:00.000Z") for index, key in enumerate(keys)]})
    _, _, fetch, _ = run(site, "--pace", "0", answers={key: ("x", None) for key in keys})
    assert len(fetch.calls) == 120


def test_it_waits_between_requests_to_youtube_but_not_before_the_first_and_asks_once_per_video():
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-03T00:00:00.000Z"),
                            video("aaaaaaaaaaa", "2026-11-02T00:00:00.000Z", "https://youtu.be/aaaaaaaaaaa"), video("bbbbbbbbbbb", "2026-11-01T00:00:00.000Z")]})
    site.rows = {f"{row['id']}": row for row in site.partitions[ACCEPTED]}
    second = site.partitions[ACCEPTED][1]
    second["id"] = "reference-aaaaaaaaaaa-v1-copy"
    site.rows[second["id"]] = second
    _, _, fetch, sleeps = run(site, "--pace", "2.5", answers={"a" * 11: ("Same.", None), "b" * 11: ("Other.", None)})
    assert fetch.calls == ["a" * 11, "b" * 11] and sleeps == [2.5]
    assert len(site.actions) == 3


def test_a_dry_run_lists_what_would_be_read_and_neither_asks_youtube_nor_writes():
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-02T00:00:00.000Z"), video("v", "2026-11-01T00:00:00.000Z", "https://vimeo.com/1")]})
    site.get_record = mock.Mock(side_effect=AssertionError("a dry run reads only the index"))
    code, output, fetch, _ = run(site, "--dry-run")
    assert code == 0 and fetch.calls == [] and site.actions == []
    assert [row[2] for row in lines(output)[1:3]] == ["would_read", "would_record_unsupported_platform"]
    assert "dry run" in lines(output)[0][3]


def test_when_youtube_blocks_the_connection_it_backs_off_then_stops_naming_the_non_cloud_connection(capsys):
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-03T00:00:00.000Z"), video("bbbbbbbbbbb", "2026-11-02T00:00:00.000Z"),
                            video("ccccccccccc", "2026-11-01T00:00:00.000Z")]})
    answers = {"a" * 11: ("Fine.", None), "b" * 11: (None, "blocked"), "c" * 11: ("never reached", None)}
    code, output, fetch, sleeps = run(site, "--pace", "1", answers=answers)
    assert code == worker.EXIT_BLOCKED
    assert fetch.calls == ["a" * 11, "b" * 11, "b" * 11, "b" * 11]   # the same video three times, then stop; the third video is not tried
    assert sleeps == [1.0, 60.0, 300.0]
    assert outcomes(output)[0] == ("captured", "reference-aaaaaaaaaaa-v1") and "backing_off" in output and "stopped: blocked" in output
    assert [action["referenceId"] for action in site.actions] == ["reference-aaaaaaaaaaa-v1"]
    error = capsys.readouterr().err
    assert "non-cloud connection" in error and "cloud" in error


def test_a_block_that_clears_after_a_wait_carries_on():
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-01T00:00:00.000Z")]})
    answers = iter([(None, "blocked"), ("Now it works.", None)])
    out, sleeps = io.StringIO(), []
    code = worker.command(["--corpus-key", "demo"], client=site, out=out, fetch=lambda identifier: next(answers), sleep=sleeps.append)
    assert code == 0 and sleeps == [60.0] and site.actions[0]["text"] == "Now it works."


def test_on_a_cloud_machine_the_block_message_says_so(capsys, monkeypatch):
    monkeypatch.setenv("AWS_EXECUTION_ENV", "AWS_ECS_FARGATE")
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-01T00:00:00.000Z")]})
    code, _, _, _ = run(site, answers={"a" * 11: (None, "blocked")})
    assert code == worker.EXIT_BLOCKED
    assert "looks like a cloud machine (AWS_EXECUTION_ENV is set)" in capsys.readouterr().err


def test_without_the_optional_library_it_says_how_to_install_it_before_touching_anything(capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", None)
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-01T00:00:00.000Z")]})
    assert worker.command(["--corpus-key", "demo"], client=site, out=io.StringIO()) == 2
    assert "--extras transcripts" in capsys.readouterr().err
    assert site.asked == [] and site.actions == []


def test_a_site_without_the_index_is_told_it_ships_in_a_later_deploy(capsys):
    class NoIndex(Site):
        def iterate_newest_first(self, index, partition):
            raise GraphQLRequestError("Cannot query field listReferencesByContentNeededAndArrival on type Query")
            yield  # pragma: no cover

    assert worker.command(["--corpus-key", "demo"], client=NoIndex({}), out=io.StringIO(), fetch=fetcher({})) == 2
    assert "content-needed index" in capsys.readouterr().err


def test_without_a_corpus_key_the_site_publishes_its_canonical_corpus_and_no_table_is_listed():
    site = Site({ACCEPTED: []})
    out = io.StringIO()
    assert worker.command([], client=site, out=out, fetch=fetcher({})) == 0
    assert ACCEPTED in site.asked


def test_without_a_corpus_key_the_request_meter_records_no_unbounded_list():
    from papyrus_content import request_meter
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
    from fake_appsync import FakeAppSync
    from papyrus_content import references_thumbnails, references_titles

    canonical = {"id": CORPUS, "role": "canonical", "name": "Demo"}
    backend = FakeAppSync(indexes={"listKnowledgeCorporaByRoleAndName": {"canonical": [canonical]}, "listKnowledgeCorpora": {"": [canonical]}})
    client = PapyrusGraphQLAuthoringClient(endpoint="https://example.appsync-api.us-east-1.amazonaws.com/graphql", header_factory=lambda body: {}, site_tenant=False)
    client._open_connection = lambda: backend   # type: ignore[method-assign]
    request_meter.reset_for_tests()
    try:
        with request_meter.run("cli:references capture-transcripts", emit="log") as run:
            for corpus_ids_of in (worker.corpus_ids_of, references_thumbnails.corpus_ids_of, references_titles.corpus_ids_of):
                assert corpus_ids_of(client, None) == [CORPUS]
        assert run.unbounded == {}
    finally:
        request_meter.reset_for_tests()


def test_the_command_is_signed_in_only_and_imports_no_aws_library(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "")   # setenv, so teardown undoes what the command sets; delenv of an unset name would not
    worker.command(["--corpus-key", "demo"], client=Site({}), out=io.StringIO(), fetch=fetcher({}))
    import os
    assert os.environ["PAPYRUS_GRAPHQL_AUTH"] == "user"
    source = open(worker.__file__).read()
    assert "boto3" not in source and "create_authoring_client" not in source


def test_the_wrapped_cli_routes_to_the_worker_with_help_that_does_not_run_it(capsys):
    from papyrus.cli import _map_references

    with pytest.raises(SystemExit) as stop:
        _map_references("capture-transcripts", ["--help"])
    assert stop.value.code == 0
    assert "non-cloud connection" in capsys.readouterr().out


# --- the transcript itself ---------------------------------------------------------------------------------------------------------------


class Track:
    def __init__(self, words):
        self.words = words

    def fetch(self):
        return [mock.Mock(text=word) for word in self.words]


class Tracks:
    def __init__(self, english=None, other=None):
        self.english, self.other = english, other

    def find_transcript(self, languages):
        if self.english is None:
            raise LookupError("no english")
        return self.english

    def __iter__(self):
        return iter([self.other] if self.other else [])


def api(result):
    def factory():
        listing = mock.Mock()
        if isinstance(result, Exception):
            listing.side_effect = result
        else:
            listing.return_value = result
        return mock.Mock(list=listing)
    return factory


def test_the_english_track_is_joined_into_one_paragraph():
    assert worker.fetch_transcript("x" * 11, api_factory=api(Tracks(english=Track(["Hello  there", "and welcome\n"])))) == ("Hello there and welcome", None)


def test_without_an_english_track_the_first_track_is_used():
    assert worker.fetch_transcript("x" * 11, api_factory=api(Tracks(other=Track(["Bonjour"]))))[0] == "Bonjour"


@pytest.mark.parametrize("name, reason", [
    ("RequestBlocked", "blocked"), ("IpBlocked", "blocked"), ("TranscriptsDisabled", "no_transcript"), ("VideoUnavailable", "unavailable"),
    ("AgeRestricted", "unavailable"),
])
def test_library_failures_are_typed(name, reason):
    youtube = pytest.importorskip("youtube_transcript_api")
    error = getattr(youtube, name)("x" * 11)
    assert worker.fetch_transcript("x" * 11, api_factory=api(error)) == (None, reason)


def test_other_failures_are_unreadable_and_an_empty_transcript_is_no_transcript():
    assert worker.fetch_transcript("x" * 11, api_factory=api(RuntimeError("boom"))) == (None, "unreadable")
    assert worker.fetch_transcript("x" * 11, api_factory=api(Tracks(english=Track([" "])))) == (None, "no_transcript")


def test_a_transcript_too_large_for_the_request_is_reported_and_left():
    site = Site({ACCEPTED: [video("aaaaaaaaaaa", "2026-11-01T00:00:00.000Z")]})
    _, output, _, _ = run(site, answers={"a" * 11: ("x" * (worker.MAXIMUM_TEXT_BYTES + 1), None)})
    assert outcomes(output) == [("too_large", "reference-aaaaaaaaaaa-v1")] and site.actions == []


def test_the_content_needed_index_is_registered_for_the_client_and_its_fields_are_read_without_failing_an_older_site():
    from papyrus_content import graphql_authoring as g

    definition = g.INDEX_DEFINITIONS[worker.INDEX]
    assert definition["field"] == "listReferencesByContentNeededAndArrival" and definition["partitionKey"] == "contentNeededKey"
    for field in ("captureReason", "contentNeededKey"):
        assert field in g.REFERENCE_FIELDS.split() and field in g.NEWER_REFERENCE_FIELDS and field in g.MEDIUM_REFERENCE_FIELDS


def test_the_partitions_are_corpus_medium_needs_content_and_status():
    assert worker.partitions(["knowledge-corpus-a", "knowledge-corpus-b"], ["accepted"]) == [
        "knowledge-corpus-a#video#needs_content#accepted", "knowledge-corpus-b#video#needs_content#accepted"]
