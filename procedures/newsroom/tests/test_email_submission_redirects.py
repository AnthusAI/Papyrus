"""Synthetic-only URL resolution tests; these tests have no network transport."""
from email.message import EmailMessage

import pytest

from papyrus_content.email_submission import (
    MAX_REDIRECTS,
    RedirectResolutionError,
    extract_submission,
    is_supported_beehiiv_tracking_url,
    resolve_beehiiv_tracking_url,
)

TRACKER = "https://link.mail.beehiiv.com/ss/c/opaque-route"
PUBLIC_IP = "93.184.216.34"


def message(body: str) -> bytes:
    email = EmailMessage()
    email["From"] = "editor@example.org"
    email["To"] = "submissions@example.net"
    email.set_content(body, subtype="html")
    return email.as_bytes()


def test_only_exact_https_beehiiv_click_wrappers_are_resolvable():
    assert is_supported_beehiiv_tracking_url(TRACKER)
    assert is_supported_beehiiv_tracking_url(TRACKER + "?id=opaque")
    for url in (
        "http://link.mail.beehiiv.com/ss/c/route",
        "https://user@link.mail.beehiiv.com/ss/c/route?id=opaque",
        "https://link.mail.beehiiv.com:8443/ss/c/route?id=opaque",
        "https://link.mail.beehiiv.com/unsubscribe?id=opaque",
        "https://link.mail.beehiiv.com/ss/c/unsubscribe?id=opaque",
        "https://link.mail.beehiiv.com/ss/c/manage-preferences?id=opaque",
        "https://other.example/ss/c/route?id=opaque",
        "https://link.mail.beehiiv.com/ss/c/route?action=unsubscribe",
    ):
        assert not is_supported_beehiiv_tracking_url(url)


def test_synthetic_redirect_is_normalized_and_never_auto_followed():
    calls = []
    responses = [
        {"status": 302, "headers": {"Location": "https://news.example.org/story?utm_source=mail&b=2&a=1#top"}},
        {"status": 200, "headers": {}},
    ]

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return responses.pop(0)

    def resolve_host(host, *, timeout):
        assert host in {"link.mail.beehiiv.com", "news.example.org"}
        assert timeout <= 2
        return [PUBLIC_IP]

    resolved = resolve_beehiiv_tracking_url(TRACKER + "?id=synthetic", resolve_host=resolve_host,
                                           request=request, clock=lambda: 0)
    assert resolved == "https://news.example.org/story?a=1&b=2"
    assert len(calls) == 2
    for _, options in calls:
        assert options["method"] == "HEAD"
        assert options["allow_redirects"] is False
        assert options["read_body"] is False
        assert options["trust_env"] is False
        assert options["connect_addresses"] == (PUBLIC_IP,)
        assert options["timeout"] <= 2


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.2", "169.254.169.254", "::1", "fc00::1"])
def test_nonpublic_or_link_local_dns_answers_are_rejected_before_request(address):
    requests = []
    with pytest.raises(RedirectResolutionError, match="redirect_address_not_public"):
        resolve_beehiiv_tracking_url(TRACKER, resolve_host=lambda *_args, **_kwargs: [address],
                                     request=lambda *args, **kwargs: requests.append(args), clock=lambda: 0)
    assert requests == []


def test_mixed_public_and_private_dns_answer_set_fails_closed():
    requests = []
    with pytest.raises(RedirectResolutionError, match="redirect_address_not_public"):
        resolve_beehiiv_tracking_url(TRACKER, resolve_host=lambda *_args, **_kwargs: [PUBLIC_IP, "10.0.0.1"],
                                     request=lambda *args, **kwargs: requests.append(args), clock=lambda: 0)
    assert requests == []


