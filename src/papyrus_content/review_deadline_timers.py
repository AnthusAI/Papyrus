"""A soft review's deadline as a follow-up timer (PPY-9b8e59, slice C3 of docs/design/always-on-agents-architecture.md).

An open soft review with a deadline carries ``dueAt`` (its deadline); nothing else does. ``review_requests`` calls ``sync`` wherever it writes ``dueAt``: raising sets the
timer, an answer or a withdrawal clears it. The timer fires once at the deadline, puts a wake for the ``review-deadline`` owner on the site's wake queue and deletes
itself; the run reads the request again (``review_requests.on_deadline_wake``) and times it out ("proceeded without review") only if it still waits for exactly that
time. A flag and a hard gate never have a deadline, so they never have an entry. This is the same shape as a Delivery's due time (``announcements/delivery_timers.py``).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .follow_up_timers import FollowUpTimers, follow_up_request

OWNER = "review-deadline"
RECORD_KIND = "ReviewRequest"
WAITING_FOR = "deadline"
#: The procedure a deadline wake starts. It is the engine's, not an agent's: it does one conditional write on the request named in its input.
PROCEDURE_KEY = "review_deadline"


class ReviewDeadlineTimerError(ValueError):
    """The site's follow-up timers cannot be built from what this process was given."""


class ReviewDeadlineTimers:
    """``base`` is the runner request every start carries (procedure, publication, policy location), as for any follow-up; the request's id and the deadline it waits for
    are added as the input, which is what the ``review_deadline`` procedure reads. The runner starts that procedure with no adopted agent (``engine_follow_ups``)."""

    def __init__(self, timers: FollowUpTimers, base: Mapping[str, Any] | Callable[[Mapping[str, Any]], Mapping[str, Any]]):
        self.timers, self._base = timers, base

    @classmethod
    def from_environment(cls, environment: Mapping[str, str], *, appsync_endpoint: str, client: Any = None) -> ReviewDeadlineTimers:
        """The timers of the site this process works for, named as the site's functions name them: ``PAPYRUS_AGENT_PUBLICATION_ID``, ``PAPYRUS_AWS_ACCOUNT_ID`` and
        ``AWS_REGION`` are required (``PAPYRUS_AWS_PARTITION``, ``PAPYRUS_TENANT_ID`` and ``PAPYRUS_SITE_BUCKET`` are carried when set)."""
        def value(name: str) -> str:
            return str(environment.get(name) or "").strip()

        missing = [name for name in ("PAPYRUS_AGENT_PUBLICATION_ID", "PAPYRUS_AWS_ACCOUNT_ID", "AWS_REGION") if not value(name)]
        if missing:
            raise ReviewDeadlineTimerError(f"a soft review with a deadline sets a follow-up timer on the site's schedule group, which needs {', '.join(missing)}")
        publication = value("PAPYRUS_AGENT_PUBLICATION_ID")
        timers = FollowUpTimers.for_site(publication, account=value("PAPYRUS_AWS_ACCOUNT_ID"), region=value("AWS_REGION"),
                                         partition=value("PAPYRUS_AWS_PARTITION") or "aws", client=client)
        base: dict[str, Any] = {"publicationId": publication, "appsyncEndpoint": appsync_endpoint, "procedureKey": PROCEDURE_KEY,
                                "actorLabel": "Papyrus review deadline"}
        for name, variable in (("tenantId", "PAPYRUS_TENANT_ID"), ("siteBucket", "PAPYRUS_SITE_BUCKET")):
            if value(variable):
                base[name] = value(variable)
        return cls(timers, base)

    def _base_request(self, row: Mapping[str, Any]) -> dict[str, Any]:
        request = dict(self._base(row) if callable(self._base) else self._base)
        request["input"] = {**(request.get("input") if isinstance(request.get("input"), dict) else {}), "reviewRequestId": row["id"],
                            **({"dueAt": row["dueAt"]} if row.get("dueAt") else {})}
        return request

    def sync(self, row: Mapping[str, Any]) -> str | None:
        """Make the request's entry agree with its ``dueAt``: set (or move) it when there is one, delete it when there is none. Returns the wake key or None."""
        due = row.get("dueAt")
        return self.timers.sync(RECORD_KIND, row["id"], due, owner=OWNER, base=self._base_request(row), waiting_for=WAITING_FOR if due else None)

    def wake_request(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """The runner request this request's timer sends for its deadline, with the same wake key. Overdue recovery sends it again (overdue.py)."""
        return follow_up_request(self._base_request(row), owner=OWNER, record_id=row["id"], due_at=row["dueAt"], waiting_for=WAITING_FOR)
