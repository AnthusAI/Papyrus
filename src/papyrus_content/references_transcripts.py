"""`papyrus references capture-transcripts`: the transcripts of videos the newsroom holds no content for, read from a non-cloud connection.

YouTube refuses cloud addresses (measured: 39 of 40 attempts from the monitoring router in 30 days were blocked; the same call from a home connection
worked), so no cloud function tries. A person signed in with `papyrus login` runs this where YouTube answers, and it writes what it reads the way the
newsroom's capture panel does: the `correctReferenceCapture` action, as the signed-in editor, with no AWS credentials and no new permission. Nothing
depends on one particular machine being on; anyone signed in can run it, and a second run picks up where the first stopped.

Which videos: the sparse index `listReferencesByContentNeededAndArrival` (partition `<corpusId>#video#needs_content#<status>`, newest first), one
partition per corpus and curation status. A video leaves the index when its content is captured or when the worker records that nothing can be
(`no_transcript`, `unavailable`, `unsupported_platform`), so nothing is read twice and nothing is filtered after reading. The partitions are merged by arrival,
newest first. Stars are not part of the index (a vote would have to rewrite a composite sort key), so the order is newest first, not most valuable first.

The transcript is a third party's text. It is stored as the Reference's text and read as data by every later step; nothing here or after it treats it as
an instruction.
"""
from __future__ import annotations

import argparse
import heapq
import json
import os
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TextIO

from .tenant_knowledge_keys import corpus_id_for_key
from . import signed_in_lane as lane
from .operator_errors import GraphQLRequestError
from .reference_capture_state import SETTLED_CAPTURE_REASONS
from .reference_feed_keys import NEEDS_CONTENT
from .reference_medium import MEDIUM_VIDEO
from .signed_in_lane import Refusal
from .youtube_transcript import video_id

INDEX = "referencesByContentNeededAndArrival"
STATUSES = ("pending", "accepted", "rejected")
DEFAULT_STATUSES = ("accepted", "pending")
DEFAULT_PACE_SECONDS = 3.0
BACKOFF_SECONDS = (60.0, 300.0)   # waits before trying the same video again after YouTube refuses; then the run stops
MAXIMUM_TEXT_BYTES = 900_000      # the data API takes a request of about 1 MB
EXIT_BLOCKED = 3
CLOUD_HINTS = ("AWS_LAMBDA_FUNCTION_NAME", "AWS_EXECUTION_ENV", "ECS_CONTAINER_METADATA_URI_V4", "ECS_CONTAINER_METADATA_URI", "GITHUB_ACTIONS",
               "CODEBUILD_BUILD_ID", "CODESPACES", "KUBERNETES_SERVICE_HOST", "CLOUD_SHELL", "GOOGLE_CLOUD_PROJECT")
CORRECT_MUTATION = "mutation CorrectReferenceCapture($input: AWSJSON!) { correctReferenceCapture(input: $input) }"
NOTE = "Transcript read from YouTube by papyrus references capture-transcripts."
BLOCKED_ADVICE = ("YouTube is refusing requests from this connection. It blocks cloud and data-centre addresses, so this command needs a non-cloud "
                  "connection, such as a home or office network. Run it there; the videos not done yet are still waiting.")
LIBRARY_ADVICE = ("Reading transcripts needs the youtube-transcript-api package, which a base install does not carry. Install the optional extra "
                  "(`poetry install --extras transcripts`, or `pip install \"papyrus-newsroom[transcripts]\"`) and run this again.")


class Blocked(Exception):
    """YouTube refused this connection."""


