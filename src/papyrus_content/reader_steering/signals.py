"""Spam and quality signals for reader submissions and comments, from Humanus rule checks.

Humanus is stateless and receives a policy pack with every call (docs/editorial-checks.md). Only its deterministic
rules lane runs here, with no model: the built-in ``ai-writing-tells`` pack plus a small spam pack kept in this module.
Signals are advice for the moderation queue. They never hide anything by themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlsplit

SOURCE_HUMANUS = "humanus"
SOURCE_PAPYRUS = "papyrus"
MAXIMUM_SIGNALS = 20
MAXIMUM_EXCERPT = 80
URL_SHORTENERS = frozenset(
    "bit.ly t.co tinyurl.com goo.gl ow.ly is.gd buff.ly rebrand.ly cutt.ly shorturl.at rb.gy tiny.cc lnkd.in".split()
)

SPAM_PACK: dict[str, Any] = {
    "schemaVersion": 1,
    "packId": "reader-spam",
    "version": "1.0.0",
    "title": "Reader spam tells",
    "language": "en",
    "guidance": "Flag promotional pressure and filler that a reader link or comment rarely needs.",
    "policies": [
        {
            "id": "promotion",
            "version": 1,
            "title": "Promotional pressure",
            "severity": "warn",
            "guidance": "Calls to buy, click or sign up now are advertising, not a recommendation.",
            "detectors": [
                {"id": "buy-now", "lane": "rules", "kind": "regex", "pattern": r"\b(?:buy|order|subscribe|sign\s+up)\s+now\b", "ignoreCase": True},
                {"id": "click-here", "lane": "rules", "kind": "regex", "pattern": r"\bclick\s+(?:here|the\s+link)\b", "ignoreCase": True},
                {"id": "limited-offer", "lane": "rules", "kind": "regex", "pattern": r"\b(?:limited\s+time\s+offer|act\s+now|free\s+money|100%\s+free)\b", "ignoreCase": True},
                {"id": "earn-money", "lane": "rules", "kind": "regex", "pattern": r"\b(?:make|earn)\s+\$?\d[\d,]*\s*(?:a|per)\s+(?:day|week|month)\b", "ignoreCase": True},
            ],
        },
        {
            "id": "shouting",
            "version": 1,
            "title": "Shouting",
            "severity": "info",
            "guidance": "Long runs of capitals or exclamation marks read as spam.",
            "detectors": [
                {"id": "capitals", "lane": "rules", "kind": "regex", "pattern": r"\b[A-Z]{4,}(?:\s+[A-Z]{4,}){2,}\b"},
                {"id": "exclamations", "lane": "rules", "kind": "regex", "pattern": r"!{3,}"},
            ],
        },
    ],
}

CheckFunction = Callable[[dict[str, Any]], dict[str, Any]]


def humanus_check(request: dict[str, Any]) -> dict[str, Any]:
    import humanus

    return humanus.check(request)


def builtin_packs() -> list[dict[str, Any]]:
    from humanus.packs import builtin_pack

    return [builtin_pack("ai-writing-tells"), SPAM_PACK]


def humanus_signals(text: str, *, check: CheckFunction | None = None, packs: Iterable[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Rule findings for ``text`` as ``{source, policy, detector, severity, excerpt}``, at most ``MAXIMUM_SIGNALS``."""
    if not text.strip():
        return []
    run = check or humanus_check
    signals: list[dict[str, Any]] = []
    for pack in packs if packs is not None else builtin_packs():
        result = run(
            {
                "schemaVersion": 1,
                "content": {"format": "text", "text": text},
                "pack": pack,
                "options": {"lanes": {"rules": True, "classifier": False}},
            }
        )
        for finding in result.get("findings", []):
            if finding.get("status") != "violation":
                continue
            signals.append(
                {
                    "source": SOURCE_HUMANUS,
                    "policy": finding["policyId"],
                    "detector": finding["detectorId"],
                    "severity": finding.get("severity", "info"),
                    "excerpt": str(finding.get("excerptText") or finding.get("excerpt") or "")[:MAXIMUM_EXCERPT],
                }
            )
    return signals[:MAXIMUM_SIGNALS]


def link_signals(url: str) -> list[dict[str, Any]]:
    host = (urlsplit(url).hostname or "").lower()
    if host in URL_SHORTENERS:
        return [{"source": SOURCE_PAPYRUS, "policy": "link", "detector": "url-shortener", "severity": "warn", "excerpt": host}]
    return []


def submission_signals(title: str, note: str | None, url: str, *, check: CheckFunction | None = None) -> list[dict[str, Any]]:
    text = f"{title}\n\n{note}" if note else title
    return (link_signals(url) + humanus_signals(text, check=check))[:MAXIMUM_SIGNALS]
