"""Roundup drafts, approval, the start-send guards, the paced worker and test send, against moto's DynamoDB and fakes.

Placeholders only: reader addresses are @example.com and the postal address is a made-up example. Nothing here reads SSM.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import pytest
from botocore.exceptions import ClientError

from papyrus_content.newsletter import addresses, ops_proxy
from papyrus_content.newsletter.compliance import Compliance
from papyrus_content.newsletter.compose import MANAGE_PLACEHOLDER, UNSUBSCRIBE_PLACEHOLDER, content_hash
from papyrus_content.newsletter.handler import Newsletter, Settings
from papyrus_content.newsletter.issues import EDITED_NOTE, IssueService
from papyrus_content.newsletter.mailer import Mailer
from papyrus_content.newsletter.newsletter_test import START, THEME, FakeSes, Harness, running_harness
from papyrus_content.newsletter.postal import PostalAddress
from papyrus_content.newsletter.scheduler import at_expression, effective_send_time, schedule_name
from papyrus_content.newsletter.send import BATCH_SIZE, Pacer, SendQueue, Sender, start_send
from papyrus_content.newsletter.store import iso, membership_row, profile_key

ADDRESS = "1 Example Street, Example City"
DAY = 24 * 60 * 60
LISTS = (
    {
        "id": "weekly", "name": "Weekly roundup", "description": "", "kind": "roundup",
        "issueType": "newsletter_issue", "archivePath": "/roundup/", "timezone": "America/New_York",
    },
    {"id": "alerts-a", "name": "Alerts A", "description": "", "kind": "alert"},
)
ADMIN = {"username": "admin-user", "sub": "sub-admin", "groups": ["admin"], "email": "admin@example.com"}
EDITOR = {"username": "editor-user", "sub": "sub-editor", "groups": ["editor"], "email": "editor@example.com"}
NOBODY = {"username": "reader-user", "groups": []}


class FakeContent:
    """The slice of the GraphQL authoring client the newsletter uses: Items and published summaries."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.published: list[dict[str, Any]] = []
        self.published_items: dict[str, dict[str, Any]] = {}

    def get_record(self, model: str, record_id: str) -> dict[str, Any] | None:
        if model == "PublishedItem":
            return self.published_items.get(record_id)
        assert model == "Item"
        return self.items.get(record_id)

    def upsert(self, model: str, payload: dict[str, Any]) -> str:
        assert model == "Item"
        existed = payload["id"] in self.items
        self.items[payload["id"]] = dict(payload)
        return "updated" if existed else "created"

    def list_published_item_summaries(self) -> list[dict[str, Any]]:
        return list(self.published)

    def publish(self, *, slug: str, title: str, section: str | None, at: float, type: str = "article", dek: str | None = None) -> None:
        front = f"title: {json.dumps(title)}\n" + (f"description: {json.dumps(dek)}\n" if dek else "")
        self.published.append(
            {
                "id": f"published-{slug}", "type": type, "status": "published", "slug": slug, "section": section, "title": title,
                "publishedAt": iso(at), "metadata": json.dumps({"frontMatterYaml": front}),
            }
        )


class FakeScheduler:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, float]] = []
        self.deleted: list[str] = []

    def upsert(self, name: str, issue_id: str, send_at: float) -> None:
        self.created.append((name, issue_id, send_at))

    def delete(self, name: str) -> None:
        self.deleted.append(name)


class FakeQueue:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []
        self.singles: list[list[str]] = []

    def send_batches(self, issue_id: str, batches: list[list[str]]) -> None:
        self.batches += batches

    def send(self, issue_id: str, hids: list[str]) -> None:
        self.singles.append(hids)


class FakePostal:
    def __init__(self, value: str | None = ADDRESS) -> None:
        self.value = value

    def resolve(self) -> str | None:
        return self.value


