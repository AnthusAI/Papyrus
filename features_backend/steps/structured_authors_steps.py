from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree

from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from procedures.newsroom.tests.standard_frontend_support import ProjectedSite  # noqa: E402

ATOM = {"a": "http://www.w3.org/2005/Atom"}
DC_CREATOR = "{http://purl.org/dc/elements/1.1/}creator"


def names(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def atom_authors(context, slug: str):
    root = ElementTree.fromstring(context.authors_site.tree["atom.xml"])
    for entry in root.findall("a:entry", ATOM):
        if entry.findtext("a:id", namespaces=ATOM).endswith(f"/{slug}.html"):
            return entry.findall("a:author", ATOM)
    raise AssertionError(f"no Atom entry {slug}")


@given("a site with articles by a string, by a list, by objects and by nobody has been projected")
def authors_site(context) -> None:
    context.authors_site = ProjectedSite("authors")
    context.add_cleanup(context.authors_site.cleanup)


@then('the Atom entry "{slug}" has the authors "{authors}"')
def atom_has_authors(context, slug: str, authors: str) -> None:
    found = [author.findtext("a:name", namespaces=ATOM) for author in atom_authors(context, slug)]
    assert found == names(authors), found


@then('the Atom entry "{slug}" has no authors')
def atom_has_no_authors(context, slug: str) -> None:
    assert atom_authors(context, slug) == []


def atom_author(context, name: str):
    root = ElementTree.fromstring(context.authors_site.tree["atom.xml"])
    for author in root.findall("a:entry/a:author", ATOM):
        if author.findtext("a:name", namespaces=ATOM) == name:
            return author
    raise AssertionError(f"no Atom author {name}")


@then('the Atom author "{name}" has the uri "{uri}"')
def atom_author_uri(context, name: str, uri: str) -> None:
    assert atom_author(context, name).findtext("a:uri", namespaces=ATOM) == uri


@then('the Atom author "{name}" has no uri')
def atom_author_no_uri(context, name: str) -> None:
    assert atom_author(context, name).find("a:uri", ATOM) is None


def rss_creators(context, slug: str) -> list[str]:
    root = ElementTree.fromstring(context.authors_site.tree["feed.xml"])
    for item in root.iter("item"):
        if item.findtext("link").endswith(f"/{slug}.html"):
            return [creator.text for creator in item.findall(DC_CREATOR)]
    raise AssertionError(f"no RSS item {slug}")


@then('the RSS item "{slug}" has the creators "{creators}"')
def rss_has_creators(context, slug: str, creators: str) -> None:
    assert rss_creators(context, slug) == names(creators)


@then('the RSS item "{slug}" has no creators')
def rss_has_no_creators(context, slug: str) -> None:
    assert rss_creators(context, slug) == []


@then('the page "{key}" says "{text}"')
def page_says(context, key: str, text: str) -> None:
    assert text in context.authors_site.text(key), context.authors_site.text(key)


@then('the page "{key}" does not say "{text}"')
def page_does_not_say(context, key: str, text: str) -> None:
    assert text not in context.authors_site.text(key)


def public_record(context, url: str) -> dict:
    return next(record for record in json.loads(context.authors_site.text("_data/search-index.json")) if record["url"] == url)


@then('the public data entry "{url}" has the authors "{authors}"')
def public_has_authors(context, url: str, authors: str) -> None:
    assert public_record(context, url)["authors"] == names(authors)


@then('the public data entry "{url}" has no authors key')
def public_has_no_authors(context, url: str) -> None:
    assert "authors" not in public_record(context, url)


def entry_for_slug(context, slug: str):
    site = context.authors_site
    return next(entry for entry in site.projector._entries(site.context.source.site_index()) if entry.slug == slug)


@then('the entry "{slug}" has the authors "{authors}" as plain names that join with commas')
def entry_authors_are_names(context, slug: str, authors: str) -> None:
    entry = entry_for_slug(context, slug)
    assert all(isinstance(name, str) for name in entry.authors), entry.authors
    assert ", ".join(entry.authors) == ", ".join(names(authors)), entry.authors


@then('the entry "{slug}" has no author names')
def entry_has_no_author_names(context, slug: str) -> None:
    assert entry_for_slug(context, slug).authors == ()


@then('the entry "{slug}" keeps the url of the author "{name}" in its author details')
def entry_details_keep_url(context, slug: str, name: str) -> None:
    details = {author.name: author for author in entry_for_slug(context, slug).author_details}
    assert details[name].url, details
