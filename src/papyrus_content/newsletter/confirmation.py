"""The confirmation email: transactional mail with one button, built by ``email_render.render_transactional``."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from papyrus_content.email_render import RenderedEmail, render_transactional, theme_from_config

from . import links
from .tokens import CONFIRM_TOKEN_LIFETIME_SECONDS

BUTTON_LABEL = "Confirm subscription"
_MARKUS_SPECIAL = re.compile(r"([\\`*_\[\]<>#|~])")


def markus_text(value: str) -> str:
    """Config text as literal Markus text: one line, special characters escaped."""
    return _MARKUS_SPECIAL.sub(r"\\\1", " ".join(value.split()))


def confirm_url(site_origin: str, token: str, base_path: str = "") -> str:
    """The clean page the button opens (``<origin><base>/newsletter/confirm/?token=...``); it posts to the machine endpoint itself."""
    return links.page_url(site_origin, base_path, "confirm", f"token={token}")


def build_confirmation(
    *,
    site_origin: str,
    base_path: str = "",
    site_name: str,
    theme_config: Mapping[str, Any],
    lists: Sequence[Mapping[str, str]],
    token: str,
) -> RenderedEmail:
    hours = CONFIRM_TOKEN_LIFETIME_SECONDS // 3600
    lines = [f"Please confirm that you want to get email from {markus_text(site_name)}.", ""]
    for entry in lists:
        description = markus_text(entry.get("description", ""))
        lines.append(f"- **{markus_text(entry['name'])}**" + (f": {description}" if description else ""))
    lines += [
        "",
        f"This link works for {hours} hours. Nothing is sent to you until you confirm.",
        "If you did not ask for this, ignore this email and you will not hear from us again.",
    ]
    return render_transactional(
        subject=f"Confirm your subscription to {site_name}",
        markus="\n".join(lines),
        theme=theme_from_config(theme_config, site_name),
        site_name=site_name,
        site_url=links.home_url(site_origin, base_path),
        preheader=f"Confirm to start receiving email from {site_name}.",
        action_url=confirm_url(site_origin, token, base_path),
        action_label=BUTTON_LABEL,
    )
