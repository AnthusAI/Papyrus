"""The notifications plugin's reader pages, projected as real static pages (docs/notifications.md).

People land on these URLs from email and from the plugin's form; ``/api/notifications/*`` is only for machines (form POST targets, the
RFC 8058 one-click POST, JSON state). Each page is static text plus a container; ``_plugins/papyrus-notifications-pages@1.js`` reads the
``token``, ``list``, ``lists``, ``msg`` and ``step`` query parameters, fills the hidden fields of the forms and fetches names and state
from ``/api/notifications/state``. The subscribe page (``/notifications/``) places the ``<papyrus-notifications>`` web component
(``_plugins/papyrus-notifications@1.js``). The pages always use the directory form (``notifications/confirm/index.html``) whatever
``urls.style`` says, because the emails link to those exact URLs. Icons are Lucide (ISC licence), drawn in ``currentColor``; every state is
also said in words.
"""

from __future__ import annotations

from html import escape

from .head import PageHead

NOTIFICATIONS_PLUGIN = "notifications"
PAGES_SCRIPT_PATH = "_plugins/papyrus-notifications-pages@1.js"
COMPONENT_SCRIPT_PATH = "_plugins/papyrus-notifications@1.js"
#: ``index`` is the subscribe page at ``/notifications/``; the others are ``/notifications/<name>/``.
PAGE_NAMES = ("index", "confirm", "confirmed", "preferences", "unsubscribe", "unsubscribed", "expired")
REFERRER_META = '<meta name="referrer" content="same-origin">'
NO_SCRIPT = "This page needs JavaScript. Turn it on and reload the page."


def site_key(name: str) -> str:
    """The site-relative object key of a page: ``notifications/confirm/index.html``."""
    return "notifications/index.html" if name == "index" else f"notifications/{name}/index.html"


def site_path(name: str) -> str:
    return "/notifications/" if name == "index" else f"/notifications/{name}/"


_HEADINGS = {
    "index": "Get notifications",
    "confirm": "Confirm your subscription",
    "confirmed": "You are subscribed",
    "preferences": "Your notifications",
    "unsubscribe": "Unsubscribe",
    "unsubscribed": "You are unsubscribed",
    "expired": "This link did not work",
}


def scripts(name: str) -> tuple[str, ...]:
    """The scripts a page loads: the pages script everywhere, and the web component only where it is placed."""
    return (PAGES_SCRIPT_PATH, COMPONENT_SCRIPT_PATH) if name == "index" else (PAGES_SCRIPT_PATH,)


def head(name: str, path: str, description: str) -> PageHead:
    """Noindex, with a ``same-origin`` referrer policy so the form posts carry the site's real Origin and Referer. The chrome adds the site name to the title."""
    return PageHead(title=_HEADINGS[name], path=path, description=description, noindex=True, extra=REFERRER_META)


def _icon(name: str, body: str) -> str:
    return (
        '<svg class="markus-notifications-icon" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" '
        f'data-icon="{name}">{body}</svg>'
    )


ICONS = {
    "mail": _icon("mail", '<path d="m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7"/><rect x="2" y="4" width="20" height="16" rx="2"/>'),
    "circle-check": _icon("circle-check", '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>'),
    "bell-off": _icon(
        "bell-off",
        '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M17 17H4a1 1 0 0 1-.74-1.673C4.59 13.956 6 12.499 6 8a6 6 0 0 1 .258-1.742"/>'
        '<path d="m2 2 20 20"/><path d="M8.668 3.01A6 6 0 0 1 18 8c0 2.687.77 4.653 1.707 6.05"/>',
    ),
    "save": _icon(
        "save",
        '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
        '<path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/><path d="M7 3v4a1 1 0 0 0 1 1h7"/>',
    ),
    "trash-2": _icon(
        "trash-2",
        '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>'
        '<line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
    ),
    "triangle-alert": _icon(
        "triangle-alert",
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    ),
    "arrow-left": _icon("arrow-left", '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>'),
}


def _form(action: str, fields: str, body: str, *, state: str = "") -> str:
    return (
        f'<form class="markus-notifications-form" method="post" action="{action}" data-notifications-form="{state}" hidden>'
        f'<input type="hidden" name="t" value="">{fields}{body}</form>'
    )


def _button(label: str, icon: str, *, name: str = "", value: str = "", secondary: bool = False) -> str:
    attrs = (f' name="{name}" value="{value}"' if name else "") + (' data-variant="secondary"' if secondary else "")
    return f'<button type="submit" class="markus-button markus-notifications-button"{attrs}>{ICONS[icon]}<span>{escape(label)}</span></button>'


