"""The editorial gate of the idea pipeline: the site's own policy pack, the same composition ``papyrus editorial check`` uses (PPY-373fdb)."""

from __future__ import annotations

import os
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

    @classmethod
    def for_client(cls, client: Any, *, judgment_key: Any = None) -> "HumanusGate":
        """A gate that reads the site behind ``client`` (the router, which serves several sites and so cannot use the process's own endpoint).
        ``judgment_key`` is the TypeSafe key for the judgment lane, or None: then the environment is left as it is and, with no
        ``TYPESAFE_API_KEY`` there, Humanus reports the lane unavailable and the Item records why. The rules lane runs either way."""
        if judgment_key:
            os.environ["TYPESAFE_API_KEY"] = judgment_key
        return cls(Services(store=GraphQLEditorialStore(execute=client.graphql)))

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
