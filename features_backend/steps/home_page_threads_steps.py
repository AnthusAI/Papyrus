from __future__ import annotations

import copy
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.home_page.task import home_page_settings_of, run_home_page_snapshot  # noqa: E402
from papyrus_content.home_page.threads import NEVER_PUBLISHED_FIELDS, PUBLIC_MESSAGE_FIELDS, opaque_key  # noqa: E402
from procedures.newsroom.tests.reader_privacy import scan_files  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite  # noqa: E402

SITE_DIRECTORY = FIXTURES / "home-page"
REFERENCES_FIXTURE = REPO_ROOT / "features_backend" / "fixtures" / "home-page" / "references.json"
THREADS_FIXTURE = REPO_ROOT / "features_backend" / "fixtures" / "home-page" / "threads.json"
THREADS_KEY = "_data/home-page/threads.json"
THREAD_DIRECTORY = "_data/home-page/threads/"
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
SECRET_MARK = "SECRET"
THREAD_SECTION = re.compile(r'<section class="home-page-threads" data-layout="(?P<layout>[a-z]+)">(?P<body>.*?)</section>', re.S)
THREAD_CARD = re.compile(r'<li>(?P<card><article class="home-page-thread".*?</article>)</li>', re.S)
THREAD_TITLE = re.compile(r'<h3 class="home-page-title">(?P<title>[^<]*)</h3>')
MAIN = re.compile(r"<main.*?</main>", re.S)
TAG = re.compile(r"<[^>]+>")
PERSON_KEYS = frozenset(NEVER_PUBLISHED_FIELDS)


def load_threads_fixture() -> dict:
    """The fixture, with its ``{uuid}`` placeholder turned into a UUID, so the text that must be scrubbed holds one without the file doing so."""
    uuid_text = "-".join(["123e4567", "e89b", "12d3", "a456", "426614174000"])
    return json.loads(THREADS_FIXTURE.read_text(encoding="utf-8").replace("{uuid}", uuid_text))


def quoted(text: str) -> list[str]:
    return re.findall(r'"([^"]*)"', text)


class ThreadsClient:
    """The authoring client calls the snapshot makes, answered from the references and threads fixtures and the projected site's own Stories."""

    def __init__(self, site_client, threads: dict) -> None:
        self.references = json.loads(REFERENCES_FIXTURE.read_text(encoding="utf-8"))
        self.threads = threads
        self.site_client = site_client
        self.profile_reads: list[str] = []

    def rows(self) -> list[dict]:
        return [entry["row"] for entry in self.references["references"]]

    def list_by_index(self, index_name: str, key_value: str, *, limit: int = 100) -> list[dict]:
        if index_name == "referencesByCurationStatusKey":
            return [row for row in self.rows() if row["curationStatusKey"] == key_value]
        if index_name == "referencesByFeedStateAndPrediction":
            return [row for row in self.rows() if row["feedStateKey"] == key_value]
        if index_name == "messageThreadsByKindAndUpdatedAt":
            return [entry["thread"] for entry in self.threads["threads"] if entry["thread"]["threadKind"] == key_value]
        if index_name == "messagesByThreadAndSequence":
            return [row for entry in self.threads["threads"] if entry["thread"]["id"] == key_value for row in entry["messages"]]
        raise AssertionError(f"unexpected index {index_name}")

    def get_record(self, model_name: str, record_id: str):
        if model_name == "UserProfile":
            self.profile_reads.append(record_id)
            return self.threads["profiles"].get(record_id)
        return self.site_client.get_record(model_name, record_id)

    def list_semantic_relations_by_subject_state(self, subject_state_key: str) -> list[dict]:
        lineage = subject_state_key.removeprefix("reference#").removesuffix("#current")
        return [relation for entry in self.references["references"] if entry["row"]["lineageId"] == lineage for relation in entry["relations"]]

    def list_reference_attachments_by_lineage(self, reference_lineage_id: str) -> list[dict]:
        return [item for entry in self.references["references"] if entry["row"]["lineageId"] == reference_lineage_id for item in entry["attachments"]]

    def list_records(self, model_name: str) -> list[dict]:
        assert model_name == "NewsroomSection"
        return list(self.references["sections"])


