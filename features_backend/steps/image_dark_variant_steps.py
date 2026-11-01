from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from PIL import Image  # noqa: E402

from papyrus_content.markus_renderer.images import (  # noqa: E402
    DARK_VARIANT_CSS,
    ImageBuilder,
    ImagePipeline,
    ImagePipelineError,
    ImageRequest,
)


def _workspace(context) -> Path:
    if getattr(context, "dark_root", None) is None:
        context.dark_root = Path(tempfile.mkdtemp(prefix="image-dark-"))
        context.tmp_dirs.append(context.dark_root)
        (context.dark_root / "content").mkdir()
    return context.dark_root


def _make(context, name: str, width: int, height: int) -> None:
    path = _workspace(context) / "content" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), (20, 40, 60)).save(path)


def _render(context, request: ImageRequest) -> None:
    root = _workspace(context)
    builder = ImageBuilder(
        ImagePipeline(widths=(200, 400), formats=("webp",)),
        content_dir=root / "content",
        out_dir=root / "dist",
    )
    context.dark_error = None
    context.dark_html = ""
    try:
        context.dark_html = builder.render(request)
    except ImagePipelineError as error:
        context.dark_error = str(error)


@given('an image "{name}" of {width:d} by {height:d} pixels')
def step_image(context, name, width, height):
    _make(context, name, width, height)


@given('an image pair "{name}" of {width:d} by {height:d} pixels, and a dark file "{dark}" of {dw:d} by {dh:d} pixels')
def step_image_with_dark(context, name, width, height, dark, dw, dh):
    _make(context, name, width, height)
    _make(context, dark, dw, dh)


@when('I render the image "{name}" with srcDark "{dark}"')
def step_render_explicit(context, name, dark):
    _render(context, ImageRequest(src=name, alt="A chart", src_dark=dark, pair_by_name=True))


@when('I render the directive image "{name}" without srcDark')
def step_render_by_name(context, name):
    _render(context, ImageRequest(src=name, alt="A chart", pair_by_name=True))


def _variant(html: str, which: str) -> str:
    match = re.search(rf'<div class="papyrus-image-{which}">(.*?)</div>(?=<div class="papyrus-image-dark">|</figure>)', html, re.S)
    assert match, f"no {which} variant in {html}"
    return match.group(1)


@then("the figure has a light variant and a dark variant")
def step_both(context):
    assert context.dark_error is None, context.dark_error
    assert 'class="papyrus-image-light"' in context.dark_html
    assert 'class="papyrus-image-dark"' in context.dark_html
    assert context.dark_html.count("<style>") == 1


@then("the figure has no dark variant")
def step_none(context):
    assert context.dark_error is None, context.dark_error
    assert "papyrus-image-dark" not in context.dark_html
    assert "<picture>" in context.dark_html


@then("both variants have responsive renditions of their own file")
def step_renditions(context):
    light = _variant(context.dark_html, "light")
    dark = _variant(context.dark_html, "dark")
    assert "chart-400.webp" in light and "chart-night" not in light
    assert "chart-night-400.webp" in dark and "chart-night-400.webp" in dark
    assert "<source" in dark and "srcset=" in dark


@then("the light image keeps width {width:d} and height {height:d}")
def step_light_size(context, width, height):
    assert f'width="{width}" height="{height}"' in _variant(context.dark_html, "light")


@then("the dark image is lazy loaded")
def step_dark_lazy(context):
    assert 'loading="lazy"' in _variant(context.dark_html, "dark")


@then("when the root has no theme set, a dark operating system preference hides the light variant and shows the dark one")
def step_os(context):
    assert "@media (prefers-color-scheme:dark){:root:not([data-theme]):not(.dark) .papyrus-image-light{display:none}" in DARK_VARIANT_CSS
    assert ":root:not([data-theme]):not(.dark) .papyrus-image-dark{display:revert}" in DARK_VARIANT_CSS
    assert DARK_VARIANT_CSS.startswith(".papyrus-image-dark{display:none}")
    assert DARK_VARIANT_CSS in context.dark_html


@then('data-theme "dark" on the root shows the dark variant whatever the operating system prefers')
def step_theme_dark(context):
    assert ":root[data-theme=dark] .papyrus-image-light" in DARK_VARIANT_CSS
    assert ":root[data-theme=dark] .papyrus-image-dark" in DARK_VARIANT_CSS


@then('data-theme "light" on the root keeps the light variant even when the operating system is dark')
def step_theme_light(context):
    # Every dark-showing rule outside the media query requires data-theme=dark or no data-theme,
    # and the media query rule is guarded by :not([data-theme]).
    outside = DARK_VARIANT_CSS.split("}}", 1)[1]
    assert "[data-theme=light]" not in outside.replace(":not([data-theme=light])", "")
    assert ":not([data-theme])" in DARK_VARIANT_CSS.split("}}", 1)[0]


@then("a dark class on the root is understood when no data-theme is set")
def step_class(context):
    assert ":root.dark:not([data-theme=light]) .papyrus-image-dark{display:revert}" in DARK_VARIANT_CSS


@then('the build fails naming "{first}" and "{second}"')
def step_fails(context, first, second):
    assert context.dark_error, "expected a build error"
    assert first in context.dark_error and second in context.dark_error, context.dark_error
