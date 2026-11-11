from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from PIL import Image  # noqa: E402

from papyrus_content.markus_renderer.content_markup import prepare_page  # noqa: E402
from papyrus_content.markus_renderer.images import ImageBuilder, ImagePipeline  # noqa: E402
from papyrus_content.projection.standard.markdown import home_markdown, item_markdown  # noqa: E402


@given('a Story picture credited "{credit}"')
def picture_credited(context, credit):
    context.credit_written = credit
    context.picture_directive = f'::image{{src="assets/harbour.jpg" alt="A harbour" credit="{credit}"}}'


@given('a Story picture with the caption "{caption}" credited "{credit}"')
def picture_with_caption(context, caption, credit):
    context.picture_directive = f'::image{{src="assets/harbour.jpg" alt="A harbour" caption="{caption}" credit="{credit}"}}'


@given('a Story picture written over several lines with the credit "{credit}"')
def picture_over_lines(context, credit):
    context.picture_directive = f'::image{{\n  src="assets/harbour.jpg"\n  credit="{credit}"\n  alt="A harbour"\n}}'


@when("the picture is rendered on the page")
def render_picture(context):
    with tempfile.TemporaryDirectory() as tmp:
        content = Path(tmp) / "content"
        (content / "assets").mkdir(parents=True)
        Image.new("RGB", (400, 300), (30, 90, 160)).save(content / "assets" / "harbour.jpg")
        page = prepare_page(context.picture_directive, images=ImagePipeline(), citations=None)
        builder = ImageBuilder(ImagePipeline(), content_dir=content, out_dir=Path(tmp) / "dist")
        context.page_html = builder.render(next(iter(page.images.values())))


@then('the credit under the picture is "{expected}"')
def credit_on_page(context, expected):
    match = re.search(r'<span class="papyrus-image-credit">(.*?)</span>', context.page_html)
    assert match and match.group(1) == expected.replace("&", "&amp;"), context.page_html


@then("there is no credit under the picture")
def no_credit_on_page(context):
    assert "papyrus-image-credit" not in context.page_html and "Generated" not in context.page_html, context.page_html


@then('the figure caption is exactly "{expected}"')
def caption_only(context, expected):
    match = re.search(r"<figcaption>(.*?)</figcaption>", context.page_html)
    assert match and match.group(1) == expected, context.page_html


@when("the Markdown copy of the Story is made")
def make_twin(context):
    entry = SimpleNamespace(title="Harbour", author_details=None, date=None, updated=None, summary_text="")
    context.twin = item_markdown(entry, "---\ntitle: Harbour\n---\n" + context.picture_directive + "\n", None)


@when("the Markdown copy of the home page is made")
def make_home_twin(context):
    context.twin = home_markdown("Home", "A home page.", "---\ntitle: Home\n---\n" + context.picture_directive + "\n")


@then("the picture in the Markdown copy has no credit")
def no_credit_in_twin(context):
    assert "credit" not in context.twin, context.twin


@then("the Markdown copy still has the picture's source and alt text")
def twin_still_valid(context):
    assert 'src="assets/harbour.jpg"' in context.twin and 'alt="A harbour"' in context.twin and "::image{" in context.twin and context.twin.rstrip().endswith("}"), context.twin


@then('the picture in the Markdown copy is credited "{expected}"')
def credit_in_twin(context, expected):
    assert f'credit="{expected}"' in context.twin, context.twin
