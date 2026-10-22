"""Pure-Python email renderer: Markus source -> responsive inline-styled HTML plus plain text."""

from .render import (
    EmailFooter,
    PostalAddressMissing,
    RenderedEmail,
    render_issue,
    render_transactional,
)
from .theme import EmailTheme, theme_from_config

__all__ = [
    "EmailFooter",
    "EmailTheme",
    "PostalAddressMissing",
    "RenderedEmail",
    "render_issue",
    "render_transactional",
    "theme_from_config",
]
