"""Newsroom tests never touch the network: a newly created Reference tries to fetch its link preview (``attach_preview``)."""

import pytest


@pytest.fixture(autouse=True)
def _no_preview_network(monkeypatch):
    from papyrus_content import reference_images
    from papyrus_content.link_exploration import Exploration

    monkeypatch.setattr(reference_images, "explore", lambda *args, **kwargs: Exploration(False, None, failure="offline"))
