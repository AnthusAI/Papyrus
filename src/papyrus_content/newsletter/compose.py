"""Turning an issue's Item into mail: the current Markus body, rendered once with link placeholders per recipient."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from papyrus_content.email_render import EmailFooter, RenderedEmail, render_issue, theme_from_config

from . import links

#: Stand-ins for the two per-recipient links. The issue is rendered once with these and each message substitutes its own.
MANAGE_PLACEHOLDER = "https://links.newsletter.invalid/manage"
UNSUBSCRIBE_PLACEHOLDER = "https://links.newsletter.invalid/unsubscribe"
MAXIMUM_RENDER_BYTES = 300_000  # one DynamoDB item is 400 KB; Gmail clips at 102 KB anyway


class ItemMissing(Exception):
    """The issue's Item is gone."""


@dataclass(frozen=True)
class IssueSource:
    subject: str
    markus: str
    preheader: str


def content_hash(subject: str, markus: str) -> str:
    """The approval fingerprint: sha256 of the subject and the Markus body."""
    return hashlib.sha256(f"{subject}\n\n{markus}".encode("utf-8")).hexdigest()


def one_line(value: str) -> str:
    return " ".join(value.split())


def load_source(content: Any, issue: Mapping[str, Any]) -> IssueSource:
    """The Item's current title, body and deck. Raises ``ItemMissing``.

    An alert issue has no Item: its subject, body and preheader were written onto the issue when the alert was raised.
    """
    if issue.get("kind") == "alert":
        return IssueSource(
            subject=one_line(str(issue.get("subject") or "")),
            markus=str(issue.get("bodyMarkus") or ""),
            preheader=one_line(str(issue.get("preheader") or "")),
        )
    item_id = issue.get("itemId")
    item = content.get_record("Item", item_id) if item_id else None
    if item is None:
        raise ItemMissing(item_id or "")
    subject = one_line(str(item.get("title") or item.get("headline") or issue.get("subject") or ""))
    return IssueSource(subject=subject, markus=str(item.get("bodyMarkus") or ""), preheader=one_line(str(item.get("deck") or "")))


def reason_sentence(list_name: str, site_name: str) -> str:
    return f"You get this because you subscribed to {list_name} on {site_name}."


def render(
    settings: Any,
    list_name: str,
    source: IssueSource,
    postal_address: str,
    *,
    manage_url: str = MANAGE_PLACEHOLDER,
    unsubscribe_url: str = UNSUBSCRIBE_PLACEHOLDER,
    subject_prefix: str = "",
) -> RenderedEmail:
    """Render the issue. Raises ``PostalAddressMissing`` for a blank address."""
    site_url = links.home_url(settings.site_origin, getattr(settings, "base_path", ""))
    footer = EmailFooter(
        site_name=settings.from_name,
        site_url=site_url,
        reason=reason_sentence(list_name, settings.from_name),
        manage_url=manage_url,
        unsubscribe_url=unsubscribe_url,
        postal_address=postal_address,
    )
    return render_issue(
        subject=subject_prefix + source.subject,
        markus=source.markus,
        theme=theme_from_config(settings.theme, settings.from_name),
        footer=footer,
        preheader=source.preheader,
        site_url=site_url,
        list_name=list_name,
    )


def personalise(html: str, text: str, *, manage_url: str, unsubscribe_url: str) -> tuple[str, str]:
    def swap(value: str) -> str:
        return value.replace(MANAGE_PLACEHOLDER, manage_url).replace(UNSUBSCRIBE_PLACEHOLDER, unsubscribe_url)

    return swap(html), swap(text)
