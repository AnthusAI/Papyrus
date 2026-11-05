from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.standard import components  # noqa: E402
from procedures.newsroom.tests.standard_frontend_content_support import cms_site, item, settings  # noqa: E402

CSS = Path(components.__file__).parent / "assets" / "markus-components.css"
SOCIAL_IMAGE = re.compile(r"<meta[^>]*(?:og|twitter):image[^>]*>")


@given('a Story whose figure has the Day picture "{day}" and the Night picture "{night}"')
def story_with_pair(context, day: str, night: str) -> None:
    context.front = {"image": day, "imageDark": night}


@given('a Story whose figure has only the Day picture "{day}"')
def story_day_only(context, day: str) -> None:
    context.front = {"image": day}


@when("the listing page is projected")
def project_listing(context) -> None:
    context.site = cms_site(settings(urls={"sections": {"posts": {"base": "posts"}}}), [item("a", date="2026-02-01", **context.front)])
    context.add_cleanup(context.site.cleanup)
    context.page = context.site.text("index.html")


@then('the card has a Day picture "{day}" and a Night picture "{night}"')
def card_has_pair(context, day: str, night: str) -> None:
    assert f'<span class="markus-card-image-day"><img class="markus-card-image" src="{day}"' in context.page
    assert f'<span class="markus-card-image-night"><img class="markus-card-image" src="{night}"' in context.page


@then('the card has the single picture "{day}" and no Night picture')
def card_single(context, day: str) -> None:
    assert f'<img class="markus-card-image" src="{day}" alt="" loading="lazy">' in context.page
    assert "markus-card-image-night" not in context.page


@then("no social image tag, feed or data file names the Night picture")
def no_night_in_social(context) -> None:
    for key, data in context.site.tree.items():
        text = data.decode("utf-8", "ignore")
        if key.endswith(".html"):
            assert "fig.dark.png" not in "".join(SOCIAL_IMAGE.findall(text)), key
        elif key.endswith((".xml", ".json")):
            assert "fig.dark.png" not in text, key


@when("the shared components stylesheet is read")
def read_stylesheet(context) -> None:
    context.css = CSS.read_text(encoding="utf-8")


@then("the Night picture shows when the system is dark unless the reader picked Light by hand")
def system_dark(context) -> None:
    assert "@media (prefers-color-scheme: dark)" in context.css
    assert ":root:not([data-theme=light]):not(.light):not(.light-theme) .markus-card-image-night { display: contents; }" in context.css


@then("the Night picture shows when the reader picked Dark by hand, whatever the system says")
def hand_dark(context) -> None:
    for selector in (":root[data-theme=dark]", ":root.dark", ":root.dark-theme"):
        assert f"{selector} .markus-card-image-night" in context.css and f"{selector} .markus-card-image-day" in context.css
