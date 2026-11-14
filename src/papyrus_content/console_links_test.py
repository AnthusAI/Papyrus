import pytest

from papyrus_content import console_links as links
from papyrus_content.console_links import ConsoleLinkError

BASE = "https://newsroom.news.example.test/newsroom"


def test_each_kind_has_one_route():
    assert links.story_version_url(BASE, "item-v2") == f"{BASE}/articles/item-v2"
    assert links.story_board_url(BASE, "item") == f"{BASE}/articles?open=contentItem%3Aitem"
    assert links.reference_url(BASE, "reference-a") == f"{BASE}/references/reference-a"
    assert links.concept_url(BASE, "semantic-node-x") == f"{BASE}/concepts?node=semantic-node-x"
    assert links.assignment_url(BASE, "a-1") == f"{BASE}/assignments/a-1"
    assert links.review_url(BASE, "rr-1") == f"{BASE}/needs-me/rr-1"


def test_ids_are_encoded_and_blank_ids_refused():
    assert links.reference_url(BASE, "a/b?c#d") == f"{BASE}/references/a%2Fb%3Fc%23d"
    with pytest.raises(ConsoleLinkError):
        links.reference_url(BASE, "  ")


@pytest.mark.parametrize("given,expected", [
    ("https://Newsroom.Example.test/", "https://newsroom.example.test"),
    ("https://newsroom.example.test/newsroom/", "https://newsroom.example.test/newsroom"),
])
def test_normalize(given, expected):
    assert links.normalize_console_url(given) == expected


@pytest.mark.parametrize("bad", ["", "http://a.test", "a.test", "https://u@a.test", "https://a.test/?q=1", "https://a.test/#x", "https://a b.test"])
def test_normalize_refuses(bad):
    with pytest.raises(ConsoleLinkError):
        links.normalize_console_url(bad)


def test_order_flag_then_environment_then_site(monkeypatch):
    monkeypatch.delenv(links.CONSOLE_URL_VARIABLE, raising=False)
    site = lambda name: "https://site.example.test/newsroom"   # noqa: E731
    assert links.resolve_console_url(published=site) == "https://site.example.test/newsroom"
    monkeypatch.setenv(links.CONSOLE_URL_VARIABLE, "https://env.example.test")
    assert links.resolve_console_url(published=site) == "https://env.example.test"
    assert links.resolve_console_url("https://flag.example.test", published=site) == "https://flag.example.test"


def test_unknown_console_is_an_error_not_a_guess(monkeypatch):
    monkeypatch.delenv(links.CONSOLE_URL_VARIABLE, raising=False)
    with pytest.raises(ConsoleLinkError, match="never guessed|unknown"):
        links.resolve_console_url(published=lambda name: None)
    def broken(name):
        raise RuntimeError("no site")
    with pytest.raises(ConsoleLinkError):
        links.resolve_console_url(published=broken)


def test_story_links_without_a_version_only_has_the_drawer():
    kinds = [link.kind for link in links.story_links(BASE, "item")]
    assert kinds == ["story-board", "checklist"]
