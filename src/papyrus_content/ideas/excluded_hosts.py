"""Source hosts a site never wants cited in an AI draft (docs/idea-pipeline.md#excluded-source-hosts).

A site lists hosts such as a competing publication. A host matches itself and every subdomain of it (``ipwatchdog.com`` matches
``www.ipwatchdog.com``, not ``notipwatchdog.com``). The list reaches the draft commands as repeatable ``--exclude-host HOST`` flags.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit


def normalize_host(value: str) -> str:
    """``https://www.Example.com/path`` or ``Example.com.`` becomes ``www.example.com``; an empty string when nothing host-like is left."""
    text = str(value or "").strip().lower()
    if "://" in text:
        text = urlsplit(text).hostname or ""
    text = text.split("/")[0].split("@")[-1].split(":")[0].strip(".")
    return text


def normalize_hosts(values: Iterable[str] | str | None) -> tuple[str, ...]:
    """The distinct, normalised hosts of a list, or of one comma-separated string, in order."""
    if values is None:
        return ()
    parts = values.split(",") if isinstance(values, str) else [piece for value in values for piece in str(value).split(",")]
    return tuple(dict.fromkeys(host for host in (normalize_host(part) for part in parts) if host))


def host_of(url: str | None) -> str:
    """The host of an address, or an empty string when it has none (a site path such as ``/stories/x``)."""
    try:
        return (urlsplit(str(url or "").strip()).hostname or "").lower().strip(".")
    except ValueError:
        return ""


def is_excluded(url: str | None, hosts: Iterable[str]) -> bool:
    """True when the host of ``url`` is one of ``hosts`` or a subdomain of one."""
    host = host_of(url)
    return bool(host) and any(host == excluded or host.endswith("." + excluded) for excluded in hosts)
