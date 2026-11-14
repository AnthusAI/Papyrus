"""`papyrus references capture-thumbnails`: give every video Reference its own thumbnail, copied into our storage, from a connection the platform answers.

This is the thumbnail half of the transcript worker's job and uses the same lane (``references_transcripts.py``): a person signed in with
`papyrus login` runs it where YouTube answers, with no AWS profile and no new permission. For each video it

1. fetches the thumbnail (``reference_thumbnails.py``: YouTube's ``img.youtube.com`` address built from the video id, an oEmbed answer for the other
   platforms), and checks it is a real picture, not YouTube's grey stand-in;
2. puts the original in the site's media bucket at ``media/assets/reference-thumbnails/<hash>.<ext>`` with the signed-in editor's identity-pool
   credentials, the way ``papyrus stories save-version --images`` puts story pictures there;
3. records the path on the Reference with the ``correctReferenceCapture`` action (as the signed-in editor), which is what the next home-page snapshot
   publishes as the card's image. A video the platform has no thumbnail for is recorded as ``none``.

It reads videos through the medium index (``listReferencesByMediumFeedAndArrival``), newest first, and skips every video that already holds a value
(including ``none``), so each video is fetched once however often this runs. The first run is the backfill. It previews by default (no network, no
writes), like ``backfill-medium``; ``--write`` does the work.

Nothing in the cloud fetches a thumbnail: whether ``img.youtube.com`` answers cloud addresses has not been measured, and YouTube refuses them for transcripts.
"""
from __future__ import annotations

import argparse
import heapq
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, TextIO

from . import signed_in_lane as lane
from .operator_errors import GraphQLRequestError
from .reference_medium import MEDIUM_VIDEO, iterate_references_by_medium
from .reference_thumbnails import (FIELD, NO_THUMBNAIL, NoThumbnail, Thumbnail, Unreachable, fetch_thumbnail, media_key, none_request, platform_of,
                                   stored_request)
from .references_transcripts import CORRECT_MUTATION, EXIT_BLOCKED, corpus_ids_of, statuses_from
from .signed_in_lane import Refusal

DEFAULT_STATUSES = ("accepted", "pending")
DEFAULT_PACE_SECONDS = 1.0
STOP_AFTER_UNREACHABLE = 3   # consecutive "could not ask": the platform is refusing this connection, so stop instead of hammering it
BLOCKED_ADVICE = ("The platforms did not answer from this connection several times in a row. Run this where YouTube and the other video sites answer "
                  "(a home or office network, not a cloud machine); the videos not done yet are still waiting.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="papyrus references capture-thumbnails", add_help=True,
        description="Give each video Reference its own thumbnail, copied into the site's media storage and recorded on the Reference, as the signed-in "
                    "editor (no AWS credentials). Previews by default: nothing is fetched or written without --write. Run it on a connection the video "
                    "platforms answer.")
    parser.add_argument("--site", help="Which signed-in site, such as shipped.anth.us (needed when several are signed in)")
    parser.add_argument("--corpus-key", help="Corpus key or comma-separated keys (knowledge-corpus-<key>). Default: every corpus the site lists")
    parser.add_argument("--status", default=",".join(DEFAULT_STATUSES),
                        help="Curation statuses to cover, comma-separated from pending, accepted, rejected, or all (default: accepted,pending)")
    parser.add_argument("--limit", type=int, help="Stop after this many videos (default: no limit)")
    parser.add_argument("--pace", type=float, default=DEFAULT_PACE_SECONDS, help=f"Seconds to wait between videos (default {DEFAULT_PACE_SECONDS:g})")
    parser.add_argument("--bucket", help="The media bucket (default: the one the signed-in site publishes)")
    parser.add_argument("--identity-pool-id", help="The site's identity pool (default: the one the signed-in site publishes)")
    parser.add_argument("--write", action="store_true", help="Fetch, store and record. Without it the command only lists what it would do.")
    return parser


def waiting_videos(client: Any, corpus_ids: Iterable[str], statuses: Iterable[str]) -> Iterator[dict[str, Any]]:
    """Current video References of every corpus and status, newest arrival first across all of them, a page at a time (never a scan)."""
    streams = [iterate_references_by_medium(client, corpus_id, MEDIUM_VIDEO, status) for corpus_id in corpus_ids for status in statuses]
    yield from heapq.merge(*streams, key=lambda row: str(row.get("feedArrivalAt") or ""), reverse=True)


def upload_with(store: Any) -> Callable[[str, Thumbnail], None]:
    def upload(path: str, thumbnail: Thumbnail) -> None:
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder) / f"thumbnail.{thumbnail.extension}"
            local.write_bytes(thumbnail.data)
            store.put(media_key(path), local, content_type=thumbnail.media_type, sha256=thumbnail.sha256)
    return upload