class Rig:
    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.now = START
        self.ses = harness.ses
        self.content = FakeContent()
        self.scheduler = FakeScheduler()
        self.queue = FakeQueue()
        self.postal = FakePostal()
        self.published_items: list[str] = []
        self.sleeps: list[float] = []
        self.ticks = 0.0
        self.settings = Settings(
            site_id="example", site_origin="https://news.example.com", sending_domain="example.com",
            from_address="newsletter@example.com", from_name="Example News", configuration_set="papyrus-example",
            lists=LISTS, theme=THEME,
        )
        self.compliance = Compliance(store=harness.store, keys=harness.keys, site_origin=self.settings.site_origin)
        self.service = IssueService(
            settings=self.settings, store=harness.store,
            mailer=Mailer(from_name="Example News", from_address="newsletter@example.com", configuration_set="papyrus-example", site_id="example", client=self.ses),
            compliance=self.compliance, postal=self.postal, scheduler=self.scheduler, queue=self.queue,
            content=lambda: self.content, publisher=self._publish, clock=lambda: self.now,
        )
        self.api = Newsletter(
            self.settings, harness.store, harness.keys, self.service.mailer, clock=lambda: self.now, issues=self.service
        )
        self.sender = Sender(self.service, pacer=Pacer(_Account(), monotonic=self._monotonic, sleep=self._pace), sleep=self.sleeps.append)

    def _publish(self, item_id: str) -> dict[str, Any]:
        self.published_items.append(item_id)
        return {"ok": True, "url": f"https://news.example.com/roundup/{item_id}.html"}

    def _monotonic(self) -> float:
        return self.ticks

    def _pace(self, seconds: float) -> None:
        self.ticks += seconds
        self.paced.append(seconds)

    paced: list[float]

    def call(self, action: str, identity: dict[str, Any] | None, **input: Any) -> dict[str, Any]:
        event: dict[str, Any] = {"action": action, "input": json.dumps(input), "identity": identity or {}}
        return self.api.dispatch(event)["body"]

    def task(self, task: str, **fields: Any) -> dict[str, Any]:
        return self.api.dispatch({"task": task, **fields})["body"]

    def add_member(self, email: str, *, status: str = "confirmed", membership: str = "subscribed", list_id: str = "weekly") -> str:
        hid = addresses.hid(self.harness.keys.hash, email)
        profile = {**profile_key(hid), "email": email, "status": status, "createdAt": iso(self.now), "updatedAt": iso(self.now), "history": []}
        self.harness.store.save(profile, None, [membership_row(hid, list_id, membership, self.now, profile_confirmed=status == "confirmed")])
        return hid

    def suppress(self, hid: str) -> None:
        self.harness.store.client.put_item(
            TableName="newsletter", Item={"pk": {"S": f"SUPP#{hid}"}, "sk": {"S": "SUPP"}, "reason": {"S": "bounce"}}
        )

    def draft(self) -> dict[str, Any]:
        self.content.publish(slug="a-story", title="A story", section="security", at=self.now - DAY)
        created = self.task("assemble-roundup", listId="weekly")
        assert created["status"] == "created", created
        return created

    def approve(self, issue_id: str, send_at: float | None = None) -> dict[str, Any]:
        when = iso(send_at if send_at is not None else self.now + 3600)
        return self.call("issue_approve", ADMIN, issueId=issue_id, sendAt=when)

    def issue(self, issue_id: str) -> dict[str, Any]:
        issue = self.service.issues.get(issue_id)
        assert issue is not None
        return issue

    def counts(self, issue_id: str) -> dict[str, int]:
        return self.issue(issue_id)["counts"]

    def fire(self, issue_id: str) -> dict[str, Any]:
        return self.task("start-send", issueId=issue_id)

    def drain(self, remaining_ms: Any = None) -> list[dict[str, Any]]:
        """Run every queued message through the worker, as the queue would."""
        results = []
        queued, self.queue.batches = self.queue.batches, []
        issue_id = self.last_issue
        for batch in queued:
            body = {"issueId": issue_id, "hids": batch}
            results.append(self.sender.process(body, remaining_ms) if remaining_ms else self.sender.process(body))
        return results

    last_issue = ""


class _Account:
    def __init__(self, rate: float = 14.0) -> None:
        self.rate = rate
        self.calls = 0

    def get_account(self) -> dict[str, Any]:
        self.calls += 1
        return {"SendQuota": {"MaxSendRate": self.rate}}


@contextmanager
def rig_context() -> Iterator[Rig]:
    with running_harness() as harness:
        rig = Rig(harness)
        rig.paced = []
        yield rig


@pytest.fixture
def rig() -> Iterator[Rig]:
    with rig_context() as value:
        yield value


def scheduled_issue(rig: Rig, members: int = 3) -> str:
    created = rig.draft()
    rig.last_issue = created["issueId"]
    for index in range(members):
        rig.add_member(f"reader{index}@example.com")
    assert rig.approve(created["issueId"])["ok"]
    return created["issueId"]


# -- assembly ----------------------------------------------------------------------------------------------------------


def test_assembly_groups_items_by_section_with_links_and_deks(rig: Rig) -> None:
    rig.content.publish(slug="patch-now", title="Patch *now*", section="security", at=START - DAY, dek="Fix it today.")
    rig.content.publish(slug="new-tool", title="A new tool", section="tools", at=START - 2 * DAY)
    rig.content.publish(slug="about-us", title="About us", section=None, at=START - 3 * DAY)
    rig.content.publish(slug="too-old", title="Too old", section="tools", at=START - 8 * DAY)
    rig.content.publish(slug="old-issue", title="An earlier issue", section="roundup", at=START - DAY, type="newsletter_issue")
    created = rig.task("assemble-roundup", listId="weekly")
    assert created["status"] == "created" and created["items"] == 3
    item = rig.content.items[created["itemId"]]
    assert item["type"] == "newsletter_issue" and item["section"] == "roundup" and item["status"] == "draft"
    assert item["title"] == "Weekly roundup: Jan 8 to Jan 15, 2027"
    body = item["bodyMarkus"]
    assert body.startswith("Write a short introduction")
    assert body.index("## Security") < body.index("## Tools") < body.index("## More")
    assert "- [Patch \\*now\\*](https://news.example.com/security/patch-now.html): Fix it today." in body
    assert "[A new tool](https://news.example.com/tools/new-tool.html)" in body
    assert "[About us](https://news.example.com/about-us.html)" in body
    assert "Too old" not in body and "earlier issue" not in body
    issue = rig.issue(created["issueId"])
    assert (issue["status"], issue["kind"], issue["listId"], issue["itemId"]) == ("draft", "roundup", "weekly", created["itemId"])
    assert issue["subject"] == item["title"] and issue["counts"]["queued"] == 0


