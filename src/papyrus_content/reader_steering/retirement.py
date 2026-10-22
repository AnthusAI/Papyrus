"""The Prospectus retired-subject poll: a typed interface and a disabled implementation.

Prospectus will tell sites which siteSubjects were retired (a person deleted their account). The route is not
final; it will look like ``GET /v1/site-subjects/retired?since=<cursor>``. Until it exists the snapshot run
calls :class:`DisabledRetirementPoll`, which retires nothing, and the plugin setting ``retirementPoll`` stays false.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RetiredSubjects:
    site_subjects: tuple[str, ...] = ()
    cursor: str | None = None


class RetirementPoll(Protocol):
    def fetch(self, since: str | None) -> RetiredSubjects: ...


class DisabledRetirementPoll:
    enabled = False

    def fetch(self, since: str | None) -> RetiredSubjects:
        return RetiredSubjects(cursor=since)
