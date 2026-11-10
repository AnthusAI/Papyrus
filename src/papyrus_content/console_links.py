"""Console links: the address of one Story, Reference, Concept, Assignment or review item in the newsroom console.

One place builds every console address, so the CLI (`papyrus links`, and the `console` rows of `stories create`, `stories save-version`,
`stories show` and `references show`) and anything that wraps it print the same thing. Building an address needs no network: it is
`console base + path`. The base is the console's own address, `https://<console host><newsroom path>`, which only the site knows
(a console on its own host, a console at `/newsroom` of the public host, a console mounted at the root). The CLI never guesses it:
it takes, in order, `--console-url`, `PAPYRUS_CONSOLE_URL`, then `console_url` from the signed-in site's public site file
(`/.well-known/papyrus-site.json`). With none of those the command says so and prints nothing.

The routes are the ones the console really parses (docs/console-links.md has the table and what each does when the id is wrong).
There is no route for a Story's checklist of its own and none for a single review request outside the Notification Center item
address; those are stated plainly rather than invented.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass
from typing import Any

CONSOLE_URL_VARIABLE = "PAPYRUS_CONSOLE_URL"

STORY_BOARD_PATH = "/articles"   # the Story board; a site that renames its content item redirects it and loses the query (see docs)
STORY_OPEN_PARAMETER = "open"
STORY_BOARD_PREFIX = "contentItem:"


class ConsoleLinkError(ValueError):
    """The console address is unknown or an id cannot be turned into a link; the message says what to do."""


@dataclass(frozen=True)
class ConsoleLink:
    kind: str
    url: str
    note: str = ""


UNKNOWN_CONSOLE = (
    "The console address of this site is unknown, so no link was built (links are never guessed). Pass --console-url "
    "https://<console host>[/newsroom], or set PAPYRUS_CONSOLE_URL, or sign in to a site that publishes it "
    "(console_url in /.well-known/papyrus-site.json, which a site publishes once it runs a release that has it)."
)


def normalize_console_url(value: object) -> str:
    """An https address with no credentials, query or fragment; a trailing slash is dropped. The path is the newsroom path ('' or '/newsroom')."""
    text = str(value or "").strip()
    parts = urllib.parse.urlsplit(text)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
            or any(ch.isspace() for ch in text)):
        raise ConsoleLinkError(f"Not a console address: {text!r}. Give an https address with no query, such as https://newsroom.example.test/newsroom.")
    return f"https://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def resolve_console_url(override: str | None = None, *, published: Any = None) -> str:
    """The console base: the flag, else the environment, else what the signed-in site publishes. Raises ConsoleLinkError when none says."""
    chosen = (override or "").strip() or os.environ.get(CONSOLE_URL_VARIABLE, "").strip()
    if chosen:
        return normalize_console_url(chosen)
    if published is None:
        from . import env
        published = env.site_published
    try:
        found = published("console_url")
    except Exception:   # noqa: BLE001 - no readable site is the same answer as a site that does not say
        found = None
    if not found:
        raise ConsoleLinkError(UNKNOWN_CONSOLE)
    return normalize_console_url(found)


def _segment(value: str, what: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ConsoleLinkError(f"A {what} id is needed to build its console link.")
    return urllib.parse.quote(text, safe="")


def story_board_url(base: str, lineage_id: str) -> str:
    """The Story board with this Story's drawer open (its latest version, its checklist, its stars)."""
    return f"{base}{STORY_BOARD_PATH}?{STORY_OPEN_PARAMETER}={_segment(STORY_BOARD_PREFIX + str(lineage_id or '').strip(), 'story')}"


def story_version_url(base: str, version_id: str) -> str:
    """The Story editor page of exactly one saved version (draft or published); the id is the version record id."""
    return f"{base}{STORY_BOARD_PATH}/{_segment(version_id, 'story version')}"


def reference_url(base: str, lineage_id: str) -> str:
    return f"{base}/references/{_segment(lineage_id, 'reference')}"


def concept_url(base: str, lineage_id: str) -> str:
    """`?node=` is the form the server reads on a first load; `/concepts/<id>` only works for in-page navigation."""
    return f"{base}/concepts?node={_segment(lineage_id, 'concept')}"


def assignment_url(base: str, assignment_id: str) -> str:
    return f"{base}/assignments/{_segment(assignment_id, 'assignment')}"


def review_url(base: str, item_id: str) -> str:
    """A Notification Center item (a review request id such as rr-..., or a Reference lineage waiting for a decision)."""
    return f"{base}/needs-me/{_segment(item_id, 'review item')}"


def story_links(base: str, lineage_id: str, version_id: str | None = None, version_note: str = "") -> list[ConsoleLink]:
    """Every address a Story has. Without a version id only the board drawer can be built (the drawer needs just the lineage id)."""
    drawer = story_board_url(base, lineage_id)
    links: list[ConsoleLink] = []
    if version_id:
        links.append(ConsoleLink("story", story_version_url(base, version_id), version_note or "editor page of that exact version"))
    links.append(ConsoleLink("story-board", drawer, "board drawer: the latest version, its checklist and stars"))
    links.append(ConsoleLink("checklist", drawer, "the checklist has no address of its own; it is a panel in the board drawer"))
    return links


def console_rows(group: str, command: str, links: list[ConsoleLink]) -> list[str]:
    """The tab-separated `console` rows a command prints after its own rows."""
    return ["\t".join([group, command, "console", link.kind, link.url]) for link in links]