def test_window_starts_at_the_last_sent_issue(rig: Rig) -> None:
    rig.content.publish(slug="before", title="Before", section="tools", at=START - 4 * DAY)
    rig.content.publish(slug="after", title="After", section="tools", at=START - 2 * DAY)
    previous = rig.service.issues
    from papyrus_content.newsletter.issues import new_issue_row

    row = new_issue_row("a" * 16, list_id="weekly", kind="roundup", subject="Earlier", now=START - 5 * DAY)
    row.update(status="sent", sentAt=iso(START - 3 * DAY))
    assert previous.create(row)
    created = rig.task("assemble-roundup", listId="weekly")
    body = rig.content.items[created["itemId"]]["bodyMarkus"]
    assert "[After]" in body and "Before" not in body


def test_one_draft_per_list_and_iso_week(rig: Rig) -> None:
    rig.content.publish(slug="story", title="Story", section="tools", at=START - DAY)
    first = rig.task("assemble-roundup", listId="weekly")
    again = rig.task("assemble-roundup", listId="weekly")
    assert first["status"] == "created" and again["status"] == "exists"
    assert len(rig.service.issues.list_all()) == 1
    rig.now += 7 * DAY
    rig.content.publish(slug="next", title="Next", section="tools", at=rig.now - DAY)
    assert rig.task("assemble-roundup", listId="weekly")["status"] == "created"
    assert len(rig.service.issues.list_all()) == 2


def test_a_crash_between_the_period_claim_and_the_issue_row_is_finished_on_retry(rig: Rig) -> None:
    from papyrus_content.newsletter import roundup

    rig.content.publish(slug="story", title="Story", section="tools", at=START - DAY)
    original = rig.service.issues.create
    rig.service.issues.create = lambda row: (_ for _ in ()).throw(RuntimeError("crash"))  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        roundup.assemble(rig.service, LISTS[0], manual=False, actor="t")
    rig.service.issues.create = original  # type: ignore[assignment]
    assert rig.task("assemble-roundup", listId="weekly")["status"] == "created"
    assert len(rig.service.issues.list_all()) == 1


