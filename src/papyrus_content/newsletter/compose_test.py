from __future__ import annotations

from papyrus_content.newsletter.compose import IssueSource, archive_url, render
from papyrus_content.newsletter.handler import Settings

ROUNDUP = {"id": "weekly", "name": "Weekly roundup", "kind": "roundup", "archivePath": "/roundup/"}
OTHER = {"id": "digest", "name": "Digest", "kind": "roundup", "archivePath": "/digest/"}
ALERTS = {"id": "alerts", "name": "Alerts", "kind": "alert"}
THEME = {"accent": "#111111", "text": "#111111", "background": "#ffffff"}
SOURCE = IssueSource(subject="Hello", markus="Body.", preheader="")


def settings(lists, base_path: str = "") -> Settings:
    return Settings(
        site_id="s", site_origin="https://shipped.example.com", sending_domain="d", from_address="a@d", from_name="Shipped",
        configuration_set="c", lists=tuple(lists), theme=THEME, base_path=base_path,
    )


def test_a_roundup_list_links_its_own_archive():
    assert archive_url(settings([ROUNDUP, OTHER]), OTHER) == "https://shipped.example.com/digest/"


def test_an_alert_list_falls_back_to_the_first_roundup_archive():
    assert archive_url(settings([ALERTS, ROUNDUP, OTHER]), ALERTS) == "https://shipped.example.com/roundup/"


def test_no_archive_anywhere_means_no_link():
    assert archive_url(settings([ALERTS]), ALERTS) is None
    mail = render(settings([ALERTS]), "Alerts", SOURCE, "1 Example Way", entry=ALERTS)
    assert "All issues" not in mail.html and "All issues" not in mail.text


def test_the_archive_link_respects_the_base_path():
    assert archive_url(settings([ROUNDUP], base_path="posts"), ROUNDUP) == "https://shipped.example.com/posts/roundup/"
    mail = render(settings([ROUNDUP], base_path="posts"), "Weekly roundup", SOURCE, "1 Example Way", entry=ROUNDUP)
    assert 'href="https://shipped.example.com/posts/roundup/"' in mail.html
    assert "All issues: https://shipped.example.com/posts/roundup/" in mail.text
