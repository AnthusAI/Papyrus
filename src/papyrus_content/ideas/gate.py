"""The editorial gate of the idea pipeline: the site's own policy pack, the same composition ``papyrus editorial check`` uses (PPY-373fdb)."""

from __future__ import annotations

from typing import Any

from ..editorial_checks import EditorialChecksDisabled, GraphQLEditorialStore, Services, check_editorial, check_run_record


class HumanusGate:
    """Checks an idea's text against the publication's policies. The rules lane always runs; the judgment lane needs ``TYPESAFE_API_KEY`` and,
    when it is missing, Humanus reports the lane as unavailable, which the Item records (``generated.check.judgment``) instead of passing silently."""

    def __init__(self, services: Services) -> None:
        self.services = services

    @classmethod
    def for_site(cls) -> "HumanusGate":
        return cls(Services(store=GraphQLEditorialStore()))

    def check(self, body: str, section: str | None) -> dict[str, Any]:
        try:
            return check_editorial({"body": body, "format": "markus", "section": section}, self.services)
        except EditorialChecksDisabled:
            return {"skipped": "disabled"}

    def record(self, item: dict[str, Any], result: dict[str, Any]) -> None:
        record = check_run_record(item, result, self.services.now())
        if self.services.last_check_request:
            record["packVersion"] = self.services.last_check_request["pack"].get("version")
        self.services.store.put_check_run(record)
