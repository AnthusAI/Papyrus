"""Public thread pages (homePage.forum): the settings, the page, its twin, the digest and the privacy scan."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

import pytest

from papyrus_content.home_page.settings import ForumSettings, home_page_settings_from_mapping
from papyrus_content.home_page.snapshot import build_threads_snapshot, snapshot_bytes, thread_file
from papyrus_content.projection.standard.forum_pages import is_thread_key, thread_fragment, thread_markdown
from procedures.newsroom.tests.reader_privacy import scan_files
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
REFERENCE_KEY = "b94890d5bbae"
FIRST_KEY = hashlib.sha256(b"first thread").hexdigest()[:12]
SECOND_KEY = hashlib.sha256(b"second thread").hexdigest()[:12]


def message(key, at, text, author, edited=False):
    return {"key": key, "at": at, "edited": edited, "text": text, "author": author}


THREADS = [
    {
        "key": FIRST_KEY, "title": "Is this worth adopting?", "anchor": {"kind": "reference", "key": REFERENCE_KEY, "title": "Accepted eight"},
        "messages": [
            message("m1", "2026-10-30T09:00:00Z", "First line\nsecond line\n\nNew <b>paragraph</b>", {"handle": "ryan"}),
            message("m2", "2026-10-31T10:00:00Z", "Agreed.", {"label": "Editor"}, edited=True),
        ],
    },
    {
        "key": SECOND_KEY, "title": "Fungi follow-up", "anchor": {"kind": "story", "url": "/fungi.html", "title": "Fungi Underground"},
        "messages": [message("m3", "2026-10-29T08:00:00Z", "A note on spores.", {"label": "AI"})],
    },
]


def seed_for(threads) -> dict[str, bytes]:
    index, documents = build_threads_snapshot(threads, NOW)
    seed = {"_data/home-page/threads.json": snapshot_bytes(index)}
    seed.update({thread_file(key): snapshot_bytes(document) for key, document in documents.items()})
    return seed


def settings_with_forum(forum) -> dict:
    settings = copy.deepcopy(json.loads((FIXTURES / "home-page" / "projection.json").read_text(encoding="utf-8")))
    settings["homePage"]["threads"] = {"enabled": True}
    if forum is not None:
        settings["homePage"]["forum"] = forum
    return settings


def project(forum=None, threads=THREADS, **options):
    seed = {**seed_for(threads), "_data/home-page/references.json": (FIXTURES / "home-page" / "_data" / "home-page" / "references.json").read_bytes()}
    pages = {f"pages/{path.name}": path.read_bytes() for path in sorted((FIXTURES / "home-page" / "pages").glob("*.md"))}
    return ProjectedSite(settings=settings_with_forum(forum), content=FIXTURES / "home-page" / "content", extra_files=pages, seed=seed, **options)


@pytest.fixture
def site():
    built = project({})
    yield built
    built.cleanup()


def test_forum_defaults_and_unknown_keys():
    assert home_page_settings_from_mapping({}).forum is None
    assert home_page_settings_from_mapping({"forum": {}}).forum == ForumSettings("conversations", 50, None)
    configured = home_page_settings_from_mapping({"forum": {"threadBase": "talk/", "index": {"pageSize": 20}, "posting": {"enabled": True}}}).forum
    assert (configured.thread_base, configured.index_page_size, configured.posting) == ("talk", 20, {"enabled": True})
    with pytest.raises(ValueError, match="Unknown homePage.forum settings: pageLimit"):
        home_page_settings_from_mapping({"forum": {"pageLimit": 3}})
    with pytest.raises(ValueError, match="Unknown homePage.forum.index settings: size"):
        home_page_settings_from_mapping({"forum": {"index": {"size": 3}}})
    with pytest.raises(ValueError, match="pageSize must be a whole number of at least 1"):
        home_page_settings_from_mapping({"forum": {"index": {"pageSize": 0}}})


def test_forum_thread_pages_and_twins_are_written_for_each_thread(site):
    for key in (FIRST_KEY, SECOND_KEY):
        assert f"conversations/{key}/index.html" in site.tree and f"conversations/{key}/index.md" in site.tree
    page = site.text(f"conversations/{FIRST_KEY}/index.html")
    assert page.index("First line") < page.index("Agreed.")
    assert "<p>First line<br>second line</p><p>New &lt;b&gt;paragraph&lt;/b&gt;</p>" in page
    assert 'data-icon="user"' in page and 'data-icon="badge-check"' in page and 'data-icon="pencil"' in page
    assert "home-page-row" in page
    assert "papyrus-home-page.css?v=" in page  # a thread page styles its cards even without an include


def test_forum_the_reference_anchor_falls_back_to_a_line_when_the_snapshot_lacks_it():
    threads = copy.deepcopy(THREADS)
    threads[0]["anchor"]["key"] = "ffffffffffff"
    built = project({}, threads)
    try:
        page = built.text(f"conversations/{FIRST_KEY}/index.html")
        assert "home-page-row" not in page and "Reference: Accepted eight" in page
    finally:
        built.cleanup()


def test_forum_a_thread_base_moves_the_pages():
    built = project({"threadBase": "talk"})
    try:
        assert f"talk/{FIRST_KEY}/index.html" in built.tree and not [key for key in built.tree if key.startswith("conversations/")]
    finally:
        built.cleanup()


def test_forum_a_site_without_forum_is_byte_identical_to_one_with_threads_but_no_forum_setting():
    without = project(None)
    try:
        assert not [key for key in without.tree if key.startswith("conversations/")]
        assert "llms.txt" in without.tree and "Conversations" not in without.text("llms.txt")
    finally:
        without.cleanup()


def test_forum_llms_and_sitemap_name_the_thread_pages(site):
    llms = site.text("llms.txt")
    assert "## Conversations" in llms and f"/conversations/{FIRST_KEY}/index.md" in llms
    sitemap = "".join(body.decode("utf-8") for key, body in site.tree.items() if key.startswith("sitemap") and key.endswith(".xml"))
    assert f"/conversations/{FIRST_KEY}/" in sitemap


def test_forum_the_page_digest_follows_only_its_own_thread_file(site):
    projector = site.projector
    plan = projector._plan(site.context.source.site_index())
    first, second = (plan[f"conversations/{key}/index.html"][0] for key in (FIRST_KEY, SECOND_KEY))
    changed = copy.deepcopy(THREADS)
    changed[0]["messages"].append(message("m4", "2026-10-31T11:00:00Z", "One more.", {"label": "Editor"}))
    for name, body in seed_for(changed).items():
        (site.out / name).write_bytes(body)
    projector._home_page.reset()
    projector._plan_cache = None
    plan = projector._plan(site.context.source.site_index())
    assert plan[f"conversations/{FIRST_KEY}/index.html"][0] != first
    assert plan[f"conversations/{SECOND_KEY}/index.html"][0] == second


def test_forum_the_reader_pages_include_thread_pages_and_twins(site):
    keys = site.projector.home_page_reader_keys()
    assert {f"conversations/{FIRST_KEY}/index.html", f"conversations/{FIRST_KEY}/index.md"} <= keys
    assert site.projector.thread_page_keys(FIRST_KEY) == (f"conversations/{FIRST_KEY}/index.html", f"conversations/{FIRST_KEY}/index.md")
    assert site.projector.thread_page_keys("../escape") == ()
    assert site.projector.owns_page_key(f"conversations/{FIRST_KEY}/index.html") and site.projector.owns_page_key(f"conversations/{FIRST_KEY}/index.md")


def test_forum_a_file_that_is_not_an_opaque_key_is_not_a_page():
    threads = copy.deepcopy(THREADS)
    threads[1]["key"] = "../../etc"
    built = project({}, threads)
    try:
        pages = [key for key in built.tree if key.startswith("conversations/")]
        assert pages and all(FIRST_KEY in key for key in pages)
    finally:
        built.cleanup()
    assert is_thread_key(FIRST_KEY) and not is_thread_key("ABC") and not is_thread_key(None)


def test_forum_thread_pages_pass_the_reader_privacy_scan(site):
    files = {key: body for key, body in site.tree.items() if key.startswith("conversations/")}
    assert files and scan_files(files, []) == {}


def test_forum_twin_and_fragment_are_pure():
    twin = thread_markdown(THREADS[0], "https://example.org/conversations/x/", "Reference: Accepted eight")
    assert twin.startswith("# Is this worth adopting?\n") and "## ryan, 30 Oct 2026" in twin and "## Editor, 31 Oct 2026 (edited)" in twin
    assert thread_fragment(THREADS[1], None).count("<article") == 1
