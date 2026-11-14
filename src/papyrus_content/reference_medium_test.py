"""The medium rule: exact URL shapes, certain only (src/papyrus_content/reference_medium.py)."""
from __future__ import annotations

import pytest

from .reference_medium import EVIDENCE_AGGREGATION, MEDIUM_VIDEO, PLATFORMS, classify_address, medium_fields, medium_of, stale_medium_fields

ID = "dQw4w9WgXcQ"
PLAYLIST = "PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom"
LOOM = "0123456789abcdef0123456789abcdef"

VIDEOS = [
    (f"https://www.youtube.com/watch?v={ID}", "youtube"),
    (f"https://youtube.com/watch?v={ID}&t=42s", "youtube"),
    (f"https://m.youtube.com/watch?v={ID}", "youtube"),
    (f"https://youtu.be/{ID}", "youtube"),
    (f"https://youtu.be/{ID}?si=abc&t=3", "youtube"),
    (f"https://www.youtube.com/shorts/{ID}", "youtube"),
    (f"https://www.youtube.com/live/{ID}", "youtube"),
    (f"https://www.youtube.com/embed/{ID}", "youtube"),
    (f"https://www.youtube-nocookie.com/embed/{ID}", "youtube"),
    (f"HTTPS://WWW.YOUTUBE.COM/watch?v={ID}", "youtube"),
    ("https://vimeo.com/123456789", "vimeo"),
    ("https://vimeo.com/123456789/abcdef1234", "vimeo"),
    ("https://player.vimeo.com/video/123456789", "vimeo"),
    ("https://vimeo.com/channels/staffpicks/123456789", "vimeo"),
    ("https://vimeo.com/groups/motion/videos/123456789", "vimeo"),
    ("https://vimeo.com/showcase/7654321/video/123456789", "vimeo"),
    ("https://www.dailymotion.com/video/x8abcde", "dailymotion"),
    ("https://www.dailymotion.com/embed/video/x8abcde", "dailymotion"),
    ("https://dai.ly/x8abcde", "dailymotion"),
    (f"https://www.loom.com/share/{LOOM}", "loom"),
    (f"https://www.loom.com/embed/{LOOM}", "loom"),
    ("https://acme.wistia.com/medias/abcde12345", "wistia"),
    ("https://fast.wistia.net/embed/iframe/abcde12345", "wistia"),
    ("https://www.ted.com/talks/ken_robinson_do_schools_kill_creativity", "ted"),
    ("https://www.twitch.tv/videos/123456789", "twitch"),
    ("https://clips.twitch.tv/FunnyClipSlug-abc123", "twitch"),
    ("https://www.twitch.tv/somechannel/clip/FunnyClipSlug-abc123", "twitch"),
]

NOT_VIDEOS = [
    "https://www.youtube.com/",
    "https://www.youtube.com/about/",
    "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv",
    "https://www.youtube.com/c/SomeChannel/videos",
    "https://www.youtube.com/results?search_query=cats",
    "https://www.youtube.com/feed/subscriptions",
    "https://www.youtube.com/watch",
    "https://www.youtube.com/watch?v=short",
    f"https://www.youtube.com/watch?list={PLAYLIST}",
    f"https://music.youtube.com/watch?v={ID}",
    f"https://notyoutube.com/watch?v={ID}",
    f"https://youtube.com.evil.example/watch?v={ID}",
    f"https://example.org/watch?v={ID}",
    f"https://example.org/?next=https://youtu.be/{ID}",
    "https://vimeo.com/",
    "https://vimeo.com/categories/animation",
    "https://vimeo.com/staffpicks",
    "https://vimeo.com/ondemand/some-film",
    "https://vimeo.com/channels/staffpicks/videos",
    "https://vimeo.com/123456789/review/abc/def",
    "https://www.dailymotion.com/someuser",
    "https://www.dailymotion.com/video/",
    "https://www.loom.com/",
    "https://www.loom.com/share/not-a-loom-id",
    "https://www.ted.com/talks",
    "https://www.ted.com/speakers/ken_robinson",
    "https://www.ted.com/talks/some_talk/transcript",
    "https://www.twitch.tv/somechannel",
    "https://www.twitch.tv/directory",
    "https://example.org/paper.pdf",
    "ftp://youtu.be/dQw4w9WgXcQ",
    "not a url",
    "",
    None,
    42,
]