def test_an_empty_week_makes_no_draft_and_no_claim(rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    assert rig.task("assemble-roundup", listId="weekly")["status"] == "empty"
    assert rig.service.issues.list_all() == [] and rig.content.items == {}
    assert "roundup_empty" in capsys.readouterr().out
    rig.content.publish(slug="late", title="Late", section="tools", at=rig.now - DAY)
    assert rig.task("assemble-roundup", listId="weekly")["status"] == "created"


def test_unknown_list_and_alert_lists_make_no_scheduled_draft(rig: Rig) -> None:
    assert rig.task("assemble-roundup", listId="alerts-a")["ok"] is False
    assert rig.task("assemble-roundup", listId="nope")["ok"] is False


def test_manual_draft_is_allowed_empty_and_never_overwrites(rig: Rig) -> None:
    first = rig.call("issue_create_draft", EDITOR, listId="weekly")
    second = rig.call("issue_create_draft", EDITOR, listId="weekly")
    assert first["ok"] and second["ok"] and first["itemId"] != second["itemId"]
    assert rig.call("issue_create_draft", NOBODY, listId="weekly")["error"] == "forbidden"
    assert rig.call("issue_create_draft", EDITOR, listId="alerts-a")["error"] == "bad_request"


# -- approval ----------------------------------------------------------------------------------------------------------


def test_approval_stores_the_hash_and_schedules_the_send(rig: Rig) -> None:
    created = rig.draft()
    issue_id = created["issueId"]
    result = rig.approve(issue_id, START + 3600)
    assert result["ok"] and result["adjusted"] is False and result["warnings"] == []
    issue = rig.issue(issue_id)
    item = rig.content.items[created["itemId"]]
    assert issue["status"] == "scheduled"
    assert issue["contentHash"] == content_hash(item["title"], item["bodyMarkus"])
    assert (issue["approvedBy"], issue["sendAt"]) == ("admin-user", iso(START + 3600))
    assert rig.scheduler.created == [(schedule_name("example", issue_id), issue_id, START + 3600)]
    assert issue["scheduleName"] == f"papyrus-nl-example-{issue_id[:8]}"


def test_schedule_parameters_are_one_time_utc_and_deleted_after(rig: Rig) -> None:
    from papyrus_content.newsletter.scheduler import IssueScheduler

    class Client:
        class exceptions:  # noqa: N801
            ConflictException = type("ConflictException", (Exception,), {})
            ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

        def __init__(self) -> None:
            self.created: list[dict[str, Any]] = []
            self.updated: list[dict[str, Any]] = []
            self.conflict = False

        def create_schedule(self, **parameters: Any) -> None:
            if self.conflict:
                raise self.exceptions.ConflictException()
            self.created.append(parameters)

        def update_schedule(self, **parameters: Any) -> None:
            self.updated.append(parameters)

    client = Client()
    scheduler = IssueScheduler(function_arn="arn:aws:lambda:us-east-1:123456789012:function:f", role_arn="arn:aws:iam::123456789012:role/r", client=client)
    scheduler.upsert("papyrus-nl-example-0123abcd", "0123abcd" + "0" * 8, 1_800_003_600)
    parameters = client.created[0]
    assert parameters["ScheduleExpression"] == "at(2027-01-15T09:00:00)"
    assert parameters["ScheduleExpressionTimezone"] == "UTC"
    assert parameters["FlexibleTimeWindow"] == {"Mode": "OFF"} and parameters["ActionAfterCompletion"] == "DELETE"
    assert json.loads(parameters["Target"]["Input"]) == {"task": "start-send", "issueId": "0123abcd" + "0" * 8}
    assert parameters["Target"]["RoleArn"].endswith(":role/r")
    client.conflict = True
    scheduler.upsert("papyrus-nl-example-0123abcd", "0123abcd" + "0" * 8, 1_800_007_200)
    assert client.updated[0]["ScheduleExpression"] == "at(2027-01-15T10:00:00)"


def test_a_send_time_in_the_past_or_under_two_minutes_away_becomes_now_plus_two_minutes() -> None:
    assert effective_send_time(START - 10, START) == (START + 120, True)
    assert effective_send_time(START + 60, START) == (START + 120, True)
    assert effective_send_time(None, START) == (START + 120, True)
    assert effective_send_time(START + 120, START) == (START + 120, False)
    assert at_expression(START) == "at(2027-01-15T08:00:00)"


def test_approving_with_a_past_time_is_moved_forward(rig: Rig) -> None:
    created = rig.draft()
    result = rig.call("issue_approve", ADMIN, issueId=created["issueId"], sendAt=iso(START - 3600))
    assert result["adjusted"] is True and rig.issue(created["issueId"])["sendAt"] == iso(START + 120)


def test_only_admins_approve_cancel_or_stop(rig: Rig) -> None:
    created = rig.draft()
    issue_id = created["issueId"]
    for identity in (EDITOR, NOBODY, None):
        for action in ("issue_approve", "issue_cancel", "issue_stop"):
            assert rig.call(action, identity, issueId=issue_id, sendAt=iso(START + 3600))["error"] == "forbidden"
    assert rig.issue(issue_id)["status"] == "draft" and rig.scheduler.created == []
    rig.approve(issue_id)
    assert rig.call("issue_cancel", EDITOR, issueId=issue_id)["error"] == "forbidden"
    assert rig.issue(issue_id)["status"] == "scheduled"


def test_reapproving_updates_the_same_schedule_and_cancel_returns_to_draft(rig: Rig) -> None:
    created = rig.draft()
    issue_id = created["issueId"]
    rig.approve(issue_id, START + 3600)
    rig.approve(issue_id, START + 7200)
    assert [entry[0] for entry in rig.scheduler.created] == [schedule_name("example", issue_id)] * 2
    assert rig.issue(issue_id)["sendAt"] == iso(START + 7200)
    cancelled = rig.call("issue_cancel", ADMIN, issueId=issue_id)
    assert cancelled["ok"] and rig.scheduler.deleted == [schedule_name("example", issue_id)]
    issue = rig.issue(issue_id)
    assert issue["status"] == "draft" and "contentHash" not in issue and "sendAt" not in issue
    assert rig.call("issue_cancel", ADMIN, issueId=issue_id)["error"] == "invalid_state"


def test_approval_refuses_a_missing_item_and_a_sent_issue(rig: Rig) -> None:
    created = rig.draft()
    del rig.content.items[created["itemId"]]
    assert rig.approve(created["issueId"])["error"] == "item_missing"
    assert rig.call("issue_approve", ADMIN, issueId="zzzz", sendAt=iso(START))["error"] == "not_found"
    assert rig.call("issue_approve", ADMIN, issueId="not valid!")["error"] == "not_found"


def test_approval_warns_when_the_postal_address_is_missing(rig: Rig) -> None:
    created = rig.draft()
    rig.postal.value = None
    result = rig.approve(created["issueId"])
    assert result["ok"] and result["warnings"] and rig.issue(created["issueId"])["status"] == "scheduled"


# -- reads -------------------------------------------------------------------------------------------------------------


def test_list_get_and_preview(rig: Rig) -> None:
    created = rig.draft()
    issue_id = created["issueId"]
    listed = rig.call("issue_list", EDITOR)
    assert [row["issueId"] for row in listed["issues"]] == [issue_id] and listed["issues"][0]["listName"] == "Weekly roundup"
    assert rig.call("issue_list", NOBODY)["error"] == "forbidden"
    assert rig.call("issue_list", EDITOR, status="sent")["issues"] == []
    rig.approve(issue_id)
    detail = rig.call("issue_get", EDITOR, issueId=issue_id)["issue"]
    assert detail["status"] == "scheduled" and detail["editedSinceApproval"] is False
    rig.content.items[created["itemId"]]["bodyMarkus"] += "\nMore.\n"
    assert rig.call("issue_get", EDITOR, issueId=issue_id)["issue"]["editedSinceApproval"] is True
    preview = rig.call("issue_preview", EDITOR, issueId=issue_id)
    assert preview["ok"] and "<html" in preview["html"] and ADDRESS in preview["text"] and preview["postalAddress"] is True
    assert "More." in preview["text"] and "links.newsletter.invalid" not in preview["html"]
    assert rig.call("issue_preview", NOBODY, issueId=issue_id)["error"] == "forbidden"


# -- start-send --------------------------------------------------------------------------------------------------------


def test_nothing_sends_without_approval(rig: Rig) -> None:
    created = rig.draft()
    rig.add_member("reader@example.com")
    assert rig.fire(created["issueId"])["status"] == "ignored"
    assert rig.queue.batches == [] and rig.ses.sent == []
    assert rig.issue(created["issueId"])["status"] == "draft"


def test_an_issue_edited_after_approval_goes_back_to_draft_and_sends_nothing(rig: Rig) -> None:
    issue_id = scheduled_issue(rig)
    item_id = rig.issue(issue_id)["itemId"]
    rig.content.items[item_id]["bodyMarkus"] += "\nA late change.\n"
    result = rig.fire(issue_id)
    assert result["status"] == "draft" and result["note"] == EDITED_NOTE
    issue = rig.issue(issue_id)
    assert issue["status"] == "draft" and issue["note"] == EDITED_NOTE and "contentHash" not in issue
    assert rig.queue.batches == [] and rig.ses.sent == []


def test_a_changed_title_counts_as_an_edit(rig: Rig) -> None:
    issue_id = scheduled_issue(rig)
    rig.content.items[rig.issue(issue_id)["itemId"]]["title"] = "A different subject"
    assert rig.fire(issue_id)["status"] == "draft"


def test_a_missing_postal_address_blocks_the_send(rig: Rig) -> None:
    issue_id = scheduled_issue(rig)
    rig.postal.value = None
    assert rig.fire(issue_id)["status"] == "blocked"
    issue = rig.issue(issue_id)
    assert issue["status"] == "blocked" and issue["note"] == "postal address missing" and rig.queue.batches == []


def test_a_blocked_issue_is_approved_again_once_the_cause_is_fixed(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 2)
    rig.postal.value = None
    assert rig.fire(issue_id)["status"] == "blocked"
    rig.postal.value = ADDRESS
    assert rig.approve(issue_id, rig.now + 3600)["ok"] and rig.issue(issue_id)["status"] == "scheduled"
    rig.now += 3600
    assert rig.fire(issue_id)["status"] == "sending"
    rig.drain()
    assert len(rig.ses.sent) == 2 and rig.issue(issue_id)["status"] == "sent"


def test_a_paused_site_blocks_the_send(rig: Rig) -> None:
    issue_id = scheduled_issue(rig)
    rig.harness.store.client.put_item(
        TableName="newsletter", Item={"pk": {"S": "STATE"}, "sk": {"S": "SITE"}, "paused": {"BOOL": True}}
    )
    assert rig.fire(issue_id)["status"] == "blocked"
    assert rig.issue(issue_id)["note"] == "site paused" and rig.queue.batches == []


def test_start_send_queues_batches_of_fifty_and_counts_queued(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, members=BATCH_SIZE * 2 + 5)
    rig.add_member("pending@example.com", status="pending", membership="pending")
    result = rig.fire(issue_id)
    assert result == {"ok": True, "status": "sending", "queued": BATCH_SIZE * 2 + 5}
    assert sorted(len(batch) for batch in rig.queue.batches) == [5, 50, 50]
    issue = rig.issue(issue_id)
    assert issue["status"] == "sending" and issue["counts"]["queued"] == 105 and issue["enqueuedAt"]
    render = rig.service.issues.get_render(issue_id)
    assert render is not None and ADDRESS in render["text"] and MANAGE_PLACEHOLDER in render["html"]
    assert rig.fire(issue_id)["status"] == "ignored", "a second firing does nothing"


def test_a_list_with_no_subscribers_completes_at_once_and_archives(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, members=0)
    rig.fire(issue_id)
    issue = rig.issue(issue_id)
    assert issue["status"] == "sent" and rig.published_items == [issue["itemId"]]
    assert issue["archiveUrl"].startswith("https://news.example.com/roundup/")


# -- the worker --------------------------------------------------------------------------------------------------------


def run_to_the_end(rig: Rig, members: int = 3) -> str:
    issue_id = scheduled_issue(rig, members)
    assert rig.fire(issue_id)["status"] == "sending"
    rig.drain()
    return issue_id


def test_each_subscriber_gets_one_mail_with_unsubscribe_headers_and_tags(rig: Rig) -> None:
    issue_id = run_to_the_end(rig)
    assert len(rig.ses.sent) == 3
    for message in rig.ses.sent:
        simple = message["Content"]["Simple"]
        headers = {entry["Name"]: entry["Value"] for entry in simple["Headers"]}
        assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
        link = headers["List-Unsubscribe"]
        assert link.startswith("<https://news.example.com/api/newsletter/unsubscribe?t=") and link.endswith(">")
        assert link[1:-1] in simple["Body"]["Html"]["Data"] and link[1:-1] in simple["Body"]["Text"]["Data"]
        assert "newsletter.invalid" not in simple["Body"]["Html"]["Data"]
        assert ADDRESS in simple["Body"]["Text"]["Data"]
        assert "You get this because you subscribed to Weekly roundup on Example News." in simple["Body"]["Text"]["Data"]
        tags = {tag["Name"]: tag["Value"] for tag in message["EmailTags"]}
        assert tags["site"] == "example" and tags["list"] == "weekly" and tags["issue"] == issue_id and len(tags["sub"]) == 32
        assert message["ConfigurationSetName"] == "papyrus-example"
        assert message["Destination"]["ToAddresses"][0].endswith("@example.com")
    assert len({message["Destination"]["ToAddresses"][0] for message in rig.ses.sent}) == 3
    counts = rig.counts(issue_id)
    assert (counts["sent"], counts["queued"]) == (3, 3) and rig.issue(issue_id)["status"] == "sent"
    rows = rig.ledger(issue_id)
    assert len(rows) == 3 and all(row["status"] == "sent" and row["messageId"] and row["gsiHid"] == row["sk"].removeprefix("SEND#") for row in rows)
    assert "example.com" not in json.dumps(rows), "the ledger holds no address"


def test_a_retried_batch_never_mails_anyone_twice(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 4)
    rig.fire(issue_id)
    batch = list(rig.queue.batches[0])
    first = rig.sender.process({"issueId": issue_id, "hids": batch})
    assert first["sent"] == 4 and len(rig.ses.sent) == 4
    again = rig.sender.process({"issueId": issue_id, "hids": batch})
    assert len(rig.ses.sent) == 4, "the second delivery of the same message sent nothing"
    assert again["dropped"] == "sent"
    assert rig.counts(issue_id)["sent"] == 4


def test_a_retry_after_a_partial_run_finishes_only_the_rest(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 4)
    rig.fire(issue_id)
    batch = list(rig.queue.batches[0])
    rig.sender.process({"issueId": issue_id, "hids": batch[:2]})
    assert len(rig.ses.sent) == 2
    # the failed run is delivered again with the whole batch: the two done are not mailed again
    rig.service.issues.update(issue_id, expect="sent", sets={"status": "sending"})  # the partial run had not completed it
    rig.sender.process({"issueId": issue_id, "hids": batch})
    assert len(rig.ses.sent) == 4 and len({m["Destination"]["ToAddresses"][0] for m in rig.ses.sent}) == 4
    assert rig.counts(issue_id)["sent"] == 4


def test_a_claim_left_by_a_dead_worker_is_never_mailed_and_counts_as_failed(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 2)
    rig.fire(issue_id)
    hid = rig.queue.batches[0][0]
    assert rig.service.issues.claim(issue_id, hid, START)
    rig.drain()
    assert len(rig.ses.sent) == 1
    counts = rig.counts(issue_id)
    assert (counts["sent"], counts["failed"]) == (1, 1) and rig.issue(issue_id)["status"] == "sent"
    assert rig.service.issues.get_send(issue_id, hid)["error"] == "interrupted"  # type: ignore[index]


def test_a_stopped_issue_drops_its_remaining_messages(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 3)
    rig.fire(issue_id)
    assert rig.call("issue_stop", ADMIN, issueId=issue_id)["ok"]
    results = rig.drain()
    assert results == [{"dropped": "stopped"}] and rig.ses.sent == []
    issue = rig.issue(issue_id)
    assert issue["status"] == "stopped" and issue["counts"]["sent"] == 0 and rig.published_items == []


def test_stopping_part_way_stops_the_rest_of_the_message(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 25)
    rig.fire(issue_id)
    original = rig.ses.send_email
    count = {"n": 0}

    def stop_after_ten(**kwargs: Any) -> dict[str, str]:
        count["n"] += 1
        if count["n"] == 10:
            rig.service.issues.update(issue_id, {"status": "stopped"}, expect="sending")
        return original(**kwargs)

    rig.ses.send_email = stop_after_ten  # type: ignore[method-assign]
    result = rig.sender.process({"issueId": issue_id, "hids": rig.queue.batches[0]})
    assert result["dropped"] == "stopped" and len(rig.ses.sent) == 10
    assert rig.issue(issue_id)["status"] == "stopped"


def test_suppressed_and_unsubscribed_addresses_are_counted_not_mailed(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 2)
    bounced = rig.add_member("bounced@example.com")
    rig.suppress(bounced)
    left = rig.add_member("left@example.com", membership="unsubscribed")
    pending = rig.add_member("pending@example.com", status="pending", membership="pending")
    rig.fire(issue_id)
    assert rig.counts(issue_id)["queued"] == 3, "the suppressed address is still on the index; the others never were"
    # a stale index can still hand the worker an address that has since left: queue those two by hand
    stale = [left, pending]
    rig.service.issues.update(issue_id, expect="sending", add_counts={"queued": 2})
    rig.drain()
    assert rig.issue(issue_id)["status"] == "sending"
    rig.sender.process({"issueId": issue_id, "hids": stale})
    counts = rig.counts(issue_id)
    assert (counts["suppressed"], counts["skipped"], counts["sent"]) == (1, 2, 2)
    assert len(rig.ses.sent) == 2 and bounced not in str(rig.ses.sent)
    assert rig.issue(issue_id)["status"] == "sent"
    again = rig.sender.process({"issueId": issue_id, "hids": stale + [bounced]})
    assert again == {"dropped": "sent"} and rig.counts(issue_id)["suppressed"] == 1


def test_a_repeated_skip_is_not_counted_twice(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 1)
    rig.fire(issue_id)
    left = rig.add_member("left@example.com", membership="unsubscribed")
    rig.service.issues.update(issue_id, expect="sending", add_counts={"queued": 1})
    for _ in range(2):
        rig.sender.process({"issueId": issue_id, "hids": [left]})
    assert rig.counts(issue_id)["skipped"] == 1


def test_completion_happens_once_and_archives_the_issue_once(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, BATCH_SIZE + 10)
    rig.fire(issue_id)
    first, second = rig.queue.batches
    rig.sender.process({"issueId": issue_id, "hids": first})
    assert rig.issue(issue_id)["status"] == "sending" and rig.published_items == []
    rig.sender.process({"issueId": issue_id, "hids": second})
    rig.sender.process({"issueId": issue_id, "hids": second})
    issue = rig.issue(issue_id)
    assert issue["status"] == "sent" and issue["sentAt"] and rig.published_items == [issue["itemId"]]
    assert issue["archiveUrl"]
    assert rig.counts(issue_id)["sent"] == BATCH_SIZE + 10


def test_a_failed_archive_publish_keeps_the_issue_sent_and_leaves_a_note(rig: Rig) -> None:
    def refuse(_item_id: str) -> dict[str, Any]:
        raise RuntimeError("down")

    rig.service.publisher = refuse
    issue_id = run_to_the_end(rig, 1)
    issue = rig.issue(issue_id)
    assert issue["status"] == "sent" and "archive publish failed" in issue["note"]


def test_ses_errors_are_recorded_on_the_ledger_and_counted(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 2)
    rig.fire(issue_id)
    original = rig.ses.send_email
    calls = {"n": 0}

    def fail_first(**kwargs: Any) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ClientError({"Error": {"Code": "MessageRejected", "Message": "no"}}, "SendEmail")
        return original(**kwargs)

    rig.ses.send_email = fail_first  # type: ignore[method-assign]
    rig.drain()
    counts = rig.counts(issue_id)
    assert (counts["sent"], counts["failed"]) == (1, 1) and rig.issue(issue_id)["status"] == "sent"
    failed = [row for row in rig.ledger(issue_id) if row["status"] == "failed"]
    assert failed[0]["error"] == "MessageRejected" and "example.com" not in json.dumps(failed)


def test_throttling_sleeps_and_retries_within_the_message(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 1)
    rig.fire(issue_id)
    original = rig.ses.send_email
    calls = {"n": 0}

    def throttle_twice(**kwargs: Any) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "SendEmail")
        return original(**kwargs)

    rig.ses.send_email = throttle_twice  # type: ignore[method-assign]
    rig.drain()
    assert rig.sleeps == [1.0, 2.0] and rig.counts(issue_id)["sent"] == 1 and calls["n"] == 3


