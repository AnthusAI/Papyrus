"""Starting a send (``start-send``) and the paced worker that mails it.

``start_send`` re-validates an approved issue, renders it once, and queues the subscribers in messages of up to 50.
``Sender.process`` handles one queue message: for each address it claims a ledger row *before* calling SES, so a retried
message never mails anyone twice.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Mapping

from papyrus_content.email_render import PostalAddressMissing

from .compose import MAXIMUM_RENDER_BYTES, ItemMissing, content_hash, load_source, personalise, render
from .issues import EDITED_NOTE, IssueService, IssueStore, log
from .store import Store, iso

BATCH_SIZE = 50
QUEUE_BATCH_LIMIT = 10  # SQS SendMessageBatch
HID = re.compile(r"[0-9a-f]{32}")
MINIMUM_RATE = 1.0
RATE_CACHE_SECONDS = 5 * 60
THROTTLE_CODES = frozenset({"Throttling", "ThrottlingException", "TooManyRequestsException", "Throttled", "RequestLimitExceeded"})
THROTTLE_PAUSES = (1.0, 2.0, 4.0)
#: Stop starting new addresses when this little time is left; the rest of the message goes back to the queue.
SAFETY_MARGIN_MS = 75_000


class SendQueue:
    def __init__(self, queue_url: str, client: Any = None) -> None:
        self.queue_url = queue_url
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("sqs")
        return self._client

    def send(self, issue_id: str, hids: list[str]) -> None:
        self.client.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps({"issueId": issue_id, "hids": hids}))

    def send_batches(self, issue_id: str, batches: list[list[str]]) -> None:
        for offset in range(0, len(batches), QUEUE_BATCH_LIMIT):
            entries = [
                {"Id": str(offset + index), "MessageBody": json.dumps({"issueId": issue_id, "hids": hids})}
                for index, hids in enumerate(batches[offset : offset + QUEUE_BATCH_LIMIT])
            ]
            response = self.client.send_message_batch(QueueUrl=self.queue_url, Entries=entries)
            if response.get("Failed"):
                raise RuntimeError(f"{len(response['Failed'])} queue messages were refused")


def _block(service: IssueService, issue_id: str, status: str, note: str, expect: str) -> dict[str, Any]:
    service.issues.update(issue_id, {"status": status, "note": note}, expect=expect)
    log("send_" + status, issue_id, note=note)
    return {"status": status, "note": note}


def start_send(service: IssueService, issue_id: str) -> dict[str, Any]:
    """The ``start-send`` task. Guards, in order: scheduled, unchanged since approval, postal address, site not paused."""
    issues = service.issues
    issue = issues.get(issue_id)
    if issue is None:
        return {"status": "missing"}
    resuming = issue.get("status") == "sending" and not issue.get("enqueuedAt")
    if issue.get("status") != "scheduled" and not resuming:
        return {"status": "ignored", "was": issue.get("status")}
    entry = service.settings.list_named(issue.get("listId", ""))
    if entry is None:
        return _block(service, issue_id, "blocked", "list is no longer configured", issue["status"])
    if not resuming:
        try:
            source = load_source(service.content, issue)
        except ItemMissing:
            return _block(service, issue_id, "blocked", "item is missing", "scheduled")
        if content_hash(source.subject, source.markus) != issue.get("contentHash"):
            issues.update(
                issue_id, {"status": "draft", "note": EDITED_NOTE}, expect="scheduled",
                remove=("contentHash", "approvedBy", "approvedAt", "sendAt", "scheduleName"),
            )
            log("send_edited", issue_id)
            return {"status": "draft", "note": EDITED_NOTE}
        address = service.postal.resolve()
        if not address:
            return _block(service, issue_id, "blocked", "postal address missing", "scheduled")
        if service.compliance.is_paused():
            return _block(service, issue_id, "blocked", "site paused", "scheduled")
        try:
            rendered = render(service.settings, entry["name"], source, address)
        except PostalAddressMissing:
            return _block(service, issue_id, "blocked", "postal address missing", "scheduled")
        except Exception as error:  # noqa: BLE001
            return _block(service, issue_id, "blocked", f"render failed: {type(error).__name__}", "scheduled")
        if len((rendered.html + rendered.text).encode("utf-8")) > MAXIMUM_RENDER_BYTES:
            return _block(service, issue_id, "blocked", "issue is too large to send", "scheduled")
        issues.put_render(issue_id, rendered.subject, rendered.html, rendered.text)
    hids = issues.list_members(entry["id"])
    if not resuming:
        began = issues.update(
            issue_id, {"status": "sending", "startedAt": iso(service.clock())}, expect="scheduled", add_counts={"queued": len(hids)}
        )
        if not began:
            return {"status": "ignored", "was": "changed"}
    else:
        counts = issue.get("counts") or {}
        issues.update(issue_id, expect="sending", add_counts={"queued": len(hids) - int(counts.get("queued", 0))})
    service.queue.send_batches(issue_id, [hids[offset : offset + BATCH_SIZE] for offset in range(0, len(hids), BATCH_SIZE)])
    issues.update(issue_id, {"enqueuedAt": iso(service.clock())}, expect="sending")
    log("send_started", issue_id, recipients=len(hids))
    finish_if_complete(service, issue_id)
    return {"status": "sending", "queued": len(hids)}


def finish_if_complete(service: IssueService, issue_id: str) -> bool:
    """When every queued address is accounted for, mark the issue sent (one caller wins) and archive a roundup."""
    if not service.issues.finish_if_complete(issue_id, service.clock()):
        return False
    log("send_completed", issue_id)
    issue = service.issues.get(issue_id) or {}
    if issue.get("kind") == "roundup" and issue.get("itemId"):
        try:
            result = service.publisher(issue["itemId"])
            url = result.get("url") if isinstance(result, Mapping) else None
            service.issues.update(issue_id, {"archiveUrl": url} if url else {"note": "archived; the page address is not known yet"})
        except Exception as error:  # noqa: BLE001 - the mail is out; publishing the archive page can be done from the newsroom
            service.issues.update(issue_id, {"note": f"archive publish failed: {type(error).__name__}; publish the item from the newsroom"})
            log("archive_failed", issue_id, error=type(error).__name__)
    return True


class Pacer:
    """Keeps sends under SES's MaxSendRate (from ``sesv2 get_account``, cached for five minutes)."""

    def __init__(self, ses_client: Any, *, monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.ses_client = ses_client
        self.monotonic = monotonic
        self.sleep = sleep
        self._rate: tuple[float, float] | None = None
        self._last: float | None = None

    def rate(self) -> float:
        now = self.monotonic()
        if self._rate is None or now - self._rate[0] > RATE_CACHE_SECONDS:
            try:
                value = float(self.ses_client.get_account()["SendQuota"]["MaxSendRate"])
            except Exception:  # noqa: BLE001 - unknown: assume the sandbox rate
                value = MINIMUM_RATE
            self._rate = (now, max(value, MINIMUM_RATE))
        return self._rate[1]

    def wait(self) -> None:
        interval = 1.0 / self.rate()
        if self._last is not None:
            pause = self._last + interval - self.monotonic()
            if pause > 0:
                self.sleep(pause)
        self._last = self.monotonic()


class Sender:
    """The worker's logic for one queue message."""

    def __init__(
        self,
        service: IssueService,
        *,
        pacer: Pacer,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.service = service
        self.pacer = pacer
        self.sleep = sleep

    def process(self, body: Mapping[str, Any], remaining_ms: Callable[[], int] = lambda: 10**9) -> dict[str, Any]:
        service, issues = self.service, self.service.issues
        issue_id = body.get("issueId")
        hids = [hid for hid in body.get("hids", []) if isinstance(hid, str) and HID.fullmatch(hid)] if isinstance(body.get("hids"), list) else []
        if not isinstance(issue_id, str) or not issue_id.isalnum():
            return {"dropped": "malformed"}
        issue = issues.get(issue_id)
        if issue is None or issue.get("status") != "sending":
            return {"dropped": (issue or {}).get("status", "missing")}
        if service.compliance.is_paused():
            _block(service, issue_id, "stopped", "site paused", "sending")
            return {"dropped": "paused"}
        rendered = issues.get_render(issue_id)
        if rendered is None:
            raise RuntimeError(f"issue {issue_id} has no rendered mail")  # retried, then the dead letter queue
        entry = service.settings.list_named(issue.get("listId", "")) or {}
        outcome = {"sent": 0, "failed": 0, "suppressed": 0, "skipped": 0, "handled": 0}
        for position, hid in enumerate(hids):
            if remaining_ms() < SAFETY_MARGIN_MS:
                service.queue.send(issue_id, hids[position:])
                outcome["requeued"] = len(hids) - position
                break
            if position % 10 == 0 and position:
                current = issues.get(issue_id)
                if current is None or current.get("status") != "sending":
                    outcome["dropped"] = (current or {}).get("status", "missing")
                    break
            outcome[self._one(issue_id, hid, issue.get("listId", ""), entry, rendered)] += 1
        finish_if_complete(service, issue_id)
        return outcome

    def _one(self, issue_id: str, hid: str, list_id: str, entry: Mapping[str, Any], rendered: Mapping[str, Any]) -> str:
        service, issues = self.service, self.service.issues
        now = service.clock()
        if service.compliance.is_suppressed(hid):
            return "suppressed" if issues.settle_unsent(issue_id, hid, "suppressed", now) else "handled"
        profile = service.profile(hid)
        if profile is None or profile.get("status") != "confirmed" or issues.membership_status(hid, list_id) != "subscribed":
            return "skipped" if issues.settle_unsent(issue_id, hid, "skipped", now) else "handled"
        if not issues.claim(issue_id, hid, now):
            # Handled before. A row still ``claimed`` means a worker died between the claim and the answer from SES:
            # never mail it again, and count it as failed so the issue can finish.
            issues.record_outcome(issue_id, hid, "failed", now, error="interrupted")
            return "handled"
        urls = service.compliance.manage_urls(hid, list_id)
        html, text = personalise(rendered["html"], rendered["text"], manage_url=urls["manage_url"], unsubscribe_url=urls["unsubscribe_url"])
        return self._deliver(issue_id, hid, list_id, profile["email"], rendered["subject"], html, text, urls["one_click_url"])

    def _deliver(self, issue_id: str, hid: str, list_id: str, address: str, subject: str, html: str, text: str, one_click_url: str) -> str:
        service, issues = self.service, self.service.issues
        headers = {"List-Unsubscribe": f"<{one_click_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
        tags = {"site": service.settings.site_id, "list": list_id, "issue": issue_id, "sub": hid}
        error = "unknown"
        for attempt in range(len(THROTTLE_PAUSES) + 1):
            self.pacer.wait()
            try:
                message_id = service.mailer.send_issue(to=address, subject=subject, html=html, text=text, headers=headers, tags=tags)
            except Exception as problem:  # noqa: BLE001 - the ledger records the code, never the address
                error = _error_code(problem)
                if error in THROTTLE_CODES and attempt < len(THROTTLE_PAUSES):
                    self.sleep(THROTTLE_PAUSES[attempt])
                    continue
                issues.record_outcome(issue_id, hid, "failed", service.clock(), error=error)
                return "failed"
            issues.record_outcome(issue_id, hid, "sent", service.clock(), message_id=message_id)
            return "sent"
        return "failed"  # pragma: no cover - the loop always returns


def _error_code(problem: Exception) -> str:
    response = getattr(problem, "response", None)
    code = (response or {}).get("Error", {}).get("Code") if isinstance(response, dict) else None
    return str(code or type(problem).__name__)[:100]
