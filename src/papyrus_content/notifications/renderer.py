"""The site's themed renderer, passed to Caducus's email channel in place of its plain operator template."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from caducus.notify.audience import CONFIRMATION_KIND
from caducus.notify.channels.email import RenderContext, Renderer
from caducus.notify.render.operator import RenderedEmail

from papyrus_content.email_render import EmailFooter, render_issue, render_transactional, theme_from_config
from papyrus_content.newsletter.confirmation import markus_text

from .settings import Settings


def story_block(item: Mapping[str, Any]) -> str:
    title, link, blurb = item.get("what") or "Untitled", item.get("link") or "", item.get("reason") or ""
    heading = f"[{markus_text(title)}]({link})" if link else markus_text(title)
    lines = [f"## {heading}", ""]
    if blurb:
        lines += [markus_text(blurb), ""]
    return "\n".join(lines)


class ThemedRenderer(Renderer):
    """Three shapes of mail, all in the site's theme: the subscription confirmation, public mail to readers (with the
    reader's own manage and unsubscribe links and the postal address in the footer), and operator mail."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._theme = theme_from_config(settings.theme, settings.from_name)
        #: Set by the channel for public-class mail, which must carry the sender's postal address.
        self.postal_address: str | None = None

    def _site_url(self) -> str:
        base = f"/{self._settings.base_path}" if self._settings.base_path else ""
        return self._settings.site_origin.rstrip("/") + base + "/"

    def render(self, items: Sequence[Mapping[str, Any]], context: RenderContext | None = None) -> RenderedEmail:
        if context is not None and context.kind == CONFIRMATION_KIND:
            return self._confirmation(items[0])
        first = items[0]
        name = self._settings.from_name
        subject = first.get("what") or "New story" if len(items) == 1 else f"{len(items)} new stories on {name}"
        markus = "\n".join(story_block(item) for item in items)
        if context is not None and context.klass == "public" and context.links:
            rendered = render_issue(
                subject=subject,
                markus=markus,
                theme=self._theme,
                footer=EmailFooter(
                    site_name=name,
                    site_url=self._site_url(),
                    reason=f"You get this because you subscribed to new stories from {name}.",
                    manage_url=context.links["manage"],
                    unsubscribe_url=context.links["unsubscribe"],
                    postal_address=self.postal_address,
                ),
                preheader=first.get("reason") or "",
                site_url=self._site_url(),
            )
        else:
            rendered = render_transactional(
                subject=subject,
                markus=markus,
                theme=self._theme,
                site_name=name,
                site_url=self._site_url(),
                preheader=first.get("reason") or "",
                reason=f"You received this because you are on the notification list for {name}.",
                postal_address=self.postal_address,
            )
        return RenderedEmail(subject=rendered.subject, text=rendered.text, html=rendered.html)

    def _confirmation(self, item: Mapping[str, Any]) -> RenderedEmail:
        name = self._settings.from_name
        facts = item.get("facts") or {}
        lists = [markus_text(entry) for entry in facts.get("lists") or [] if isinstance(entry, str)]
        chosen = f" ({', '.join(lists)})" if lists else ""
        rendered = render_transactional(
            subject=f"Confirm your subscription to {name}",
            markus=f"Someone asked to get email from {markus_text(name)}{chosen} at this address. "
            "Press the button to confirm. Nothing is sent until you do.",
            theme=self._theme,
            site_name=name,
            site_url=self._site_url(),
            preheader="Confirm to start getting these emails.",
            action_url=facts.get("url") or item.get("link") or "",
            action_label="Confirm subscription",
        )
        return RenderedEmail(subject=rendered.subject, text=rendered.text, html=rendered.html)
