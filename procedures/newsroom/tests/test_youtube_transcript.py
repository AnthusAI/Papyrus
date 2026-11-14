"""YouTube links: which addresses are videos, and what the cloud capture keeps of one (never a transcript). No network."""

from __future__ import annotations

import builtins
import sys

import pytest

from curation_support import Explorer, page
from papyrus_content import reference_capture, youtube_transcript

VIDEO = "dQw4w9WgXcQ"
WATCH = f"https://www.youtube.com/watch?v={VIDEO}"
WATCH_PAGE = ("<html><head><title>Talk - YouTube</title><meta property='og:title' content='A talk on feeds'>"
              "<meta property='og:description' content='The speaker explains steerable feeds.'></head><body></body></html>")


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VIDEO}&t=42s", f"https://m.youtube.com/watch?v={VIDEO}", f"https://youtu.be/{VIDEO}?si=abc",
    f"https://www.youtube.com/shorts/{VIDEO}", f"https://www.youtube-nocookie.com/embed/{VIDEO}", f"https://youtube.com/live/{VIDEO}",
])
def test_video_links_yield_the_video_id(url):
    assert youtube_transcript.video_id(url) == VIDEO


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/", "https://www.youtube.com/@channel", "https://www.youtube.com/watch?v=short", "https://example.org/watch?v=" + VIDEO,
    "https://notyoutube.com/watch?v=" + VIDEO,
])
def test_other_addresses_are_not_videos(url):
    assert youtube_transcript.video_id(url) is None


def capture(html=WATCH_PAGE, explorer_page=None):
    return reference_capture.capture_source(WATCH, explorer=Explorer({WATCH: page(html) if explorer_page is None else explorer_page}))


def test_capture_keeps_the_page_text_and_says_the_transcript_waits_for_the_worker():
    captured = capture()
    assert captured.ok and captured.text == "The speaker explains steerable feeds."
    assert (captured.text_via, captured.text_reason) == ("youtube_description", "awaiting_transcript")
    assert captured.page["title"] == "A talk on feeds"


def test_a_page_with_no_text_falls_back_to_its_title():
    captured = capture("<html><head><title>A talk</title></head></html>")
    assert captured.ok and captured.text == "A talk" and captured.text_reason == "awaiting_transcript"


def test_a_page_that_cannot_be_read_stays_failed_with_its_own_reason_and_the_same_mark():
    captured = reference_capture.capture_source(WATCH, explorer=Explorer({WATCH: "blocked"}))
    assert not captured.ok and captured.failure == "blocked" and captured.text_reason == "awaiting_transcript"


def test_capture_never_asks_youtube_for_a_transcript_and_does_not_need_the_library(monkeypatch):
    """The cloud capture cannot import the transcript library at all: a Lambda without it captures a video the same way."""
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.split(".")[0] == "youtube_transcript_api":
            raise AssertionError("the capture must not import the transcript library")
        return real_import(name, *args, **kwargs)

    for module in [name for name in sys.modules if name.split(".")[0] == "youtube_transcript_api"]:
        monkeypatch.delitem(sys.modules, module)
    monkeypatch.setattr(builtins, "__import__", refuse)
    assert capture().text_reason == "awaiting_transcript"
    assert not hasattr(sys.modules["papyrus_content.youtube_transcript"], "fetch_transcript")


def test_other_sources_carry_no_transcript_mark():
    captured = reference_capture.capture_source("https://news.example.org/r1", explorer=Explorer({"https://news.example.org/r1": page(WATCH_PAGE)}))
    assert captured.text_via is None and captured.text_reason is None