def test_sends_are_paced_under_the_account_send_rate(rig: Rig) -> None:
    rig.sender.pacer.ses_client = _Account(rate=2.0)
    issue_id = scheduled_issue(rig, 5)
    rig.fire(issue_id)
    rig.drain()
    assert len(rig.ses.sent) == 5
    assert rig.paced == [0.5] * 4, "four pauses of half a second between five sends at two a second"
    assert rig.sender.pacer.ses_client.calls == 1, "the rate is read once and cached"


def test_a_message_that_runs_short_of_time_requeues_the_rest(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 4)
    rig.fire(issue_id)
    batch = rig.queue.batches[0]
    remaining = iter([200_000, 200_000, 1_000, 1_000])
    result = rig.sender.process({"issueId": issue_id, "hids": batch}, lambda: next(remaining))
    assert result["sent"] == 2 and result["requeued"] == 2 and rig.queue.singles == [batch[2:]]
    assert rig.issue(issue_id)["status"] == "sending"


def test_the_worker_does_not_send_for_a_paused_site(rig: Rig) -> None:
    issue_id = scheduled_issue(rig, 2)
    rig.fire(issue_id)
    rig.harness.store.client.put_item(
        TableName="newsletter", Item={"pk": {"S": "STATE"}, "sk": {"S": "SITE"}, "paused": {"BOOL": True}}
    )
    assert rig.drain() == [{"dropped": "paused"}] and rig.ses.sent == []
    assert rig.issue(issue_id)["status"] == "stopped"