class Run:
    def __init__(self, client: Any, *, statuses: list[str], corpus_ids: list[str], pace: float, limit: int | None, write: bool, out: TextIO,
                 fetch: Callable[[str], Thumbnail] = fetch_thumbnail, upload: Callable[[str, Thumbnail], None] | None = None,
                 open_store: Callable[[], Any] | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self.client, self.statuses, self.corpus_ids = client, statuses, corpus_ids
        self.pace, self.limit, self.write, self.out = pace, limit, write, out
        self.fetch, self.upload, self.open_store, self.sleep = fetch, upload, open_store, sleep
        self.counts: dict[str, int] = {}
        self.unreachable_in_a_row = 0
        self.asked = False

    def line(self, outcome: str, row: dict[str, Any], detail: str = "") -> None:
        self.counts[outcome] = self.counts.get(outcome, 0) + 1
        print("\t".join(["references", "capture-thumbnails", outcome, str(row.get("id")), " ".join(str(row.get("title") or "-").split())[:80], detail]),
              file=self.out, flush=True)

    def execute(self) -> int:
        """0 when every video was handled or left for next time, EXIT_BLOCKED when the platforms kept refusing this connection."""
        handled = 0
        try:
            for row in waiting_videos(self.client, self.corpus_ids, self.statuses):
                if row.get(FIELD):
                    self.counts["already_have"] = self.counts.get("already_have", 0) + 1
                    continue
                if self.limit is not None and handled >= self.limit:
                    break
                handled += 1
                try:
                    self.handle(row)
                except GraphQLRequestError as error:
                    self.line("failed", row, f"request failed: {str(error).splitlines()[0][:200]}; left for the next run")
        except Unreachable:
            print(BLOCKED_ADVICE, file=sys.stderr, flush=True)
            self.summary(stopped="blocked")
            return EXIT_BLOCKED
        self.summary()
        return 0

    def summary(self, stopped: str | None = None) -> None:
        parts = ", ".join(f"{name} {count}" for name, count in sorted(self.counts.items())) or "no videos"
        print(f"references\tcapture-thumbnails\tdone\t{parts}" + (f"\tstopped: {stopped}; run again to continue" if stopped else ""), file=self.out, flush=True)
        if not self.write and self.counts.get("would_fetch"):
            print("references\tcapture-thumbnails\tnext\tthis was a preview; run again with --write to fetch, store and record them", file=self.out, flush=True)

    def handle(self, row: dict[str, Any]) -> None:
        address = str(row.get("sourceUri") or "")
        platform = platform_of(address)
        if platform is None:
            self.line("not_a_video", row, "the address is not a video on a known platform")
            return
        if not self.write:
            self.line("would_fetch", row, platform)
            return
        fresh = self.client.get_record("Reference", row["id"])
        if fresh and fresh.get(FIELD):
            self.line("already_have", row)   # recorded by another run since the index was read
            return
        if self.asked:
            self.sleep(self.pace)
        self.asked = True
        try:
            thumbnail = self.fetch(address)
        except NoThumbnail as reason:
            self.unreachable_in_a_row = 0
            if self.record(row, none_request(str(reason))):
                self.line("none", row, f"{platform}\t{reason}")
            return
        except Unreachable as reason:
            self.unreachable_in_a_row += 1
            self.line("failed", row, f"{platform}\t{str(reason)[:160]}; left for the next run")
            if self.unreachable_in_a_row >= STOP_AFTER_UNREACHABLE:
                raise
            return
        self.unreachable_in_a_row = 0
        request = stored_request(row, thumbnail)
        self.store(request["path"], thumbnail)
        if self.record(row, request):
            self.line("stored", row, f"{platform}\t{thumbnail.width}x{thumbnail.height}\t{request['path']}")

    def store(self, path: str, thumbnail: Thumbnail) -> None:
        try:
            if self.upload is None:
                self.upload = upload_with(self.open_store())
            self.upload(path, thumbnail)
        except Refusal:
            raise
        except Exception as error:  # noqa: BLE001 - a storage fault is the same for every video: stop and say so
            raise Refusal(f"Could not store the picture in the site's media bucket: {type(error).__name__}: {str(error)[:200]}") from error

    def record(self, row: dict[str, Any], request: dict[str, Any]) -> bool:
        """The capture action as the signed-in editor. False (and a line) when the site refuses one video; the run goes on."""
        try:
            answer = lane.fetch(self.client, CORRECT_MUTATION, "correctReferenceCapture", {"input": json.dumps({"referenceId": row["id"], "thumbnail": request})},
                                noun="Saving the thumbnail", forbidden=lambda: Refusal(
                                    "Refused: saving thumbnails is for editors and admins; your signed-in account does not have that access."))
        except Refusal as refusal:
            if "does not have that access" in str(refusal):
                raise
            self.line("failed", row, str(refusal))
            return False
        if isinstance(answer, dict) and answer.get("ok") is False:
            errors = answer.get("errors") or [{}]
            self.line("failed", row, str(errors[0].get("message") or "the site refused the thumbnail"))
            return False
        return True


def command(argv: list[str], *, client=None, out: TextIO | None = None, fetch: Callable[[str], Thumbnail] | None = None,
            upload: Callable[[str, Thumbnail], None] | None = None, sleep: Callable[[float], None] = time.sleep) -> int:
    out = out or sys.stdout
    os.environ["PAPYRUS_GRAPHQL_AUTH"] = "user"   # the signed-in lane only; never IAM
    try:
        args = build_parser().parse_args(argv)
        statuses = statuses_from(args.status)
        if args.limit is not None and args.limit < 1:
            raise Refusal("--limit must be at least 1.")
        if args.pace < 0:
            raise Refusal("--pace cannot be negative.")
        client = client or lane.client(args.site)
        corpus_ids = corpus_ids_of(client, args.corpus_key)
        print(f"references\tcapture-thumbnails\tmode\t{'write' if args.write else 'preview (nothing is fetched or written; add --write)'}\t{', '.join(statuses)}\t{', '.join(corpus_ids)}",
              file=out, flush=True)

        def open_store() -> Any:
            from .story_images import open_media_store
            return open_media_store(args.bucket, args.identity_pool_id)

        run = Run(client, statuses=statuses, corpus_ids=corpus_ids, pace=args.pace, limit=args.limit, write=args.write, out=out,
                  **({"fetch": fetch} if fetch else {}), upload=upload, open_store=open_store, sleep=sleep)
        return run.execute()
    except GraphQLRequestError as error:
        text = str(error)
        if "thumbnailPath" in text or "FieldUndefined" in text:
            print("This site's data API does not have the thumbnail field yet. It ships in the release that carries this command; deploy the site first.", file=sys.stderr)
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
