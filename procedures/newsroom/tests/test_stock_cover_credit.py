"""A stock cover image's credit shows under the picture on the article page and nowhere on a card or index page (PPY-c3f1e0; Ryan, 2026-11-05).

The cover is front matter ``image`` (the card and share picture) plus ``coverImage`` (the structured record the newsroom writes) and a first body
figure ``::image{ credit="..." }``. Cards read ``image`` only.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from papyrus_content.markus_renderer.images import ImageBuilder, ImagePipeline, ImageRequest
from procedures.newsroom.tests.standard_frontend_content_support import cms_site, item, settings

CREDIT = "Image: Ana Example, CC BY 4.0, via Wikimedia Commons"
COVER = {
    "image": "/assets/harbour/harbour.jpg",
    "coverImage": {
        "source": "wikimedia-commons", "sourceLabel": "Wikimedia Commons", "sourceUrl": "https://commons.wikimedia.org/wiki/File:Harbour.jpg",
        "title": "Harbour", "creator": "Ana Example", "licence": "CC BY 4.0", "licenceUrl": "https://creativecommons.org/licenses/by/4.0",
        "srcPath": "assets/harbour/harbour.jpg", "pickedAt": "2026-11-05T12:00:00.000Z", "pickedBy": "editor-a",
    },
}


def test_the_article_page_figure_carries_the_credit_directly_under_the_picture():
    with tempfile.TemporaryDirectory() as tmp:
        content = Path(tmp) / "content"
        (content / "assets" / "harbour").mkdir(parents=True)
        Image.new("RGB", (1600, 900), (30, 90, 160)).save(content / "assets" / "harbour" / "harbour.jpg")
        builder = ImageBuilder(ImagePipeline(), content_dir=content, out_dir=Path(tmp) / "dist")
        html = builder.render(ImageRequest(src="assets/harbour/harbour.jpg", alt="A harbour", credit=CREDIT))
    assert f'<figcaption><span class="papyrus-image-credit">{CREDIT}</span></figcaption></figure>' in html
    assert html.index("<img") < html.index("papyrus-image-credit")


def test_no_card_or_index_page_carries_the_credit_or_the_record():
    site = cms_site(
        settings(urls={"sections": {"posts": {"base": "posts"}}}),
        [item("harbour", date="2026-02-01", **COVER), item("other", date="2026-01-01")],
    )
    try:
        tree = site.tree
        assert any(key.endswith(".html") for key in tree)
        listing = site.text("index.html")
        assert 'src="/assets/harbour/harbour.jpg"' in listing, "the card shows the cover picture"
        article_key = next(key for key in tree if key.endswith("harbour/index.html") or key.endswith("harbour.html"))
        forbidden = ("Ana Example", "CC BY 4.0", "papyrus-image-credit", "Wikimedia", "creativecommons.org", "coverImage", "pickedBy")
        for key, data in tree.items():
            if key == article_key:
                continue
            text = data.decode("utf-8", "ignore")
            for word in forbidden:
                assert word not in text, f"{key} carries {word!r}"
    finally:
        site.cleanup()