def print_console_rows(group: str, command: str, build, *, override: str | None = None) -> None:
    """Print the console rows built by `build(base)`. A command's own result is never lost to a link problem: an unknown console prints one row saying so."""
    try:
        for row in console_rows(group, command, build(resolve_console_url(override))):
            print(row)
    except ConsoleLinkError as error:
        print("\t".join([group, command, "console", "unavailable", str(error)]))


def render_json(base: str, links: list[ConsoleLink]) -> str:
    return json.dumps({"ok": True, "console": base, "links": [{"kind": link.kind, "url": link.url, "note": link.note} for link in links]}, indent=2)


LINKS_USAGE = (
    "Usage: papyrus links [--story LINEAGE|SLUG [--version N|VERSION_ID]] [--reference REFERENCE_ID|LINEAGE] [--concept NAME|NODEKEY] [--assignment ID]\n"
    "                    [--review ID] [--console-url URL] [--json]\n"
    "  Read only. Prints the newsroom console address of each item named, built from the console address the signed-in site publishes\n"
    "  (or --console-url / PAPYRUS_CONSOLE_URL). Hand these to the editor when you worked on the item. A story prints its editor page for one\n"
    "  version (the current one unless --version), its board drawer, and the checklist (a panel of that drawer; it has no address of its own).\n"
    "  Each id is checked against the site first, so a link is never built for something that does not exist. An unknown console address fails\n"
    "  with a message; it is never guessed."
)


def _need(value: Any, flag: str) -> str:
    if value is True or not str(value or "").strip():
        raise ValueError(f"{flag} needs a value.")
    return str(value).strip()


def build_links(options: dict[str, Any], client: Any, base: str) -> list[ConsoleLink]:
    """Every link the options ask for. Reads the site (never writes) to turn a slug, a version number or a name into the id the console takes."""
    links: list[ConsoleLink] = []
    if options.get("story") is not None:
        from .story_links import resolve_story
        from .story_reporting import story_versions

        current = resolve_story(client, _need(options["story"], "--story"))
        lineage = str(current.get("lineageId") or current["id"])
        chosen, note = current, "editor page of the current version"
        if options.get("version") is not None:
            wanted = _need(options["version"], "--version")
            versions = story_versions(client, lineage)
            if wanted.isdigit():
                chosen = next((row for row in versions if int(row.get("versionNumber") or 0) == int(wanted)), None)
            else:
                chosen = next((row for row in versions if row["id"] == wanted), None)
            if chosen is None:
                have = ", ".join(str(row.get("versionNumber")) for row in versions)
                raise ValueError(f"Story {lineage} has no version {wanted} (versions: {have}).")
            note = f"editor page of version {chosen.get('versionNumber')} ({chosen.get('status') or 'draft'})"
        links.extend(story_links(base, lineage, chosen["id"], note))
    elif options.get("version") is not None:
        raise ValueError("--version needs --story.")
    if options.get("reference") is not None:
        from .story_reporting import current_reference

        wanted = _need(options["reference"], "--reference")
        record = current_reference(client, wanted)
        if record is None:
            raise ValueError(f"No Reference {wanted!r}. Give an id or lineage id that `papyrus stories show` or `papyrus references list` prints.")
        links.append(ConsoleLink("reference", reference_url(base, str(record.get("lineageId") or record["id"])), "Reference review page"))
    if options.get("concept") is not None:
        from .section_concepts import current_concept_nodes, resolve_concept

        text = _need(options["concept"], "--concept")
        nodes = current_concept_nodes(client)
        node = resolve_concept(nodes, text) or next((n for n in nodes if text in (n.get("lineageId"), n.get("id"))), None)
        if node is None:
            raise ValueError(f"No concept is named {text!r}. Name an existing concept by its name, alias, #hashtag, node key or lineage id.")
        links.append(ConsoleLink("concept", concept_url(base, str(node.get("lineageId") or node["id"])), "concept page"))
    if options.get("assignment") is not None:
        wanted = _need(options["assignment"], "--assignment")
        if client.get_record("Assignment", wanted) is None:
            raise ValueError(f"No Assignment {wanted!r}.")
        links.append(ConsoleLink("assignment", assignment_url(base, wanted), "assignment page"))
    if options.get("review") is not None:
        wanted = _need(options["review"], "--review")
        links.append(ConsoleLink("review", review_url(base, wanted), "Notification Center item; it opens while the item still waits for a decision"))
    return links


def links_command(flags: list[str], *, client: Any = None) -> int:
    """papyrus links ...: print the console address of each item named."""
    from .options import parse_options

    options = parse_options(flags)
    if options.get("help") is True or options.get("h") is True:
        print(LINKS_USAGE)
        return 0
    asked = [name for name in ("story", "reference", "concept", "assignment", "review") if options.get(name) is not None]
    if not asked:
        raise ValueError("papyrus links needs at least one of --story, --reference, --concept, --assignment, --review.\n" + LINKS_USAGE)
    override = options.get("console-url")
    base = resolve_console_url(None if override is True else override)   # fail on an unknown console before reading anything
    needs_site = any(name in asked for name in ("story", "reference", "concept", "assignment"))
    if client is None and needs_site:
        from .graphql_authoring import create_authoring_client

        client = create_authoring_client()[0]
    links = build_links(options, client, base)
    if options.get("json"):
        print(render_json(base, links))
        return 0
    for link in links:
        print("\t".join(["links", link.kind, link.url, link.note]))
    return 0
