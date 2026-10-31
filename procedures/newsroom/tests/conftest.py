"""Newsroom tests never touch the network: a newly created Reference tries to fetch its link preview (``attach_preview``)."""

import pytest


@pytest.fixture(autouse=True)
def _no_preview_network(monkeypatch):
    from papyrus_content import reference_images
    from papyrus_content.link_exploration import Exploration

    monkeypatch.setattr(reference_images, "explore", lambda *args, **kwargs: Exploration(False, None, failure="offline"))


@pytest.fixture(autouse=True)
def _site_without_enrollment_for_local_login(monkeypatch):
    """A local login asks its site for an enrollment challenge; tests answer as a site that has not switched it on."""
    from papyrus_content import cli_user_auth

    monkeypatch.setattr(cli_user_auth, "site_enrolls", lambda config, **kwargs: False)