def project_site(context, *, settings: dict | None = None, threads: dict | None = None) -> None:
    settings = settings if settings is not None else settings_copy()
    extra_files = {f"pages/{path.name}": path.read_bytes() for path in sorted((SITE_DIRECTORY / "pages").glob("*.md"))}
    context.build_error = None
    try:
        context.site = ProjectedSite(settings=settings, content=SITE_DIRECTORY / "content", extra_files=extra_files)
    except (AssertionError, ValueError) as error:
        context.build_error = str(error)
        return
    context.add_cleanup(context.site.cleanup)
    fixture = threads if threads is not None else load_threads_fixture()
    context.client = ThreadsClient(context.site.client, fixture)
    context.reports = []


def settings_copy() -> dict:
    settings = copy.deepcopy(json.loads((SITE_DIRECTORY / "projection.json").read_text(encoding="utf-8")))
    settings["homePage"]["threads"] = {"enabled": True}
    return settings


def run_task(context) -> dict:
    report = run_home_page_snapshot(context.site.context, context.client, home_page_settings_of(context.site.projector), now=NOW)
    context.reports.append(report)
    context.report = report
    return report


def threads_document(context) -> dict:
    body = context.site.writer.get(THREADS_KEY)
    assert body is not None, "threads.json was not written"
    return json.loads(body)


def thread_titled(context, title: str) -> dict:
    found = [thread for thread in threads_document(context)["threads"] if thread["title"] == title]
    assert len(found) == 1, f"{title!r} appears {len(found)} times in {[thread['title'] for thread in threads_document(context)['threads']]}"
    return found[0]


def thread_file(context, key: str) -> dict:
    body = context.site.writer.get(f"{THREAD_DIRECTORY}{key}.json")
    assert body is not None, f"the file of thread {key} is missing"
    return json.loads(body)


def published_files(context) -> dict[str, bytes]:
    return {key: body for key, body in context.site.tree.items() if key.startswith("_data/home-page/")}


def raw_thread_id(context, title: str) -> str:
    for entry in context.client.threads["threads"]:
        if entry["thread"]["title"] == title:
            return entry["thread"]["id"]
    raise AssertionError(f"the fixture has no thread {title!r}")


def lists(context, path: str) -> list[dict]:
    page = MAIN.search(context.site.text(path)).group(0)
    found = [{"layout": match["layout"], "cards": [card["card"] for card in THREAD_CARD.finditer(match["body"])]} for match in THREAD_SECTION.finditer(page)]
    assert found, f"{path} has no threads list"
    return found


def titles_of(cards: list[str]) -> list[str]:
    return [html.unescape(THREAD_TITLE.search(card)["title"]) for card in cards]


def one_list(context, path: str, layout: str | None = None) -> dict:
    found = lists(context, path)
    if layout is None:
        return found[0]
    chosen = [entry for entry in found if entry["layout"] == layout]
    assert chosen, f"{path} has no {layout} of threads"
    return chosen[0]


def card_titled(context, title: str) -> str:
    for path in ("threads-list/index.html", "threads-grid/index.html", "threads-mixed/index.html"):
        for entry in lists(context, path):
            for card in entry["cards"]:
                if titles_of([card]) == [title]:
                    return card
    raise AssertionError(f"no card titled {title!r}")


