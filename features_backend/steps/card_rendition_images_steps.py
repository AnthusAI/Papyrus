"""Cards show the rendition the article page shows (features_backend/card-rendition-images.feature)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from procedures.newsroom.tests.based_images_support import CHART, CHART_DARK, FOLDER, BasedImageSite  # noqa: E402

IMG_SRC = re.compile(r'<img\b[^>]*?\bsrc="([^"]+)"')
ORIGINAL = re.compile(r'<img\b[^>]*?\bsrc="[^"]*/' + re.escape(FOLDER) + r'/chart(?:\.dark)?\.png"')


def restored(context, base_path: str | None, card: str, dark: str | None) -> None:
    site = BasedImageSite(base_path)
    context.add_cleanup(site.cleanup)
    context.add_cleanup(site.release_function)
    front = f"image: {card}\n" + (f"imageDark: {dark}\n" if dark else "")
    story = (site.content / "hello.md").read_text(encoding="utf-8").replace("description: A first article.\n", f"description: A first article.\n{front}", 1)
    (site.content / "hello.md").write_text(story, encoding="utf-8")
    context.images_site = site


def stored(name: str) -> str:
    return f"{FOLDER}/{name}"


@given('a site with images whose story "hello" names the card picture "{card}" and the Night picture "{dark}"')
def site_with_pair(context, card: str, dark: str) -> None:
    restored(context, None, stored(card) if "/" not in card else card, stored(dark))


@given('a site under the base path "{base}" with images whose story "hello" names the card picture "{card}"')
def based_site_with_card(context, base: str, card: str) -> None:
    restored(context, base, stored(card), None)


@given('a site with images whose story "hello" names the card picture "{card}"')
def site_with_card(context, card: str) -> None:
    restored(context, None, card, None)


@given("the story's pictures are uploaded")
def pictures_uploaded(context) -> None:
    context.images_site.configure_function()
    context.images_site.upload_all()


@given("the site holds no original files")
def no_originals(context) -> None:
    site = context.images_site
    prefix = (site.base_path or "").strip("/")
    for source in site.pictures:
        original = site.site_store / prefix / source
        assert original.is_file(), original
        original.unlink()


@when("the cards are rendered from the site store")
def render(context) -> None:
    context.images_site.render_from_store()
    assert context.images_site.error is None, context.images_site.error


def front_page(context) -> str:
    site = context.images_site
    root = (site.base_path or "").strip("/")
    return (site.cloud_out / root / "index.html").read_text(encoding="utf-8")


def article_page(context) -> str:
    site = context.images_site
    root = (site.base_path or "").strip("/")
    return (site.cloud_out / root / "hello" / "index.html").read_text(encoding="utf-8")


def card_sources(context) -> list[str]:
    card = re.search(r'<article class="markus-card">(.*?)</article>', front_page(context), re.S)
    assert card is not None, "the front page has no card"
    return IMG_SRC.findall(card.group(1))


def tail(address: str) -> str:
    return address[address.index("assets/responsive/"):]


def picture_of_article(context, dark: bool) -> str:
    sources = [tail(src) for src in IMG_SRC.findall(article_page(context)) if "/responsive/" in src]
    return next(src for src in sources if (".dark-" in src) == dark)


@then("the card on the front page shows the Day picture of the article page")
def card_day(context) -> None:
    day = [src for src in card_sources(context) if ".dark" not in src]
    assert day and tail(day[0]) == picture_of_article(context, False), (card_sources(context), picture_of_article(context, False))


@then("the card on the front page shows the Night picture of the article page")
def card_night(context) -> None:
    night = [src for src in card_sources(context) if ".dark" in src]
    assert night and tail(night[0]) == picture_of_article(context, True), (card_sources(context), picture_of_article(context, True))


@then('no card names the original file "chart.png"')
def no_original(context) -> None:
    assert not ORIGINAL.search(front_page(context)), front_page(context)


@then("that picture is a file of the site store")
def is_stored(context) -> None:
    site = context.images_site
    day = [src for src in card_sources(context) if ".dark" not in src][0]
    assert (site.site_store / (site.base_path or "").strip("/") / tail(day)).is_file(), day


@then('the card on the front page shows an address starting with "{prefix}"')
def card_prefix(context, prefix: str) -> None:
    assert card_sources(context)[0].startswith(prefix), card_sources(context)


@then('the card on the front page shows "{address}"')
def card_address(context, address: str) -> None:
    assert card_sources(context) == [address], card_sources(context)


@then('the social image of the story page names "chart.png" and not a rendition')
def social_image(context) -> None:
    page = article_page(context)
    images = re.findall(r'<meta (?:property|name)="(?:og|twitter):image" content="([^"]+)"', page)
    assert images, "the story page has no social image"
    assert all(image.endswith(CHART.split("/", 1)[1]) or image.endswith(CHART) for image in images), images
    assert not any("/responsive/" in image for image in images), images