def test_malformed_messages_are_dropped(rig: Rig) -> None:
    assert rig.sender.process({"hids": []}) == {"dropped": "malformed"}
    assert rig.sender.process({"issueId": "nothere", "hids": ["x"]}) == {"dropped": "missing"}


# -- test send ---------------------------------------------------------------------------------------------------------


def test_test_send_goes_only_to_the_signed_in_editor(rig: Rig) -> None:
    created = rig.draft()
    rig.add_member("reader@example.com")
    result = rig.call("issue_test_send", EDITOR, issueId=created["issueId"], to="reader@example.com", email="other@example.com")
    assert result["ok"]
    assert len(rig.ses.sent) == 1
    message = rig.ses.sent[0]
    assert message["Destination"]["ToAddresses"] == ["editor@example.com"]
    simple = message["Content"]["Simple"]
    assert simple["Subject"]["Data"].startswith("[Test] Weekly roundup")
    assert "Headers" not in simple
    tags = {tag["Name"]: tag["Value"] for tag in message["EmailTags"]}
    assert "sub" not in tags and "issue" not in tags and tags["kind"] == "test"
    assert 'href="#test"' in simple["Body"]["Html"]["Data"] and ADDRESS in simple["Body"]["Text"]["Data"]
    assert rig.ledger(created["issueId"]) == [] and rig.issue(created["issueId"])["status"] == "draft"