def card_text(card: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", TAG.sub(" ", card))).strip()


@given("the home-page threads fixture site is projected")
def projected(context) -> None:
    project_site(context)
    assert context.build_error is None, context.build_error


@given('the home-page threads fixture site is projected with authors "{policy}" and the anonymous label "{label}"')
def projected_with_policy(context, policy: str, label: str) -> None:
    settings = settings_copy()
    settings["homePage"]["threads"].update({"authors": policy, "anonymousLabel": label})
    project_site(context, settings=settings)
    assert context.build_error is None, context.build_error


@given("the home-page threads fixture site is projected with threads switched off")
def projected_with_threads_off(context) -> None:
    settings = settings_copy()
    settings["homePage"]["threads"] = {"enabled": False}
    project_site(context, settings=settings)
    assert context.build_error is None, context.build_error


@given("the home-page threads fixture site is projected with only private conversations")
def projected_with_private_conversations(context) -> None:
    fixture = load_threads_fixture()
    for entry in fixture["threads"]:
        entry["thread"]["status"] = "archived"
    project_site(context, threads=fixture)
    assert context.build_error is None, context.build_error


@given("the home-page threads fixture site is projected without a homePage setting")
def projected_without_home_page(context) -> None:
    settings = settings_copy()
    del settings["homePage"]
    settings["pages"] = [page for page in settings["pages"] if page["id"] == "threads-list"]
    extra_files = {"pages/threads-list.md": (SITE_DIRECTORY / "pages" / "threads-list.md").read_bytes()}
    context.build_error = None
    try:
        context.site = ProjectedSite(settings=settings, content=SITE_DIRECTORY / "content", extra_files=extra_files)
    except (AssertionError, ValueError) as error:
        context.build_error = str(error)
        return
    context.add_cleanup(context.site.cleanup)


@given("the home-page threads fixture site is projected with the include attribute {attribute}")
def projected_with_attribute(context, attribute: str) -> None:
    name, value = attribute.split("=", 1)
    attributes = {"select": "recent", "count": "3", "layout": "list", name: value.strip('"')}
    line = "::include{kind=\"threads\" " + " ".join(f'{key}="{given}"' for key, given in attributes.items()) + "}"
    extra_files = {f"pages/{path.name}": path.read_bytes() for path in sorted((SITE_DIRECTORY / "pages").glob("*.md"))}
    extra_files["pages/threads-list.md"] = ('::band{size="bare"}\n' + line + "\n").encode("utf-8")
    context.build_error = None
    try:
        context.site = ProjectedSite(settings=settings_copy(), content=SITE_DIRECTORY / "content", extra_files=extra_files)
    except (AssertionError, ValueError) as error:
        context.build_error = str(error)
        return
    context.add_cleanup(context.site.cleanup)


@when("the home-page-snapshot task runs against the threads fixture")
def run_snapshot(context) -> None:
    run_task(context)


@when("the home-page-snapshot task runs again against the threads fixture")
def run_snapshot_again(context) -> None:
    context.mark = len(context.site.writer.operations)
    run_task(context)


@when('the thread "{title}" is archived and the home-page-snapshot task runs again')
def archive_and_run(context, title: str) -> None:
    identifier = raw_thread_id(context, title)
    for entry in context.client.threads["threads"]:
        if entry["thread"]["id"] == identifier:
            entry["thread"]["status"] = "archived"
    context.before_archive_key = opaque_key(identifier)
    context.mark = len(context.site.writer.operations)
    run_task(context)


@then("the threads in threads.json, most recently active first, are {titles}")
def threads_are(context, titles: str) -> None:
    found = [thread["title"] for thread in threads_document(context)["threads"]]
    assert found == quoted(titles), found


@then("threads.json lists no thread")
def no_threads(context) -> None:
    assert threads_document(context)["threads"] == []


@then("threads.json holds none of {titles}")
def threads_hold_none(context, titles: str) -> None:
    text = context.site.writer.get(THREADS_KEY).decode("utf-8")
    for title in quoted(titles):
        assert title not in text, title


@then("a thread on a Reference is anchored by the Reference's public key and a thread on a Story by the Story's page address")
def anchors(context) -> None:
    reference = thread_titled(context, "Is this tool worth adopting?")["anchor"]
    assert reference["kind"] == "reference" and re.fullmatch(r"[0-9a-f]{12}", reference["key"]) and reference["title"] == "Accepted eight", reference
    story = thread_titled(context, "Fungi follow-up")["anchor"]
    assert story == {"kind": "story", "url": "/fungi.html", "title": "Fungi Underground"}, story
    recommended = thread_titled(context, "Notes on the pending high candidate")["anchor"]
    assert recommended["kind"] == "reference" and recommended["title"] == "Pending high", recommended


@then('the thread "{title}" has {count:d} messages')
def thread_has_messages(context, title: str, count: int) -> None:
    thread = thread_titled(context, title)
    assert thread["messages"] == count, thread
    assert len(thread_file(context, thread["key"])["messages"]) == count


@then("its latest Message is marked as edited")
def latest_edited(context) -> None:
    assert thread_titled(context, "Is this tool worth adopting?")["latest"]["edited"] is True


@then("no published file holds the text of a deleted, moderated or system Message")
def no_secret_text(context) -> None:
    for key, body in published_files(context).items():
        assert SECRET_MARK not in body.decode("utf-8"), key
    assert any(key.startswith(THREAD_DIRECTORY) for key in published_files(context))


def author_of(message: dict) -> dict:
    return message["author"]


@then('the first Message of the thread "{title}" is by the handle "{handle}"')
def first_by_handle(context, title: str, handle: str) -> None:
    thread = thread_titled(context, title)
    assert author_of(thread_file(context, thread["key"])["messages"][0]) == {"handle": handle}


@then('the latest Message of the thread "{title}" is by the handle "{handle}"')
def latest_by_handle(context, title: str, handle: str) -> None:
    assert author_of(thread_titled(context, title)["latest"]) == {"handle": handle}


@then('the latest Message of the thread "{title}" is by the label "{label}"')
def latest_by_label(context, title: str, label: str) -> None:
    assert author_of(thread_titled(context, title)["latest"]) == {"label": label}


@then("every public Message has exactly the public fields and no field that names a person or a record")
def messages_have_public_fields(context) -> None:
    seen = 0
    for key, body in published_files(context).items():
        if not key.startswith(THREAD_DIRECTORY):
            continue
        for message in json.loads(body)["messages"]:
            seen += 1
            assert tuple(message) == PUBLIC_MESSAGE_FIELDS, message
            assert not set(message["author"]) - {"handle", "label"}, message
            assert not PERSON_KEYS & set(message), message
    assert seen


@then("the identity scanner finds nothing in any published file")
def scanner_clean(context) -> None:
    files = {key: body for key, body in context.site.tree.items() if key.endswith((".html", ".md", ".txt", ".json", ".xml"))}
    assert any(key.startswith(THREAD_DIRECTORY) for key in files) and any(key.startswith("threads-list/") for key in files)
    assert scan_files(files, []) == {}, scan_files(files, [])


@then('every Message in every thread is by the label "{label}" or "{ai}"')
def every_by_label(context, label: str, ai: str) -> None:
    seen = 0
    for key, body in published_files(context).items():
        if key.startswith(THREAD_DIRECTORY):
            for message in json.loads(body)["messages"]:
                seen += 1
                assert message["author"] in ({"label": label}, {"label": ai}), message
    assert seen


@then("the profile of no author was read")
def no_profile_read(context) -> None:
    assert context.client.profile_reads == []


@then('the threads list on "{path}" lists {titles}')
def list_lists(context, path: str, titles: str) -> None:
    found = titles_of(one_list(context, path)["cards"])
    assert found == quoted(titles), found


@then('the threads in the list on "{path}" lists {titles}')
def in_list_lists(context, path: str, titles: str) -> None:
    found = titles_of(one_list(context, path, "list")["cards"])
    assert found == quoted(titles), found


@then('the threads grid on "{path}" lists {titles}')
def grid_lists(context, path: str, titles: str) -> None:
    found = titles_of(one_list(context, path, "grid")["cards"])
    assert found == quoted(titles), found


@then('the threads list on "{path}" is drawn as a "{layout}"')
def list_layout(context, path: str, layout: str) -> None:
    entry = one_list(context, path)
    assert entry["layout"] == layout and entry["cards"], entry


@then('"{path}" no longer lists "{title}"')
def no_longer_lists(context, path: str, title: str) -> None:
    assert title not in titles_of(one_list(context, path)["cards"])


@then('no thread title appears twice on "{path}"')
def no_thread_twice(context, path: str) -> None:
    placed = [title for entry in lists(context, path) for title in titles_of(entry["cards"])]
    assert placed and len(placed) == len(set(placed)), placed


@then('the card for "{title}" says "{text}" next to a "{icon}" icon')
def card_says(context, title: str, text: str, icon: str) -> None:
    card = card_titled(context, title)
    assert text in card_text(card), card_text(card)
    assert f'data-icon="{icon}"' in card, card


@then('the card for "{title}" shows the date "{date}"')
def card_date(context, title: str, date: str) -> None:
    assert f">{date}</time>" in card_titled(context, title)


@then('the card for "{title}" quotes "{text}" and says it is "{by}"')
def card_quotes_and_by(context, title: str, text: str, by: str) -> None:
    card = card_titled(context, title)
    assert f'<p class="home-page-excerpt">{html.escape(text)}</p>' in card, card
    assert f'<p class="home-page-author">{html.escape(by)}</p>' in card, card


@then('the card for "{title}" says it is "{by}"')
def card_by(context, title: str, by: str) -> None:
    assert f'<p class="home-page-author">{html.escape(by)}</p>' in card_titled(context, title)


@then('the card for "{title}" shows the quote "{text}"')
def card_shows_quote(context, title: str, text: str) -> None:
    assert f'<p class="home-page-excerpt">{html.escape(text)}</p>' in card_titled(context, title), card_titled(context, title)


@then('the card for "{title}" quotes at most {limit:d} characters ending in a full stop')
def card_quotes_clipped(context, title: str, limit: int) -> None:
    excerpt = re.search(r'<p class="home-page-excerpt">(?P<text>[^<]*)</p>', card_titled(context, title))["text"]
    text = html.unescape(excerpt)
    assert len(text) <= limit and text.endswith(".") and "*" not in text and "](" not in text, text
    assert text.startswith("The first finding") and "fourth" not in text, text


@then("the card for \"{title}\" links its anchor to the Story's page")
def card_links_story(context, title: str) -> None:
    assert '<a href="/fungi.html">Fungi Underground</a>' in card_titled(context, title)


@then("the stylesheet and cards draw no borders and show every state in words and an icon")
def threads_no_borders(context) -> None:
    stylesheet = (REPO_ROOT / "src" / "papyrus_content" / "projection" / "standard" / "assets" / "papyrus-home-page.css").read_text(encoding="utf-8")
    declarations = re.findall(r"(?<![-\w])(border[\w-]*|outline[\w-]*|box-shadow)\s*:\s*([^;}]*)", stylesheet)
    assert all(name == "border-radius" for name, _ in declarations), declarations
    for path in ("threads-list/index.html", "threads-grid/index.html"):
        for card in one_list(context, path)["cards"]:
            assert "message-square" in card and ('data-icon="link"' in card or 'data-icon="file-text"' in card), card
            assert "Reference:" in card_text(card) or "Story:" in card_text(card), card_text(card)


@then("the per-thread file of \"{title}\" is deleted")
def file_deleted(context, title: str) -> None:
    key = f"{THREAD_DIRECTORY}{context.before_archive_key}.json"
    assert context.site.writer.get(key) is None
    assert ("delete", key) in context.site.writer.operations
    assert context.report["deleted"] == [key], context.report


@then("the per-thread files of {titles} remain")
def files_remain(context, titles: str) -> None:
    for title in quoted(titles):
        thread = thread_titled(context, title)
        assert context.site.writer.get(f"{THREAD_DIRECTORY}{thread['key']}.json") is not None, title


@then('the page "{key}" was re-rendered by the second run')
def rerendered_by_second_run(context, key: str) -> None:
    assert ("put", key) in context.site.writer.operations[context.mark:]


@then("the second run wrote and deleted nothing")
def second_run_idle(context) -> None:
    assert context.report["written"] == [] and context.report["deleted"] == [], context.report
    assert context.site.writer.operations[context.mark:] == []


@then("the store holds no thread file")
def no_thread_file(context) -> None:
    assert [key for key in context.site.tree if key.startswith("_data/home-page/threads")] == []
    assert context.report["threads"] == 0


@then('the file of the thread "{title}" holds its title, its anchor and {count:d} Messages in sequence')
def thread_file_shape(context, title: str, count: int) -> None:
    summary = thread_titled(context, title)
    document = thread_file(context, summary["key"])
    assert list(document) == ["key", "title", "anchor", "messages"], list(document)
    assert document["title"] == title and document["anchor"] == summary["anchor"]
    ordered = [message["at"] for message in document["messages"]]
    assert len(ordered) == count and ordered == sorted(ordered), ordered
    assert document["messages"][-1] == summary["latest"]


@then("no page reads the per-thread files")
def no_page_reads_files(context) -> None:
    for key, body in context.site.tree.items():
        if key.endswith((".html", ".md")):
            assert THREAD_DIRECTORY not in body.decode("utf-8"), key


@then('the threads build failed saying "{first}" and "{second}"')
def threads_build_failed(context, first: str, second: str) -> None:
    assert context.build_error is not None, "the build succeeded"
    assert first in context.build_error and second in context.build_error, context.build_error
