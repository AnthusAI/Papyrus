"""The newsletter plugin's human pages, projected as real static pages (docs/newsletter.md).

People land on these URLs from email and from the plugin's forms; ``/api/newsletter/*`` is only for machines (form POST targets, the
RFC 8058 one-click POST, JSON state). Each page is static text plus a container; ``_plugins/papyrus-newsletter-pages@1.js`` reads the
``token``, ``list`` and ``lists`` query parameters, fills the hidden fields of the forms and fetches names and state from
``/api/newsletter/state``. The pages always use the directory form (``newsletter/confirm/index.html``) whatever ``urls.style`` says,
because the emails link to those exact URLs.
"""

from __future__ import annotations

from html import escape

from .head import PageHead

NEWSLETTER_PLUGIN = "newsletter"
PAGES_SCRIPT_PATH = "_plugins/papyrus-newsletter-pages@1.js"
PAGE_NAMES = ("confirm", "confirmed", "preferences", "unsubscribe", "unsubscribed", "expired")
REFERRER_META = '<meta name="referrer" content="same-origin">'
NO_SCRIPT = "This page needs JavaScript. Turn it on and reload the page."


def site_key(name: str) -> str:
    """The site-relative object key of a page: ``newsletter/confirm/index.html``."""
    return f"newsletter/{name}/index.html"


def site_path(name: str) -> str:
    return f"/newsletter/{name}/"


_HEADINGS = {
    "confirm": "Confirm your subscription",
    "confirmed": "You are subscribed",
    "preferences": "Your subscriptions",
    "unsubscribe": "Unsubscribe",
    "unsubscribed": "You are unsubscribed",
    "expired": "This link did not work",
}


def head(name: str, path: str, description: str) -> PageHead:
    """Noindex, with a ``same-origin`` referrer policy so the form posts carry the site's real Origin and Referer. The chrome adds the site name to the title."""
    return PageHead(title=_HEADINGS[name], path=path, description=description, noindex=True, extra=REFERRER_META)


def _form(action: str, fields: str, body: str, *, state: str = "") -> str:
    return (
        f'<form class="markus-newsletter-form" method="post" action="{action}" data-newsletter-form="{state}" hidden>'
        f'<input type="hidden" name="t" value="">{fields}{body}</form>'
    )


def _button(label: str, *, name: str = "", value: str = "", secondary: bool = False) -> str:
    attrs = (f' name="{name}" value="{value}"' if name else "") + (' data-variant="secondary"' if secondary else "")
    return f'<button type="submit" class="markus-button"{attrs}>{escape(label)}</button>'


def fragment(name: str, *, site: str, home: str, paths: dict[str, str]) -> str:
    """The body of one page. ``paths`` maps page names to request paths (the base path included); ``home`` is the site's home path."""
    site_text = escape(site)
    root = (
        f'<div class="markus-document markus-newsletter-page" data-newsletter-page="{name}" data-site-name="{site_text}" data-expired-href="{escape(paths["expired"])}" '
        f'data-preferences-href="{escape(paths["preferences"])}">'
    )
    noscript = f"<noscript><p>{NO_SCRIPT}</p></noscript>"
    back = f'<p><a href="{escape(home)}">Back to {site_text}</a></p>'
    heading = f"<h1>{escape(_HEADINGS[name])}</h1>"
    manage = '<p data-newsletter-manage hidden><a href="{}">{}</a></p>'
    if name == "confirm":
        body = (
            f"{heading}<p>Press the button to start getting email from {site_text}.</p>"
            f'<div data-newsletter-lists hidden><p>You are signing up for:</p><ul></ul></div>{noscript}'
            + _form("/api/newsletter/confirm", "", f'<p class="markus-actions">{_button("Confirm subscription")}</p>')
        )
    elif name == "confirmed":
        body = (
            f'{heading}<p data-newsletter-summary>Thank you. Your subscription is confirmed.</p>'
            f'<div data-newsletter-lists hidden><p>You will get:</p><ul></ul></div>'
            f'{manage.format(escape(paths["preferences"]), "Manage your subscriptions")}{back}'
        )
    elif name == "preferences":
        body = (
            f'<p class="markus-newsletter-notice" role="status" data-newsletter-notice hidden></p>{noscript}'
            f'<div data-newsletter-section="manage" hidden>{heading}<p data-newsletter-email>Tick the lists you want.</p>'
            + _form(
                "/api/newsletter/preferences",
                "",
                '<div data-newsletter-lists></div><p class="markus-actions">'
                + _button("Save preferences", name="action", value="save")
                + _button("Unsubscribe from everything", name="action", value="unsubscribe_all", secondary=True)
                + _button("Delete my data", name="action", value="delete", secondary=True)
                + "</p>",
                state="manage",
            )
            + f"{back}</div>"
            f'<div data-newsletter-section="delete" hidden><h1>Delete your data?</h1>'
            f"<p>This erases your address and everything {site_text} holds about your subscriptions. You will not get any more email. This cannot be undone.</p>"
            + _form(
                "/api/newsletter/preferences",
                '<input type="hidden" name="action" value="delete"><input type="hidden" name="confirm" value="1">',
                f'<p class="markus-actions">{_button("Yes, delete my data")}</p>',
                state="delete",
            )
            + f'<p><a data-newsletter-back href="{escape(paths["preferences"])}">No, go back</a></p></div>'
            f'<div data-newsletter-section="deleted" hidden><h1>Your data is deleted</h1>'
            f"<p>Your address and subscriptions have been erased. You will not get any more email from us.</p>{back}</div>"
        )
    elif name == "unsubscribe":
        body = (
            f"{heading}<p data-newsletter-prompt>Stop getting all email from {site_text}?</p>{noscript}"
            + _form(
                "/api/newsletter/unsubscribe",
                '<input type="hidden" name="l" value=""><input type="hidden" name="page" value="1">',
                f'<p class="markus-actions">{_button("Unsubscribe from everything")}</p>',
            )
            + manage.format(escape(paths["preferences"]), "Choose which lists you get instead")
        )
    elif name == "unsubscribed":
        body = (
            f'{heading}<p data-newsletter-summary>You will no longer get this email from {site_text}.</p>'
            f'<div data-newsletter-lists hidden><p>You will no longer get these from {site_text}:</p><ul></ul></div>'
            f'{manage.format(escape(paths["preferences"]), "Change your mind? Manage your subscriptions")}{back}'
        )
    else:
        body = (
            f"{heading}<p>This link has expired, was already used, or is not valid. If you already confirmed, you are all set.</p>"
            "<p>If you did not finish signing up, go back to the site and sign up again to get a new link. "
            "To change your subscriptions, use the link in a recent email from us.</p>"
            f"<p>If something went wrong on our side, try the link in your email again in a minute.</p>{back}"
        )
    return f"{root}{body}</div>"