def test_test_send_needs_a_role_an_address_and_a_postal_address(rig: Rig) -> None:
    created = rig.draft()
    issue_id = created["issueId"]
    assert rig.call("issue_test_send", NOBODY, issueId=issue_id)["error"] == "forbidden"
    assert rig.call("issue_test_send", {**EDITOR, "email": None}, issueId=issue_id)["error"] == "no_address"
    rig.postal.value = None
    assert rig.call("issue_test_send", EDITOR, issueId=issue_id)["error"] == "postal_address_missing"
    assert rig.ses.sent == []


# -- plumbing ----------------------------------------------------------------------------------------------------------


def _ledger(self: Rig, issue_id: str) -> list[dict[str, Any]]:
    response = self.harness.store.client.query(
        TableName="newsletter",
        KeyConditionExpression="pk = :p AND begins_with(sk, :s)",
        ExpressionAttributeValues={":p": {"S": f"ISSUE#{issue_id}"}, ":s": {"S": "SEND#"}},
    )
    from papyrus_content.newsletter.store import _de

    return [_de(item) for item in response["Items"]]


Rig.ledger = _ledger  # type: ignore[attr-defined]


class FakeLambda:
    def __init__(self, response: dict[str, Any], error: bool = False) -> None:
        self.response, self.error, self.calls = response, error, []

    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        import io

        return {"Payload": io.BytesIO(json.dumps(self.response).encode()), **({"FunctionError": "Unhandled"} if self.error else {})}


