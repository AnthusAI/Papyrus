"""A renamed page's redirect points at the page's public path: ``/x`` when ``urls.style`` is clean (PPY-7954f8)."""

from __future__ import annotations

import unittest

from papyrus_content.projection.engine import _moved_redirects
from papyrus_content.projection.item_state import ItemState
from papyrus_content.projection.projector import MarkusProjectorSettings, read_static_files
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.hooks import Hooks
from papyrus_content.projection.standard.projector import StandardMarkusProjector

SITE = {"name": "Example", "productionUrl": "https://example.org", "description": "d"}


def projector(style: str) -> StandardMarkusProjector:
    return StandardMarkusProjector(
        MarkusProjectorSettings(theme=None), read_static_files(None, None),
        standard_settings_from_mapping({"site": SITE, "urls": {"style": style}}), hooks=Hooks(), environment=None,
    )


class MovedRedirectsCleanUrls(unittest.TestCase):
    def moved(self, style: str) -> dict[str, str]:
        state = ItemState(summary=None, page_keys=("docs/new.html",), former_page_keys=("docs/old.html",))
        return _moved_redirects(projector(style), state, set())

    def test_clean_style_targets_the_clean_path(self) -> None:
        self.assertEqual(self.moved("clean"), {"/docs/old": "/docs/new", "/docs/old.html": "/docs/new"})

    def test_other_styles_keep_the_html_path(self) -> None:
        self.assertEqual(self.moved("directory"), {"/docs/old.html": "/docs/new.html"})


if __name__ == "__main__":
    unittest.main()