def test_each_redirect_host_is_resolved_again():
    resolutions = []
    requests = []

    def resolve_host(host, *, timeout):
        resolutions.append(host)
        assert timeout <= 2
        return [PUBLIC_IP]

    def request(url, **kwargs):
        requests.append(url)
        if len(requests) == 1:
            return {"status": 302, "headers": {"Location": "https://news.example.org/story"}}
        return {"status": 200, "headers": {}}

    resolved = resolve_beehiiv_tracking_url(TRACKER, resolve_host=resolve_host,
                                           request=request, clock=lambda: 0)
    assert resolutions == ["link.mail.beehiiv.com", "news.example.org"]
    assert requests == [TRACKER, "https://news.example.org/story"]
    assert resolved == "https://news.example.org/story"


def test_total_deadline_is_enforced():
    requests = []
    ticks = iter([0, 0, 0, 9])

    def request(url, **kwargs):
        requests.append(url)
        return {"status": 200, "headers": {}}

    with pytest.raises(RedirectResolutionError, match="redirect_timeout"):
        resolve_beehiiv_tracking_url(TRACKER, resolve_host=lambda *_args, **_kwargs: [PUBLIC_IP],
                                     request=request, clock=lambda: next(ticks))
    assert requests == [TRACKER]


def test_unsafe_redirect_target_is_rejected_before_following_it():
    requests = []

    def request(url, **kwargs):
        requests.append(url)
        return {"status": 302, "headers": {"Location": "https://news.example.org/unsubscribe"}}

    with pytest.raises(RedirectResolutionError, match="redirect_target_unsafe"):
        resolve_beehiiv_tracking_url(TRACKER, resolve_host=lambda *_args, **_kwargs: [PUBLIC_IP],
                                     request=request, clock=lambda: 0)
    assert len(requests) == 1


def test_scheme_downgrade_is_rejected_before_second_request():
    requests = []

    def request(url, **kwargs):
        requests.append(url)
        return {"status": 302, "headers": {"Location": "http://news.example.org/story"}}

    with pytest.raises(RedirectResolutionError, match="redirect_scheme_downgrade"):
        resolve_beehiiv_tracking_url(TRACKER, resolve_host=lambda *_args, **_kwargs: [PUBLIC_IP],
                                     request=request, clock=lambda: 0)
    assert len(requests) == 1


def test_redirect_loop_and_hop_limit_are_bounded():
    loop_requests = []

    def loop_request(url, **kwargs):
        loop_requests.append(url)
        return {"status": 302, "headers": {"Location": "https://news.example.org/story"}}

    with pytest.raises(RedirectResolutionError, match="redirect_loop"):
        resolve_beehiiv_tracking_url(TRACKER, resolve_host=lambda *_args, **_kwargs: [PUBLIC_IP],
                                     request=loop_request, clock=lambda: 0)
    assert len(loop_requests) == 2

    hop_requests = []

    def hop_request(url, **kwargs):
        hop_requests.append(url)
        index = len(hop_requests)
        return {"status": 302, "headers": {"Location": f"https://news.example.org/story/{index}"}}

    with pytest.raises(RedirectResolutionError, match="redirect_limit_exceeded"):
        resolve_beehiiv_tracking_url(TRACKER, resolve_host=lambda *_args, **_kwargs: [PUBLIC_IP],
                                     request=hop_request, clock=lambda: 0)
    assert len(hop_requests) == MAX_REDIRECTS + 1


def test_parser_uses_only_explicit_resolver_and_excludes_action_anchors_before_call():
    called = []

    def resolver(url):
        called.append(url)
        return "https://news.example.org/story?utm_campaign=one"

    raw = message(f'<a href="{TRACKER}?id=article">Read story</a>'
                  f'<a href="{TRACKER}?id=unsubscribe">Unsubscribe</a>')
    ordinary = extract_submission(raw)
    assert ordinary["links"] == [{"url": TRACKER + "?id=article", "title": "Read story",
                                   "resolutionStatus": "unresolved"}]
    assert called == []

    result = extract_submission(raw, tracking_resolver=resolver)
    assert result["links"] == [{"url": "https://news.example.org/story", "title": "Read story"}]
    assert len(called) == 1
    assert TRACKER not in repr(result)