def test_the_appsync_proxy_forwards_the_claims_and_returns_the_body() -> None:
    client = FakeLambda({"statusCode": 200, "body": {"ok": True, "issues": []}})
    event = {
        "fieldName": "newsletterIssues",
        "arguments": {"input": "{\"listId\":\"weekly\"}"},
        "identity": {"username": "u", "sub": "s", "groups": ["admin"], "claims": {"email": "admin@example.com", "other": "x"}},
    }
    assert ops_proxy.handle(event, client=client, environment={"NEWSLETTER_FUNCTION_NAME": "fn"}) == {"ok": True, "issues": []}
    sent = json.loads(client.calls[0]["Payload"])
    assert sent == {
        "action": "issue_list", "input": "{\"listId\":\"weekly\"}",
        "identity": {"username": "u", "sub": "s", "groups": ["admin"], "email": "admin@example.com"},
    }
    assert client.calls[0]["FunctionName"] == "fn"
    assert ops_proxy.handle({"fieldName": "other"}, client=client, environment={}) == {"ok": False, "error": "unknown_operation"}
    assert ops_proxy.handle(event, client=FakeLambda({}, error=True), environment={"NEWSLETTER_FUNCTION_NAME": "fn"})["error"] == "unavailable"
    assert set(ops_proxy.FIELD_ACTIONS.values()) == {
        "issue_list", "issue_get", "issue_approve", "issue_cancel", "issue_stop", "issue_test_send", "issue_create_draft", "issue_preview",
        "panel_overview", "panel_subscribers", "panel_export", "panel_erase", "panel_resume", "panel_deliveries",
    }


def test_postal_address_prefers_the_site_override_and_caches_for_five_minutes() -> None:
    class Ssm:
        class exceptions:  # noqa: N801
            ParameterNotFound = type("ParameterNotFound", (Exception,), {})

        def __init__(self, values: dict[str, str]) -> None:
            self.values, self.asked = values, []

        def get_parameter(self, Name: str) -> dict[str, Any]:  # noqa: N803
            self.asked.append(Name)
            if Name not in self.values:
                raise self.exceptions.ParameterNotFound()
            return {"Parameter": {"Value": self.values[Name]}}

    now = {"t": 0.0}
    both = Ssm({"/papyrus/example/email/postal-address": "Override Address", "/papyrus/email/postal-address": "Shared Address"})
    postal = PostalAddress("example", both, clock=lambda: now["t"])
    assert postal.resolve() == "Override Address" and both.asked == ["/papyrus/example/email/postal-address"]
    postal.resolve()
    assert len(both.asked) == 1
    now["t"] = 301.0
    postal.resolve()
    assert len(both.asked) == 2
    shared = PostalAddress("example", Ssm({"/papyrus/email/postal-address": "Shared Address"}))
    assert shared.resolve() == "Shared Address"
    blank = PostalAddress("example", Ssm({"/papyrus/example/email/postal-address": "  ", "/papyrus/email/postal-address": "\n"}))
    assert blank.resolve() is None
    assert PostalAddress("example", Ssm({})).resolve() is None


def test_the_installed_ses_client_can_send_custom_headers() -> None:
    import botocore.session

    shape = botocore.session.get_session().get_service_model("sesv2").shape_for("Message")
    assert "Headers" in shape.members, "bundle a newer boto3: this one cannot set List-Unsubscribe"


def test_unsupported_actions_stay_unknown(rig: Rig) -> None:
    assert rig.api.dispatch({"action": "nope"})["statusCode"] == 400


def test_the_send_queue_batches_ten_entries_and_reports_refusals() -> None:
    class Sqs:
        def __init__(self, failed: bool = False) -> None:
            self.calls, self.failed = [], failed

        def send_message_batch(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            return {"Failed": [{"Id": "0"}]} if self.failed else {}

    client = Sqs()
    SendQueue("https://sqs.example/q", client).send_batches("i" * 16, [["a" * 32]] * 25)
    assert [len(call["Entries"]) for call in client.calls] == [10, 10, 5]
    assert json.loads(client.calls[0]["Entries"][0]["MessageBody"]) == {"issueId": "i" * 16, "hids": ["a" * 32]}
    with pytest.raises(RuntimeError):
        SendQueue("https://sqs.example/q", Sqs(failed=True)).send_batches("i" * 16, [["a" * 32]])
