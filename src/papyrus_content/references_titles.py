"""`papyrus references repair-titles`: the one-time repair for References whose title is their own web address (PPY-a1e2b0ea).

New References are fixed as they are created (``reference_titles.py``: the link preview and capture write the page's title). This command repairs the ones
that already exist. It runs on the signed-in lane (``papyrus login``, no AWS credentials) and goes through the ``correctReferenceCapture`` action, as you.

It reads References a page at a time from the feed-state index (never a scan), keeps the ones whose title is empty or an address, and for each looks for
the page's real title in what the newsroom already stores:

1. the preview attachment's ``title`` (what the link preview read from the page), then
2. the curation card's ``page.title`` (what capture read).

A Reference with a stored title is **fixable without a fetch**. One with neither needs the page read again: that happens only with ``--fetch``
(and ``--write``), paced, one page per Reference; a page that is blocked, unreadable or declares no usable title is left as it is and said so. The card
then shows a readable name made from the site and the address's own words (``reference_titles.readable_name``), never the raw address, and the next run
tries it again. A title that is not an address is never touched: the server checks that again before it writes.

It previews by default: reads only, nothing fetched or written. ``--write`` records the stored titles; ``--fetch`` as well reads the rest.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TextIO

from . import signed_in_lane as lane
from .link_exploration import explore
from .operator_errors import GraphQLRequestError
from .reference_curation_store import read_card
from .reference_images import preview_attachment_id
from .reference_titles import first_usable_title, needs_title, readable_name
from .references_transcripts import CORRECT_MUTATION, corpus_ids_of, statuses_from
from .signed_in_lane import Refusal

DEFAULT_STATUSES = ("accepted", "pending")
DEFAULT_PACE_SECONDS = 1.0
FEED_PARTITIONS = {"pending": "unrated", "accepted": "rated", "rejected": "rated"}
OLD_SITE = "Unsupported correction fields"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="papyrus references repair-titles", add_help=True,
        description="Give References whose title is a web address the page's real title, as the signed-in editor (no AWS credentials). Previews by default: "
                    "reads only. --write records titles already stored with the Reference; --fetch (with --write) reads the pages of the rest.")
    parser.add_argument("--site", help="Which signed-in site, such as newsroom.machines-on-machines.anth.us (needed when several are signed in)")
    parser.add_argument("--corpus-key", help="Corpus key or comma-separated keys (knowledge-corpus-<key>). Default: every corpus the site lists")
    parser.add_argument("--status", default=",".join(DEFAULT_STATUSES),
                        help="Curation statuses to cover, comma-separated from pending, accepted, rejected, or all (default: accepted,pending)")
    parser.add_argument("--limit", type=int, help="Stop after this many References with an address title (default: no limit)")
    parser.add_argument("--pace", type=float, default=DEFAULT_PACE_SECONDS, help=f"Seconds to wait between page reads with --fetch (default {DEFAULT_PACE_SECONDS:g})")
    parser.add_argument("--fetch", action="store_true", help="With --write: read the page of a Reference that has no stored title. Without it nothing is fetched.")
    parser.add_argument("--write", action="store_true", help="Record the titles. Without it the command only lists what it would do.")
    return parser


def address_titled(client: Any, corpus_ids: Iterable[str], statuses: Iterable[str]) -> Iterator[dict[str, Any]]:
    """Current References of the chosen statuses whose title is empty or an address, newest first within each partition (a page at a time, never a scan)."""
    wanted = set(statuses)
    for corpus_id in corpus_ids:
        for partition in dict.fromkeys(FEED_PARTITIONS[status] for status in wanted):
            for row in client.iterate_newest_first("referencesByFeedStateAndArrival", f"{corpus_id}#{partition}"):
                if row.get("curationStatus") in wanted and needs_title(row) and str(row.get("sourceUri") or "").lower().startswith(("http://", "https://")):
                    yield row


def stored_title(client: Any, row: dict[str, Any]) -> tuple[str | None, str | None]:
    """The page title already held for this Reference and where it came from (``preview`` or ``capture``), or ``(None, None)``. Two reads, no fetch."""
    attachment = client.get_record("ReferenceAttachment", preview_attachment_id(row))
    metadata = (attachment or {}).get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    found = first_usable_title((metadata or {}).get("title") if isinstance(metadata, dict) else None)
    if found:
        return found, "preview"
    card = read_card(client, row) or {}
    found = first_usable_title((card.get("page") or {}).get("title"))
    return (found, "capture") if found else (None, None)


class Run:
    def __init__(self, client: Any, *, statuses: list[str], corpus_ids: list[str], limit: int | None, pace: float, write: bool, fetch_pages: bool,
                 out: TextIO, explorer: Callable[..., Any] = explore, sleep: Callable[[float], None] = time.sleep) -> None:
        self.client, self.statuses, self.corpus_ids, self.limit, self.pace = client, statuses, corpus_ids, limit, pace
        self.write, self.fetch_pages, self.out, self.explorer, self.sleep = write, fetch_pages, out, explorer, sleep
        self.counts: dict[str, int] = {}
        self.fetched = False

    def line(self, outcome: str, row: dict[str, Any], detail: str = "") -> None:
        self.counts[outcome] = self.counts.get(outcome, 0) + 1
        print("\t".join(["references", "repair-titles", outcome, str(row.get("id")), str(row.get("sourceUri") or "")[:80], detail]), file=self.out, flush=True)

    def execute(self) -> int:
        handled = 0
        for row in address_titled(self.client, self.corpus_ids, self.statuses):
            if self.limit is not None and handled >= self.limit:
                break
            handled += 1
            try:
                self.handle(row)
            except GraphQLRequestError as error:
                self.line("failed", row, f"request failed: {str(error).splitlines()[0][:200]}; left for the next run")
        self.summary()
        return 0

    def summary(self) -> None:
        parts = ", ".join(f"{name} {count}" for name, count in sorted(self.counts.items())) or "no References with an address for a title"
        print(f"references\trepair-titles\tdone\t{parts}", file=self.out, flush=True)
        if not self.write and self.counts:
            print("references\trepair-titles\tnext\tthis was a preview; run again with --write to record the stored titles (add --fetch to read the other pages)",
                  file=self.out, flush=True)

    def handle(self, row: dict[str, Any]) -> None:
        title, source = stored_title(self.client, row)
        if title:
            if self.write:
                if self.record(row, title):
                    self.line("set", row, f"{source}\t{title[:80]}")
            else:
                self.line("would_set", row, f"{source}\t{title[:80]}")
            return
        if not (self.write and self.fetch_pages):
            self.line("needs_fetch" if self.write else "would_fetch", row, "no stored title")
            return
        if self.fetched:
            self.sleep(self.pace)
        self.fetched = True
        found = self.explorer(str(row["sourceUri"]), want_text=False, use_search=False)
        page_title = first_usable_title(found.metadata.title if found.metadata else None)
        if page_title is None:
            reason = "the page declares no usable title" if found.ok or found.metadata else f"page not readable: {found.failure or 'unknown'}"
            self.line("no_title", row, f"{reason}; the card shows {readable_name(str(row['sourceUri']), found.metadata.site_name if found.metadata else None)!r}")
            return
        if self.record(row, page_title):
            self.line("set", row, f"fetched\t{page_title[:80]}")

    def record(self, row: dict[str, Any], title: str) -> bool:
        """The action as the signed-in editor. False (and a line) when the site declines one Reference; the run goes on."""
        try:
            answer = lane.fetch(self.client, CORRECT_MUTATION, "correctReferenceCapture", {"input": json.dumps({"referenceId": row["id"], "pageTitle": title})},
                                noun="Saving the title", forbidden=lambda: Refusal(
                                    "Refused: repairing titles is for editors and admins; your signed-in account does not have that access."))
        except Refusal as refusal:
            if "does not have that access" in str(refusal):
                raise
            self.line("failed", row, str(refusal))
            return False
        if isinstance(answer, dict) and answer.get("ok") is False:
            message = str((answer.get("errors") or [{}])[0].get("message") or "the site refused the title")
            if OLD_SITE in message:
                raise Refusal("This site's backend does not accept page titles yet. It ships in the release that carries this command; deploy the site first.")
            self.line("failed", row, message)
            return False
        if isinstance(answer, dict) and answer.get("changed") is False:
            self.line("already_titled", row, str(answer.get("title") or "")[:80])
            return False
        return True


def command(argv: list[str], *, client=None, out: TextIO | None = None, explorer: Callable[..., Any] | None = None,
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
        if args.fetch and not args.write:
            raise Refusal("--fetch reads pages and so only goes with --write; the preview reads nothing but the site's own records.")
        client = client or lane.client(args.site)
        corpus_ids = corpus_ids_of(client, args.corpus_key)
        mode = "write" + (" with page reads" if args.fetch else " (stored titles only)") if args.write else "preview (reads only; add --write)"
        print(f"references\trepair-titles\tmode\t{mode}\t{', '.join(statuses)}\t{', '.join(corpus_ids)}", file=out, flush=True)
        run = Run(client, statuses=statuses, corpus_ids=corpus_ids, limit=args.limit, pace=args.pace, write=args.write, fetch_pages=args.fetch, out=out,
                  **({"explorer": explorer} if explorer else {}), sleep=sleep)
        return run.execute()
    except GraphQLRequestError as error:
        print(f"Request failed: {str(error).splitlines()[0][:300]}", file=sys.stderr)
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
