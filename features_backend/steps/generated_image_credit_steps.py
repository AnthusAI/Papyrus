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
from papyrus_content.projection.standard.markdown import item_markdown  # noqa: E402


@given('a Story picture credited "{credit}"')
def picture_credited(context, credit):
    context.credit_written = credit
    context.picture_directive = f'::image{{src="assets/harbour.jpg" alt="A harbour" credit="{credit}"}}'


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


@when("the Markdown copy of the Story is made")
def make_twin(context):
    entry = SimpleNamespace(title="Harbour", author_details=None, date=None, updated=None, summary_text="")
    context.twin = item_markdown(entry, "---\ntitle: Harbour\n---\n" + context.picture_directive + "\n", None)


@then('the picture in the Markdown copy is credited "{expected}"')
def credit_in_twin(context, expected):
    assert f'credit="{expected}"' in context.twin, context.twin