PLAYLISTS = [
    (f"https://www.youtube.com/playlist?list={PLAYLIST}", "youtube"),
    (f"https://youtube.com/playlist?list={PLAYLIST}&si=xyz", "youtube"),
    (f"https://www.youtube.com/embed/videoseries?list={PLAYLIST}", "youtube"),
    ("https://vimeo.com/showcase/7654321", "vimeo"),
    ("https://vimeo.com/album/7654321", "vimeo"),
    ("https://vimeo.com/channels/staffpicks", "vimeo"),
    ("https://www.dailymotion.com/playlist/x6abcd", "dailymotion"),
    ("https://www.ted.com/playlists/171/the_most_popular_talks_of_all", "ted"),
    ("https://www.twitch.tv/collections/abcDEF123", "twitch"),
]


@pytest.mark.parametrize(("address", "platform"), VIDEOS)
def test_a_video_address_is_a_video(address, platform):
    found = classify_address(address)
    assert found.medium == MEDIUM_VIDEO and found.platform == platform
    assert found.evidence_level is None and found.playlist_url is None
    assert medium_of(address) == "video"


@pytest.mark.parametrize("address", NOT_VIDEOS)
def test_anything_not_certainly_a_video_has_no_medium_and_is_not_an_aggregation(address):
    found = classify_address(address)
    assert found.medium is None and found.evidence_level is None and found.playlist_url is None


@pytest.mark.parametrize(("address", "platform"), PLAYLISTS)
def test_a_playlist_or_collection_is_an_aggregation_and_not_a_video(address, platform):
    found = classify_address(address)
    assert found.medium is None and found.evidence_level == EVIDENCE_AGGREGATION and found.platform == platform
    assert medium_of(address) is None


def test_every_platform_has_a_video_example():
    assert {platform for _, platform in VIDEOS} == set(PLATFORMS)


def test_a_watch_address_with_a_list_is_the_video_and_names_its_playlist_separately():
    found = classify_address(f"https://www.youtube.com/watch?v={ID}&list={PLAYLIST}&ab_channel=Someone")
    assert found.medium == MEDIUM_VIDEO and found.evidence_level is None
    assert found.playlist_url == f"https://www.youtube.com/playlist?list={PLAYLIST}"
    short = classify_address(f"https://youtu.be/{ID}?list={PLAYLIST}")
    assert short.medium == MEDIUM_VIDEO and short.playlist_url == f"https://www.youtube.com/playlist?list={PLAYLIST}"


def test_a_list_parameter_that_is_not_a_playlist_id_is_ignored():
    assert classify_address(f"https://www.youtube.com/watch?v={ID}&list=x").playlist_url is None
    assert classify_address("https://www.youtube.com/playlist?list=x").evidence_level is None


def test_medium_fields_name_only_what_the_address_says():
    assert medium_fields({"sourceUri": "https://example.org/paper"}) == {}
    assert medium_fields({}) == {}
    assert medium_fields({"sourceUri": f"https://youtu.be/{ID}"}) == {"medium": "video"}
    assert medium_fields({"sourceUri": f"https://youtu.be/{ID}?list={PLAYLIST}"}) == {
        "medium": "video", "playlistUrl": f"https://www.youtube.com/playlist?list={PLAYLIST}"}
    assert medium_fields({"sourceUri": f"https://www.youtube.com/playlist?list={PLAYLIST}"}) == {"evidenceLevel": "aggregation"}


def test_a_rule_never_replaces_an_evidence_level_somebody_else_wrote():
    playlist = {"sourceUri": f"https://www.youtube.com/playlist?list={PLAYLIST}", "evidenceLevel": "secondary"}
    assert medium_fields(playlist) == {}
    assert stale_medium_fields(playlist) == {}


