"""The site's themed renderer, passed to Caducus's email channel in place of its plain operator template."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from caducus.notify.channels.email import Renderer
from caducus.notify.render.operator import RenderedEmail

from papyrus_content.email_render import render_transactional, theme_from_config
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
    def __init__(self, settings: Settings):
        self._settings = settings
        self._theme = theme_from_config(settings.theme, settings.from_name)
        #: Set by the channel for public-class mail, which must carry the sender's postal address.
        self.postal_address: str | None = None

    def render(self, items: Sequence[Mapping[str, Any]]) -> RenderedEmail:
        first = items[0]
        subject = first.get("what") or "New story" if len(items) == 1 else f"{len(items)} new stories on {self._settings.from_name}"
        base = f"/{self._settings.base_path}" if self._settings.base_path else ""
        rendered = render_transactional(
            subject=subject,
            markus="\n".join(story_block(item) for item in items),
            theme=self._theme,
            site_name=self._settings.from_name,
            site_url=self._settings.site_origin.rstrip("/") + base + "/",
            preheader=first.get("reason") or "",
            reason=f"You received this because you are on the notification list for {self._settings.from_name}.",
            postal_address=self.postal_address,
        )
        return RenderedEmail(subject=rendered.subject, text=rendered.text, html=rendered.html)
