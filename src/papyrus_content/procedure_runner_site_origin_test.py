"""The runner gives a procedure the site's public address from its wake, as SITE_ORIGIN, and only a plain https origin."""
from papyrus_content.procedure_runner import child_environment


def request(**extra):
    return {"appsyncEndpoint": "https://example.appsync-api.us-east-1.amazonaws.com/graphql", "tenantId": "alpha", "siteBucket": "bucket", **extra}


def test_the_wakes_site_origin_becomes_site_origin():
    assert child_environment(request(siteOrigin="https://news.example"), None)["SITE_ORIGIN"] == "https://news.example"


def test_no_site_origin_on_the_wake_means_none_in_the_environment(monkeypatch):
    monkeypatch.setenv("SITE_ORIGIN", "https://inherited.example")
    assert "SITE_ORIGIN" not in child_environment(request(), None)


def test_an_origin_with_a_path_is_not_passed_on():
    assert "SITE_ORIGIN" not in child_environment(request(siteOrigin="https://news.example/evil?x=1"), None)


def test_validation_keeps_the_site_origin_and_refuses_one_with_a_path():
    import pytest

    from papyrus_content.procedure_runner import ProcedureNotRunnable, validate_request

    base = {"appsyncEndpoint": "https://abcdefghijklmnopqrstuvwxyz.appsync-api.us-east-1.amazonaws.com/graphql", "procedureKey": "announce_story",
            "wakeKey": "announce|s|s-v1|rated.5.2026-11-21T00:00:00Z", "tenantId": "alpha", "siteBucket": "bucket"}
    assert validate_request({**base, "siteOrigin": "https://news.example"})["siteOrigin"] == "https://news.example"
    assert validate_request(base)["siteOrigin"] is None
    with pytest.raises(ProcedureNotRunnable):
        validate_request({**base, "siteOrigin": "https://news.example/x"})


def test_the_runner_names_the_sites_broadcast_function_after_the_publication(monkeypatch):
    monkeypatch.setenv("X_BROADCAST_FUNCTION", "papyrus-notifications-broadcast-someone-else")
    assert child_environment(request(publicationId="machines-on-machines"), None)["X_BROADCAST_FUNCTION"] == "papyrus-notifications-broadcast-machines-on-machines"
    assert "X_BROADCAST_FUNCTION" not in child_environment(request(publicationId="Not A Site!"), None)
