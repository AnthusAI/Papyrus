"""The fakes of a site whose soft reviews have deadline timers (review-requests.feature, review-deadline-timers.feature): the site's schedule group and wake queue
(schedule_fakes), the request store, and the run that a deadline wake starts. No step is defined here, so any steps file may import it. No network."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests", Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content import agent_wakes, review_requests as rr  # noqa: E402
from papyrus_content.agent_definitions import schedules  # noqa: E402
from papyrus_content.follow_up_timers import FollowUpTimers  # noqa: E402
from papyrus_content.review_deadline_timers import PROCEDURE_KEY, ReviewDeadlineTimers  # noqa: E402
from schedule_fakes import ACCOUNT, ENDPOINT, REGION, TimerScheduler, WakeQueue  # noqa: E402

SITE = "review-site"


class RequestsReadOnlyByIndex(FakeAuthoringClient):
    """The site's API where listing every review request fails the scenario: a read must name a partition of the state index, or a request by its id."""

    def list_records(self, model_name: str, *args, **kwargs):
        if model_name == "ReviewRequest":
            raise AssertionError("something listed every review request")
        return super().list_records(model_name, *args, **kwargs)


class DeadlineSite:
    """A site with its schedule group, its wake queue and the run that handles a deadline wake. ``advance_to(moment)`` fires every timer due by then and runs each wake."""

    def __init__(self, client: FakeAuthoringClient | None = None):
        names = schedules.names_for(SITE)
        self.client = client if client is not None else FakeAuthoringClient()
        self.queue = WakeQueue()
        self.scheduler = TimerScheduler(names.group, self.queue)
        base = {"publicationId": SITE, "appsyncEndpoint": ENDPOINT, "procedureKey": PROCEDURE_KEY}
        self.timers = ReviewDeadlineTimers(FollowUpTimers.for_site(SITE, account=ACCOUNT, region=REGION, client=self.scheduler), base)
        self.wakes: list[dict] = []

    def advance_to(self, moment) -> list[dict]:
        """Fire the timers due by ``moment`` and run each wake they put on the queue, as the runner would: one message at a time, deleted once handled."""
        self.scheduler.fire_until(moment)
        handled = []
        while (message := self.queue.receive()) is not None:
            request = agent_wakes.request_from_event({"Records": [{"eventSource": agent_wakes.SQS_SOURCE, "body": message.body}]})
            handled.append(rr.on_deadline_wake(self.client, request["wakeKey"], now=moment))
            self.queue.delete(message)
        self.wakes.extend(handled)
        return handled

    def entries(self) -> list[str]:
        return sorted(self.scheduler.entries)