class LibraryMissing(Exception):
    """The optional youtube-transcript-api extra is not installed."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="papyrus references capture-transcripts", add_help=True,
        description="Read the transcripts of videos that have no captured content and save them, as the signed-in editor (no AWS credentials). "
                    "Run it on a non-cloud connection: YouTube refuses cloud addresses. Writes unless --dry-run.")
    parser.add_argument("--site", help="Which signed-in site, such as shipped.anth.us (needed when several are signed in)")
    parser.add_argument("--corpus-key", help="Corpus key or comma-separated keys (knowledge-corpus-<key>). Default: every corpus the site lists")
    parser.add_argument("--status", default=",".join(DEFAULT_STATUSES),
                        help="Curation statuses to cover, comma-separated from pending, accepted, rejected, or all (default: accepted,pending)")
    parser.add_argument("--limit", type=int, help="Stop after this many videos (default: no limit)")
    parser.add_argument("--pace", type=float, default=DEFAULT_PACE_SECONDS, help=f"Seconds to wait between requests to YouTube (default {DEFAULT_PACE_SECONDS:g})")
    parser.add_argument("--dry-run", action="store_true", help="List the videos that would be read; contact neither YouTube nor the data API's write path")
    return parser


def statuses_from(text: str) -> list[str]:
    chosen = [part.strip().lower() for part in text.split(",") if part.strip()]
    if chosen == ["all"]:
        return list(STATUSES)
    unknown = [part for part in chosen if part not in STATUSES]
    if unknown or not chosen:
        raise Refusal("--status takes pending, accepted, rejected or all (comma-separated).")
    return list(dict.fromkeys(chosen))


def cloud_environment() -> str | None:
    """The name of an environment variable that says this process runs on a cloud service, or None."""
    return next((name for name in CLOUD_HINTS if os.environ.get(name)), None)


def partitions(corpus_ids: Iterable[str], statuses: Iterable[str]) -> list[str]:
    return [f"{corpus_id}#{MEDIUM_VIDEO}#{NEEDS_CONTENT}#{status}" for corpus_id in corpus_ids for status in statuses]


def waiting_videos(client: Any, corpus_ids: Iterable[str], statuses: Iterable[str]) -> Iterator[dict[str, Any]]:
    """The References waiting for content, newest arrival first across every partition, read a page at a time (never a scan)."""
    streams = [client.iterate_newest_first(INDEX, partition) for partition in partitions(corpus_ids, statuses)]
    yield from heapq.merge(*streams, key=lambda row: str(row.get("feedArrivalAt") or ""), reverse=True)


# --- the transcript --------------------------------------------------------------------------------------------------------------------


def _reason(error: Exception) -> str:
    from youtube_transcript_api import (AgeRestricted, InvalidVideoId, NoTranscriptFound, RequestBlocked, TranscriptsDisabled,
                                        VideoUnavailable, VideoUnplayable, YouTubeRequestFailed)

    if isinstance(error, RequestBlocked) or (isinstance(error, YouTubeRequestFailed) and "429" in str(error)):
        return "blocked"
    if isinstance(error, (TranscriptsDisabled, NoTranscriptFound)):
        return "no_transcript"
    if isinstance(error, (VideoUnavailable, VideoUnplayable, InvalidVideoId, AgeRestricted)):
        return "unavailable"
    return "unreadable"


def fetch_transcript(identifier: str, *, api_factory: Callable[[], object] | None = None) -> tuple[str | None, str | None]:
    """``(text, None)`` with the spoken words as one paragraph, or ``(None, reason)``: ``blocked``, ``no_transcript``, ``unavailable`` or ``unreadable``.
    English when offered, else the first track. Raises ``LibraryMissing`` when the optional extra is not installed."""
    try:
        if api_factory is None:
            from youtube_transcript_api import YouTubeTranscriptApi as api_factory  # noqa: N813
    except ImportError as error:
        raise LibraryMissing from error
    try:
        tracks = api_factory().list(identifier)
        try:
            track = tracks.find_transcript(["en"])
        except Exception:  # noqa: BLE001 - no English track: take whatever YouTube offers first
            track = next(iter(tracks))
        text = " ".join(" ".join(snippet.text.split()) for snippet in track.fetch()).strip()
    except Exception as error:  # noqa: BLE001 - every library failure is a typed outcome
        return None, _reason(error)
    return (text, None) if text else (None, "no_transcript")


# --- the run -----------------------------------------------------------------------------------------------------------------------------


class Run:
    def __init__(self, client: Any, *, statuses: list[str], corpus_ids: list[str], pace: float, limit: int | None, dry_run: bool, out: TextIO,
                 fetch: Callable[[str], tuple[str | None, str | None]] = fetch_transcript, sleep: Callable[[float], None] = time.sleep) -> None:
        self.client, self.statuses, self.corpus_ids = client, statuses, corpus_ids
        self.pace, self.limit, self.dry_run, self.out = pace, limit, dry_run, out
        self.fetch, self.sleep = fetch, sleep
        self.counts: dict[str, int] = {}
        self.fetched: dict[str, tuple[str | None, str | None]] = {}
        self.asked_youtube = False

    def line(self, outcome: str, row: dict[str, Any], detail: str = "") -> None:
        self.counts[outcome] = self.counts.get(outcome, 0) + 1
        print("\t".join(["references", "capture-transcripts", outcome, str(row.get("id")), " ".join(str(row.get("title") or "-").split())[:80], detail]),
              file=self.out, flush=True)

    def execute(self) -> int:
        """The exit status: 0 when every video was handled or left for next time, EXIT_BLOCKED when YouTube refused this connection."""
        handled = 0
        try:
            for row in waiting_videos(self.client, self.corpus_ids, self.statuses):
                if self.limit is not None and handled >= self.limit:
                    break
                handled += 1
                try:
                    self.handle(row)
                except GraphQLRequestError as error:   # one video's request failed: say so and go on
                    self.line("failed", row, f"request failed: {str(error).splitlines()[0][:200]}; left for the next run")
        except Blocked:
            print(BLOCKED_ADVICE, file=sys.stderr, flush=True)
            if cloud_environment():
                print(f"This looks like a cloud machine ({cloud_environment()} is set).", file=sys.stderr, flush=True)
            self.summary(stopped="blocked")
            return EXIT_BLOCKED
        self.summary()
        return 0

    def summary(self, stopped: str | None = None) -> None:
        parts = ", ".join(f"{name} {count}" for name, count in sorted(self.counts.items())) or "nothing waiting"
        print(f"references\tcapture-transcripts\tdone\t{parts}" + (f"\tstopped: {stopped}; run again to continue" if stopped else ""), file=self.out, flush=True)
        if self.counts.get("captured") and not self.dry_run:
            print("references\tcapture-transcripts\tnext\tthe summaries of the captured videos are marked stale; the next `papyrus references curate` "
                  "run (--status accepted or pending) rewrites them from the transcripts", file=self.out, flush=True)

    def handle(self, row: dict[str, Any]) -> None:
        address = str(row.get("sourceUri") or "")
        identifier = video_id(address)
        if self.dry_run:
            self.line("would_read" if identifier else "would_record_unsupported_platform", row, identifier or "-")
            return
        fresh = self.client.get_record("Reference", row["id"])
        if not fresh or not fresh.get("contentNeededKey"):
            self.line("already_handled", row)   # captured by a person or another run since the index was read
            return
        if identifier is None:
            self.record(row, "unsupported_platform", "no transcript reader for this video platform")
            return
        text, reason = self.read(identifier)
        if text is not None:
            self.save(row, identifier, text)
        elif reason in ("no_transcript", "unavailable"):
            self.record(row, reason, identifier)
        else:
            self.line("failed", row, f"{identifier}\t{reason}; left for the next run")

    def read(self, identifier: str) -> tuple[str | None, str | None]:
        if identifier in self.fetched:
            return self.fetched[identifier]
        if self.asked_youtube:
            self.sleep(self.pace)
        self.asked_youtube = True
        for wait in (*BACKOFF_SECONDS, None):
            text, reason = self.fetch(identifier)
            if reason != "blocked":
                break
            if wait is None:
                raise Blocked
            print(f"references\tcapture-transcripts\tbacking_off\t{wait:g} seconds: YouTube refused the request", file=self.out, flush=True)
            self.sleep(wait)
        self.fetched[identifier] = (text, reason)
        return text, reason

    def save(self, row: dict[str, Any], identifier: str, text: str) -> None:
        if len(text.encode("utf-8")) > MAXIMUM_TEXT_BYTES:
            self.line("too_large", row, f"{identifier}\t{len(text)} characters; paste it in the newsroom instead")
            return
        if self.correct(row, {"text": text, "assessment": "incomplete", "note": NOTE}):
            self.line("captured", row, f"{identifier}\t{len(text)} characters")

    def record(self, row: dict[str, Any], reason: str, detail: str) -> None:
        if reason in SETTLED_CAPTURE_REASONS and self.correct(row, {"captureReason": reason}):
            self.line(reason, row, detail + "; left for a person in To capture")

    def correct(self, row: dict[str, Any], payload: dict[str, Any]) -> bool:
        """The newsroom's own capture action, as the signed-in editor. False (and a line) when the site refuses; the run goes on."""
        try:
            answer = lane.fetch(self.client, CORRECT_MUTATION, "correctReferenceCapture", {"input": json.dumps({"referenceId": row["id"], **payload})},
                                noun="Saving the capture", forbidden=lambda: Refusal(
                                    "Refused: saving captures is for editors and admins; your signed-in account does not have that access."))
        except Refusal as refusal:
            if "does not have that access" in str(refusal):
                raise
            self.line("failed", row, str(refusal))
            return False
        if isinstance(answer, dict) and answer.get("ok") is False:
            errors = answer.get("errors") or [{}]
            self.line("failed", row, str(errors[0].get("message") or "the site refused the capture"))
            return False
        return True


