"""The sender's postal address for the compliance footer, read from SSM at send time (never stored in a repo).

A per-site override ``/papyrus/<siteId>/email/postal-address`` wins over the shared default ``/papyrus/email/postal-address``.
A missing or blank value means marketing sends are refused. The value is cached for five minutes and never logged.
"""

from __future__ import annotations

import time
from typing import Any, Callable

CACHE_SECONDS = 5 * 60
SHARED_PARAMETER = "/papyrus/email/postal-address"


def site_parameter(site_id: str) -> str:
    return f"/papyrus/{site_id}/email/postal-address"


def parameter_names(site_id: str) -> tuple[str, str]:
    """Most specific first. These are the only two names the functions may read."""
    return site_parameter(site_id), SHARED_PARAMETER


class PostalAddress:
    def __init__(self, site_id: str, client: Any = None, *, clock: Callable[[], float] = time.time) -> None:
        self.site_id = site_id
        self._client = client
        self.clock = clock
        self._cached: tuple[float, str | None] | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("ssm")
        return self._client

    def resolve(self) -> str | None:
        """The address, or ``None`` when neither parameter holds one."""
        now = self.clock()
        if self._cached is not None and now - self._cached[0] < CACHE_SECONDS:
            return self._cached[1]
        value = self._read()
        self._cached = (now, value)
        return value

    def _read(self) -> str | None:
        for name in parameter_names(self.site_id):
            try:
                value = self.client.get_parameter(Name=name)["Parameter"]["Value"]
            except self.client.exceptions.ParameterNotFound:
                continue
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
