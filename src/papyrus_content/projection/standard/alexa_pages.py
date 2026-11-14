"""The alexa plugin's two public pages: the privacy policy and the terms of use the Alexa Skills Store listing links to.

They are real static pages with the site's normal chrome, projected only for a site that enables the plugin. The URLs are the
directory form (``alexa/privacy/index.html``) whatever ``urls.style`` says, because the skill manifest links to those exact addresses.
The publication name always comes from the site's identity; the contact address comes from ``footer.family.contactUrl`` when the
site sets one and is otherwise the Contact link in the site's footer. Nothing here is a person's address.
"""

from __future__ import annotations

from html import escape

from .head import PageHead

ALEXA_PLUGIN = "alexa"
PAGE_NAMES = ("privacy", "terms")
_TITLES = {"privacy": "Privacy policy for the Alexa skill", "terms": "Terms of use for the Alexa skill"}


def site_key(name: str) -> str:
    """The site-relative object key of a page: ``alexa/privacy/index.html``."""
    return f"alexa/{name}/index.html"


def site_path(name: str) -> str:
    return f"/alexa/{name}/"


def head(name: str, path: str, description: str) -> PageHead:
    """The chrome adds the site name to the title. Both pages are public and indexable: Amazon and reviewers read them."""
    return PageHead(title=_TITLES[name], path=path, description=description)


def _contact(site: str, contact_url: str) -> str:
    if contact_url:
        return f'<p>Questions about this policy: use the <a href="{escape(contact_url)}">contact page for {escape(site)}</a>.</p>'
    return f"<p>Questions about this policy: use the Contact link in the footer of any page on {escape(site)}.</p>"


def fragment(name: str, *, site: str, home: str, paths: dict[str, str], contact_url: str = "") -> str:
    """The body of one page. ``paths`` maps page names to request paths (the base path included); ``home`` is the site's home path."""
    site_text = escape(site)
    root = f'<div class="markus-document markus-alexa-page" data-alexa-page="{name}">'
    other = "terms" if name == "privacy" else "privacy"
    other_label = "Terms of use for the Alexa skill" if name == "privacy" else "Privacy policy for the Alexa skill"
    footer = f'<p><a href="{escape(paths[other])}">{other_label}</a> · <a href="{escape(home)}">Back to {site_text}</a></p>'
    heading = f"<h1>{escape(_TITLES[name])}</h1>"
    if name == "privacy":
        body = (
            f"{heading}<p>This page describes what the {site_text} Alexa skill receives and keeps. It covers the skill only; "
            f"the rest of {site_text} is covered by that site's own pages.</p>"
            "<h2>What the skill receives</h2>"
            "<p>With each request, Amazon sends the skill an anonymous Alexa user ID and information about the device. "
            "The skill does not receive your voice recording. Amazon handles your voice under its own terms.</p>"
            "<h2>If you link your account</h2>"
            f"<p>Linking is optional. If you link an account, you sign in with Google, and the skill receives an access token that identifies "
            f"your {site_text} account. We use it only to show you your feed and to record your votes. "
            f"Votes made through the skill are stored the same way as votes made on the website. Without linking, the skill reads published stories only.</p>"
            "<h2>How to unlink</h2>"
            "<p>Open the Alexa app, find the skill in your skills list, and choose to disable it or unlink your account.</p>"
            f"<h2>Contact</h2>{_contact(site, contact_url)}"
        )
    else:
        body = (
            f"{heading}<p>These terms cover your use of the {site_text} Alexa skill.</p>"
            f"<ul><li>Using the skill is subject to the same terms as using {site_text} itself.</li>"
            "<li>What the skill reads out is for information. It is not advice.</li>"
            "<li>The skill is provided as it is, with no warranty. It may be unavailable, slow or wrong at times.</li>"
            "<li>The skill may change, or be withdrawn, at any time.</li></ul>"
            f"<p>How the skill treats your information is described in the privacy policy.</p>"
        )
    return f"{root}{body}{footer}</div>"
