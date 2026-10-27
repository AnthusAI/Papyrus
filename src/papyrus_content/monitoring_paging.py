"""Paging a source until it runs out of news: the collector's one reading loop (docs/monitoring-cloud.md).

A monitor does not read a fixed number of items. It pages a newest-first source until it reaches items it has
already collected (its high-water mark) or the source has no more, and it is bound only by real constraints:
the Lambda's time (`TIME_RESERVE_SECONDS` is kept free to finish the last page and write the receipt) and the
source's rate limit (a 429 is waited out for as long as `Retry-After` says, or, with no header, for a doubling
pause; a pass that cannot wait inside its time stops and continues next pass).

A pass that stops early hands back *resume cursors*. The next pass starts from the top again (new items first,
until it meets items it has seen), then continues at each cursor, so nothing between the two is skipped.

Imports stay light on purpose: stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import time
from typing import Callable

LAMBDA_TIMEOUT_SECONDS = 120.0     # the collector Lambda's timeout (infra/monitoring/papyrus-monitoring.yaml)
TIME_RESERVE_SECONDS = 40.0        # kept free at the end of a pass: the last page's writes, receipt, state, lock
HARD_RESERVE_SECONDS = 15.0        # a page's writes stop here even mid-page; the page is read again next pass
READ_BUDGET_SECONDS = LAMBDA_TIMEOUT_SECONDS - TIME_RESERVE_SECONDS
RATE_LIMIT_FIRST_WAIT_SECONDS = 5.0   # the pause after a 429 that carries no Retry-After; doubles while it persists
RATE_LIMIT_LONGEST_WAIT_SECONDS = 300.0


class RateLimited(Exception):
    """The source answered 429. `retry_after` is the seconds it asked us to wait, when it said."""

    def __init__(self, message: str = "rate limit reached", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def retry_after_seconds(value, *, now: Callable[[], float] = time.time) -> float | None:
    """A `Retry-After` header (delta-seconds or an HTTP date) as seconds from now, or None when absent or unreadable."""
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(text).timestamp() - now())
    except (TypeError, ValueError, OverflowError):
        return None


class Reading:
    """Totals and the clock shared by the queries of one read (or one backfill run)."""

    def __init__(self, budget_seconds: float | None = None, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, emit: Callable[[str], None] | None = None):
        self.clock, self.sleep, self.emit = clock, sleep, emit
        self.started = clock()
        self.deadline = self.started + budget_seconds if budget_seconds else None
        self.hard_deadline = self.deadline + (TIME_RESERVE_SECONDS - HARD_RESERVE_SECONDS) if self.deadline else None
        self.requests, self.stopped_by, self.errors, self.waited = 0, None, [], 0.0
        self._wait = RATE_LIMIT_FIRST_WAIT_SECONDS

    def may_request(self) -> bool:
        if self.stopped_by:
            return False
        if self.deadline is not None and self.clock() > self.deadline:
            self.stopped_by = "time_budget"
        return not self.stopped_by

    def may_write(self) -> bool:
        """False once the Lambda is too close to its timeout to write another item."""
        if self.hard_deadline is not None and self.clock() > self.hard_deadline:
            self.stopped_by = self.stopped_by or "time_budget"
            return False
        return True

    def rate_limited(self, error: RateLimited) -> bool:
        """Wait out a 429 and return True to ask again. False when the wait would not fit in this pass's time
        (the pass stops, `stopped_by` says `rate_limited`, and the next pass continues)."""
        delay = error.retry_after if error.retry_after is not None else self._wait
        if error.retry_after is None:
            self._wait = min(self._wait * 2, RATE_LIMIT_LONGEST_WAIT_SECONDS)
        if self.deadline is not None and self.clock() + delay > self.deadline:
            self.stopped_by = "rate_limited"
            return False
        if self.emit:
            self.emit(f"  rate limited: waiting {delay:.0f}s" + (" (Retry-After)" if error.retry_after is not None else ""))
        self.sleep(delay)
        self.waited += delay
        return True

    def succeeded(self):
        self._wait = RATE_LIMIT_FIRST_WAIT_SECONDS


@dataclass
class Page:
    """What a page's consumer reports: how many of its items were new and how many already collected, whether
    the source's relevant part is over (past the window, under the metric floor), and `retry` when the page
    could not be written in time and must be read again next pass."""
    unseen: int = 0
    seen: int = 0
    end: bool = False
    retry: bool = False


def read_feed(fetch_page: Callable, process_page: Callable, reading: Reading, resume=(), *, stop_at_seen: bool = True) -> list:
    """Page one feed. `fetch_page(cursor)` returns `(rows, next_cursor)` (cursor None starts the feed; a None
    next cursor ends it) and `process_page(rows)` returns a `Page`. Returns the resume cursors for the next pass
    (empty when the feed is finished).

    `stop_at_seen` is for feeds ordered newest first: the first phase reads from the start until a page holds an
    item that was already collected, and each resume cursor is then read until a page of only already-collected
    items closes the gap (pages of items the rule filtered out say nothing and are read through). A feed in any
    other order (by likes, say) has no such mark, so it is read until the source's own end and resumes at its
    one cursor."""
    phases = [None, *resume] if stop_at_seen else [resume[0] if resume else None]
    for index, start in enumerate(phases):
        cursor, head, found_unseen = start, index == 0, False
        rest = phases[index + 1:]
        while True:
            if not reading.may_request():
                return ([cursor] if cursor is not None else []) + rest
            try:
                rows, following = fetch_page(cursor)
            except RateLimited as error:
                if reading.rate_limited(error):
                    continue
                return ([cursor] if cursor is not None else []) + rest
            reading.succeeded()
            reading.requests += 1
            page = process_page(rows)
            if page.retry:
                return ([cursor] if cursor is not None else []) + rest
            found_unseen = found_unseen or page.unseen > 0
            cursor = following
            if page.end or cursor is None:
                return []    # the source is read to its end: nothing lies further out
            if stop_at_seen:
                if head and page.seen:
                    break    # the high-water mark: everything older was collected by an earlier pass
                if not head and found_unseen and page.seen and not page.unseen:
                    break    # this gap is closed; the next one (if any) is further out
    return []