def corpus_ids_of(client: Any, corpus_keys: str | None) -> list[str]:
    keys = [key.strip() for key in (corpus_keys or "").split(",") if key.strip()]
    if keys:
        return [corpus_id_for_key(key) for key in dict.fromkeys(keys)]
    from .editorial_context import hosted_publication
    try:
        return [hosted_publication(client)["corpusId"]]   # the site's one canonical publication corpus, read through its role index (the corpus `reporting create` uses)
    except ValueError as missing:
        raise Refusal(f"{missing} Name one with --corpus-key.") from None


def command(argv: list[str], *, client=None, out: TextIO | None = None, fetch: Callable[[str], tuple[str | None, str | None]] | None = None,
            sleep: Callable[[float], None] = time.sleep) -> int:
    out = out or sys.stdout
    os.environ["PAPYRUS_GRAPHQL_AUTH"] = "user"   # the signed-in lane only; never IAM
    try:
        args = build_parser().parse_args(argv)
        statuses = statuses_from(args.status)
        if args.limit is not None and args.limit < 1:
            raise Refusal("--limit must be at least 1.")
        if args.pace < 0:
            raise Refusal("--pace cannot be negative.")
        if not args.dry_run and fetch is None:
            try:
                import youtube_transcript_api  # noqa: F401
            except ImportError:
                raise Refusal(LIBRARY_ADVICE) from None
            if cloud_environment():
                print(f"Warning: {cloud_environment()} is set, so this looks like a cloud machine. YouTube refuses cloud addresses; "
                      "run this on a non-cloud connection.", file=sys.stderr, flush=True)
        client = client or lane.client(args.site)
        corpus_ids = corpus_ids_of(client, args.corpus_key)
        print(f"references\tcapture-transcripts\tmode\t{'dry run (nothing is read or written)' if args.dry_run else 'write'}\t{', '.join(statuses)}\t{', '.join(corpus_ids)}",
              file=out, flush=True)
        run = Run(client, statuses=statuses, corpus_ids=corpus_ids, pace=args.pace, limit=args.limit, dry_run=args.dry_run, out=out,
                  **({"fetch": fetch} if fetch else {}), sleep=sleep)
        return run.execute()
    except LibraryMissing:
        print(LIBRARY_ADVICE, file=sys.stderr)
        return 2
    except GraphQLRequestError as error:
        text = str(error)
        if "ontentNeeded" in text or "FieldUndefined" in text:
            print("This site's data API does not have the content-needed index yet. It ships in a later deploy than the medium index; once it is live, "
                  "run `papyrus references backfill-medium --write` for the site, then this command (docs/reference-feed-indexes.md).", file=sys.stderr)
        else:
            print(f"Request failed: {text.splitlines()[0][:300]}", file=sys.stderr)
        return 2
    except Refusal as refusal:
        print(str(refusal), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Stopped. Run it again to continue where it left off.", file=sys.stderr)
        return 130
    except ValueError as error:   # AuthError (signed out, expired, no site configured) is a ValueError
        print(f"Not signed in or session unusable: {str(error).splitlines()[0]}", file=sys.stderr)
        return 2
