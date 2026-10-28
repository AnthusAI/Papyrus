"""YouTube links: which addresses are videos, how transcript failures are typed, and what capture keeps. No network."""

from __future__ import annotations

import json
from unittest import mock

import pytest
from youtube_transcript_api import IpBlocked, NoTranscriptFound, RequestBlocked, TranscriptsDisabled, VideoUnavailable

from curation_support import Explorer, page
from papyrus_content import reference_capture, youtube_transcript

VIDEO = "dQw4w9WgXcQ"
WATCH = f"https://www.youtube.com/watch?v={VIDEO}"
WATCH_PAGE = ("<html><head><title>Talk - YouTube</title><meta property='og:title' content='A talk on feeds'>"
              "<meta property='og:description' content='The speaker explains steerable feeds.'></head><body></body></html>")


class Track:
    def __init__(self, words):
        self.words = words

    def fetch(self):
        return [mock.Mock(text=word) for word in self.words]


class Tracks:
    def __init__(self, english=None, other=None):
        self.english, self.other = english, other

    def find_transcript(self, languages):
        if self.english is None:
            raise NoTranscriptFound(VIDEO, languages, self)
        return self.english

    def __iter__(self):
        return iter([self.other] if self.other else [])


def api(result):
    def factory():
        listing = mock.Mock()
        if isinstance(result, Exception):
            listing.side_effect = result
        else:
            listing.return_value = result
        return mock.Mock(list=listing)
    return factory


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


def test_the_english_track_is_joined_into_one_paragraph(capsys):
    text, reason = youtube_transcript.fetch_transcript(VIDEO, api_factory=api(Tracks(english=Track(["Hello  there", "and welcome\n"]))))
    assert (text, reason) == ("Hello there and welcome", None)
    assert json.loads(capsys.readouterr().out) == {"youtubeTranscript": "captured", "videoId": VIDEO, "reason": None, "characters": 23}


def test_without_an_english_track_the_first_track_is_used():
    text, _ = youtube_transcript.fetch_transcript(VIDEO, api_factory=api(Tracks(other=Track(["Bonjour"]))))
    assert text == "Bonjour"


@pytest.mark.parametrize("error, reason", [
    (RequestBlocked(VIDEO), "blocked"), (IpBlocked(VIDEO), "blocked"), (TranscriptsDisabled(VIDEO), "no_transcript"),
    (NoTranscriptFound(VIDEO, ["en"], None), "no_transcript"), (VideoUnavailable(VIDEO), "unavailable"), (RuntimeError("boom"), "unreadable"),
])
def test_failures_are_typed_and_logged_without_raising(error, reason, capsys):
    assert youtube_transcript.fetch_transcript(VIDEO, api_factory=api(error)) == (None, reason)
    assert json.loads(capsys.readouterr().out) == {"youtubeTranscript": "fallback", "videoId": VIDEO, "reason": reason, "characters": 0}


def test_an_empty_transcript_counts_as_no_transcript():
    assert youtube_transcript.fetch_transcript(VIDEO, api_factory=api(Tracks(english=Track([" "])))) == (None, "no_transcript")


def capture(fetched):
    with mock.patch.object(youtube_transcript, "fetch_transcript", return_value=fetched):
        return reference_capture.capture_source(WATCH, explorer=Explorer({WATCH: page(WATCH_PAGE)}))


def test_capture_uses_the_transcript_as_the_text():
    captured = capture(("We talk about feeds. Then we steer them.", None))
    assert captured.ok and captured.text == "We talk about feeds. Then we steer them." and captured.source_kind == "transcript"
    assert (captured.text_via, captured.text_reason) == ("youtube_transcript", None)
    assert captured.page["title"] == "A talk on feeds" and captured.signals["wordCount"] == 8


def test_capture_falls_back_to_the_page_text_with_the_reason():
    captured = capture((None, "blocked"))
    assert captured.ok and captured.text == "The speaker explains steerable feeds."
    assert (captured.text_via, captured.text_reason) == ("youtube_description", "blocked")


def test_a_page_with_no_text_falls_back_to_its_title():
    with mock.patch.object(youtube_transcript, "fetch_transcript", return_value=(None, "no_transcript")):
        captured = reference_capture.capture_source(WATCH, explorer=Explorer({WATCH: page("<html><head><title>A talk</title></head></html>")}))
    assert captured.ok and captured.text == "A talk" and captured.text_reason == "no_transcript"


def test_a_page_that_cannot_be_read_still_yields_the_transcript():
    with mock.patch.object(youtube_transcript, "fetch_transcript", return_value=("Spoken words.", None)):
        captured = reference_capture.capture_source(WATCH, explorer=Explorer({WATCH: "blocked"}))
    assert captured.ok and captured.text == "Spoken words."


def test_a_page_that_cannot_be_read_and_no_transcript_stays_failed_with_the_reason():
    with mock.patch.object(youtube_transcript, "fetch_transcript", return_value=(None, "blocked")):
        captured = reference_capture.capture_source(WATCH, explorer=Explorer({WATCH: "blocked"}))
    assert not captured.ok and captured.failure == "blocked" and captured.text_reason == "blocked"


def test_other_sources_never_ask_for_a_transcript():
    with mock.patch.object(youtube_transcript, "fetch_transcript") as fetch:
        captured = reference_capture.capture_source("https://news.example.org/r1", explorer=Explorer({"https://news.example.org/r1": page(WATCH_PAGE)}))
    fetch.assert_not_called()
    assert captured.text_via is None
