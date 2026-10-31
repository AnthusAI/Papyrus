from __future__ import annotations

import pytest

from ...home_page.settings import HomePageSettings
from . import home_page_blocks as blocks
from . import home_page_components as parts
from .page_ledger import PageLedger


def thread(key, last_at, text="Hello there. More text.", author=None, anchor=None):
    latest = {"key": "m", "at": last_at, "edited": False, "text": text, "author": author or {"label": "Editor"}}
    return {"key": key, "title": f"Title {key}", "anchor": anchor or {"kind": "reference", "key": "k", "title": "Ref"}, "messages": 2, "lastAt": last_at, "latest": latest}


DOCUMENT = {"threads": [thread("a", "2026-10-01T00:00:00Z"), thread("b", "2026-10-03T00:00:00Z"), thread("c", "2026-10-02T00:00:00Z")]}


def test_select_threads_orders_by_last_activity_and_claims_in_the_ledger():
    ledger = PageLedger()
    chosen = blocks.select_threads(DOCUMENT, {"select": "recent", "count": "2"}, ledger)
    assert [entry["key"] for entry in chosen] == ["b", "c"]
    assert ledger.seen == {"thread:b", "thread:c"}
    assert [entry["key"] for entry in blocks.select_threads(DOCUMENT, {"select": "recent", "count": "2"}, ledger)] == ["a"]


def test_the_thread_ledger_does_not_collide_with_reference_keys():
    ledger = PageLedger()
    ledger.claim("reference:b")
    assert [entry["key"] for entry in blocks.select_threads(DOCUMENT, {"select": "recent", "count": "1"}, ledger)] == ["b"]


@pytest.mark.parametrize(
    ("attributes", "message"),
    [({"select": "x"}, "select to be one of recent"), ({"select": "recent", "layout": "wall"}, "layout must be one of"), ({"select": "recent", "count": "-1"}, "count must be a whole number"), ({"select": "recent", "sort": "x"}, "unknown attributes: sort")],
)
def test_check_threads_names_the_file_and_the_problem(attributes, message):
    with pytest.raises(ValueError, match=f"pages/x.md: .*{message}"):
        blocks.check_threads(attributes, "pages/x.md")


def test_a_missing_document_or_no_threads_draws_the_empty_text_or_nothing():
    settings = HomePageSettings()
    assert blocks.render_threads({"select": "recent"}, None, PageLedger(), settings) == ""
    assert 'class="home-page-empty">None yet' in blocks.render_threads({"select": "recent", "empty": "None yet"}, {"threads": []}, PageLedger(), settings)


def test_render_escapes_text_and_marks_the_layout():
    document = {"threads": [thread("a", "2026-10-01T00:00:00Z", text="<script>alert(1)</script> **bold** [link](https://x.test) done.", author={"handle": "ryan"})]}
    markup = blocks.render_threads({"select": "recent", "layout": "grid", "heading": "Talk <b>"}, document, PageLedger(), HomePageSettings())
    assert 'data-layout="grid"' in markup and "<script>" not in markup and "Talk &lt;b&gt;" in markup
    assert "bold link done." in markup and "by ryan" in markup


def test_story_anchors_link_only_to_safe_addresses():
    safe = parts.anchor_markup({"kind": "story", "url": "/fungi/", "title": "Fungi"})
    unsafe = parts.anchor_markup({"kind": "story", "url": "javascript:alert(1)", "title": "Fungi"})
    assert '<a href="/fungi/">Fungi</a>' in safe and 'data-icon="file-text"' in safe
    assert "href" not in unsafe


def test_counts_are_singular_or_plural():
    assert parts.message_count_text(1) == "1 message" and parts.message_count_text(2) == "2 messages"