def fragment(name: str, *, site: str, home: str, paths: dict[str, str]) -> str:
    """The body of one page. ``paths`` maps page names to request paths (the base path included); ``home`` is the site's home path."""
    site_text = escape(site)
    root = (
        f'<div class="markus-document markus-notifications-page" data-notifications-page="{name}" data-site-name="{site_text}" '
        f'data-expired-href="{escape(paths["expired"])}" data-preferences-href="{escape(paths["preferences"])}">'
    )
    noscript = f"<noscript><p>{NO_SCRIPT}</p></noscript>"
    back = f'<p class="markus-notifications-back">{ICONS["arrow-left"]}<a href="{escape(home)}">Back to {site_text}</a></p>'
    heading = f"<h1>{escape(_HEADINGS[name])}</h1>"
    status = '<p class="markus-notifications-status" role="status" data-notifications-unavailable hidden>{}<span>{}</span></p>'.format(
        ICONS["triangle-alert"], "Notifications are not available right now. Please try again later."
    )
    manage = '<p data-notifications-manage hidden><a href="{}">{}</a></p>'
    if name == "index":
        body = (
            f"{heading}<p>Get an email from {site_text} when it publishes something new. You can change what you get, or stop, at any time.</p>"
            f"{noscript}<papyrus-notifications></papyrus-notifications>"
            "<p>Already subscribed? Use the manage link at the bottom of any email we send you.</p>"
            f"{back}"
        )
    elif name == "confirm":
        body = (
            f"{heading}<p>Press the button to start getting email from {site_text}.</p>"
            f'<div data-notifications-lists hidden><p>You are signing up for:</p><ul></ul></div>{noscript}{status}'
            + _form("/api/notifications/confirm", "", f'<p class="markus-actions">{_button("Confirm subscription", "circle-check")}</p>')
        )
    elif name == "confirmed":
        body = (
            f'{heading}<p class="markus-notifications-status" data-notifications-summary>{ICONS["circle-check"]}<span>Thank you. Your subscription is confirmed.</span></p>'
            f'<div data-notifications-lists hidden><p>You will get:</p><ul></ul></div>'
            f'{manage.format(escape(paths["preferences"]), "Manage your notifications")}{back}'
        )
    elif name == "preferences":
        body = (
            f'<p class="markus-notifications-notice" role="status" data-notifications-notice hidden>{ICONS["circle-check"]}<span></span></p>{noscript}{status}'
            f'<div data-notifications-section="manage" hidden>{heading}<p data-notifications-email>Choose what you get.</p>'
            + _form(
                "/api/notifications/preferences",
                "",
                '<div class="markus-notifications-lists" data-notifications-lists></div><p class="markus-actions">'
                + _button("Save", "save", name="action", value="save")
                + _button("Unsubscribe from everything", "bell-off", name="action", value="unsubscribe_all", secondary=True)
                + _button("Delete my data", "trash-2", name="action", value="delete", secondary=True)
                + "</p>",
                state="manage",
            )
            + f"{back}</div>"
            f'<div data-notifications-section="delete" hidden><h1>Delete your data?</h1>'
            f"<p>This erases your address and everything {site_text} holds about your notifications. You will not get any more email. This cannot be undone.</p>"
            + _form(
                "/api/notifications/preferences",
                '<input type="hidden" name="action" value="delete"><input type="hidden" name="confirm" value="1">',
                f'<p class="markus-actions">{_button("Yes, delete my data", "trash-2")}</p>',
                state="delete",
            )
            + f'<p><a data-notifications-back href="{escape(paths["preferences"])}">No, go back</a></p></div>'
            f'<div data-notifications-section="deleted" hidden><h1>Your data is deleted</h1>'
            f"<p>Your address and notifications have been erased. You will not get any more email from us.</p>{back}</div>"
        )
    elif name == "unsubscribe":
        body = (
            f"{heading}<p data-notifications-prompt>Stop getting all email from {site_text}?</p>{noscript}{status}"
            + _form(
                "/api/notifications/unsubscribe",
                '<input type="hidden" name="l" value=""><input type="hidden" name="page" value="1">',
                f'<p class="markus-actions">{_button("Unsubscribe from everything", "bell-off")}</p>',
            )
            + manage.format(escape(paths["preferences"]), "Choose what you get instead")
        )
    elif name == "unsubscribed":
        body = (
            f'{heading}<p class="markus-notifications-status" data-notifications-summary>{ICONS["circle-check"]}<span>You will no longer get this email from {site_text}.</span></p>'
            f'<div data-notifications-lists hidden><p>You will no longer get these from {site_text}:</p><ul></ul></div>'
            f'{manage.format(escape(paths["preferences"]), "Change your mind? Manage your notifications")}{back}'
        )
    else:
        body = (
            f'{heading}<p class="markus-notifications-status">{ICONS["triangle-alert"]}<span>This link has expired, was already used, or is not valid. If you already confirmed, you are all set.</span></p>'
            f'<p>If you did not finish signing up, <a href="{escape(paths["index"])}">sign up again</a> to get a new link. '
            "To change what you get, use the link in a recent email from us.</p>"
            f"<p>If something went wrong on our side, try the link in your email again in a minute.</p>{back}"
        )
    return f"{root}{body}</div>"