def test_the_stale_check_names_a_wrong_or_missing_field_and_clears_one_the_address_no_longer_supports():
    video = {"sourceUri": f"https://youtu.be/{ID}"}
    assert stale_medium_fields(video) == {"medium": "video"}
    assert stale_medium_fields({**video, "medium": "video"}) == {}
    assert stale_medium_fields({"sourceUri": "https://example.org/a", "medium": "video", "playlistUrl": "https://example.org/p"}) == {"medium": None, "playlistUrl": None}
    assert stale_medium_fields({"sourceUri": "https://example.org/a"}) == {}


# --- the index reader ------------------------------------------------------------------------------------------------------------------------


def test_the_medium_index_is_registered_and_read_newest_first_by_partition():
    from . import graphql_authoring as g
    from .reference_medium import iterate_references_by_medium, medium_partition

    definition = g.INDEX_DEFINITIONS["referencesByMediumFeedAndArrival"]
    assert definition["field"] == "listReferencesByMediumFeedAndArrival" and definition["partitionKey"] == "mediumFeedKey"
    for field in ("medium", "evidenceLevel", "playlistUrl", "mediumFeedKey"):
        assert field in g.REFERENCE_FIELDS.split() and field in g.NEWER_REFERENCE_FIELDS   # a site without the schema is read without them
    assert medium_partition("knowledge-corpus-site") == "knowledge-corpus-site#video#accepted"

    asked = []

    class Client(g.PapyrusGraphQLAuthoringClient):
        def __init__(self):
            self.tenant_id = None

        def graphql(self, query, variables=None):
            asked.append((query, variables))
            token = variables["nextToken"]
            return {"listReferencesByMediumFeedAndArrival": {"items": [{"id": "a"}, None] if token is None else [{"id": "b"}], "nextToken": "next" if token is None else None}}

    rows = list(iterate_references_by_medium(Client(), "knowledge-corpus-site"))
    assert [row["id"] for row in rows] == ["a", "b"]
    assert all("sortDirection: DESC" in query for query, _ in asked)
    assert {variables["mediumFeedKey"] for _, variables in asked} == {"knowledge-corpus-site#video#accepted"}


def test_an_older_site_without_the_new_fields_is_read_without_them():
    from . import graphql_authoring as g

    stripped = g._NEWER_FIELD_SELECTION.sub("", "id medium evidenceLevel playlistUrl mediumFeedKey captureState title")
    assert "medium" not in stripped and "playlistUrl" not in stripped and "evidenceLevel" not in stripped and "title" in stripped


def test_a_write_naming_the_medium_fields_to_a_site_that_lacks_them_is_sent_again_without_them():
    from . import graphql_authoring as g

    sent = []

    class Client(g.PapyrusGraphQLAuthoringClient):
        def __init__(self):
            self.tenant_id = None
            self._schema_lacks_newer_reference_fields = False
            self._schema_lacks_medium_fields = False

        def _send_graphql(self, query, variables=None):
            sent.append(variables)
            if variables and "medium" in variables["input"]:
                raise g.GraphQLRequestError("The variables input contains a field name 'medium' that is not defined for input object type 'CreateReferenceInput'")
            return {"createReference": {"id": "r"}}

    client = Client()
    client.graphql("mutation { createReference }", {"input": {"id": "r", "title": "T", "medium": "video", "mediumFeedKey": "c#video#pending"}})
    assert sent == [{"input": {"id": "r", "title": "T", "medium": "video", "mediumFeedKey": "c#video#pending"}}, {"input": {"id": "r", "title": "T"}}]
    client.graphql("mutation { updateReference }", {"input": {"id": "r", "mediumFeedKey": "c#video#accepted", "curationStatus": "accepted"}})
    assert sent[-1] == {"input": {"id": "r", "curationStatus": "accepted"}}, "later writes are not sent twice"
    assert len(sent) == 3
