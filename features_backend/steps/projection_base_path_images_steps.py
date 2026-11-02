from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.engine import ProjectionContext, reconcile  # noqa: E402
from papyrus_content.projection.standard.projector import StandardMarkusProjector  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.projection.directory_source import DirectoryContentSource  # noqa: E402
from procedures.newsroom.tests.based_images_support import CHART, BasedImageSite, pages, tree  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import static_directory  # noqa: E402

EXPECTED_ROOT = REPO_ROOT / "features_backend" / "fixtures" / "based-images" / "root-expected"
IMAGE_URL = re.compile(r'\b(?:src|srcset)="([^"]+)"')
SRCSET_URL = re.compile(r"(\S+)\s+\d+w")


def new_site(context, base_path: str | None) -> None:
    context.images_site = BasedImageSite(base_path)
    context.add_cleanup(context.images_site.cleanup)
    context.add_cleanup(context.images_site.release_function)


def image_urls(html: str) -> list[str]:
    """Every URL of an image the page shows: each src and every entry of each srcset, links and metadata excluded."""
    urls: list[str] = []
    for match in re.finditer(r"<(?:img|source)\b[^>]*>", html):
        for attribute in IMAGE_URL.findall(match.group(0)):
            urls.extend(SRCSET_URL.findall(attribute) or [attribute])
    return urls


def exists(site: BasedImageSite, url: str) -> bool:
    return (site.out / url.lstrip("/")).is_file()


@given('a site under the base path "{base}" with images and media originals')
def based_site(context, base: str) -> None:
    new_site(context, base)


@given("a site without a base path with images and media originals")
def unbased_site(context) -> None:
    new_site(context, None)


@given('a story "hello" with a light and dark chart, a lone picture and a Markdown picture')
def story(context) -> None:
    assert (context.images_site.content / "hello.md").is_file()


@when("the site is projected with the local command")
def project_locally(context) -> None:
    context.images_site.project_locally()


@given("the renditions function is configured for the site")
def function_configured(context) -> None:
    context.images_site.configure_function()


@given("every picture of the story is uploaded to the media store")
def upload_all(context) -> None:
    context.images_site.upload_all()


@when('the media object "{key}" is uploaded')
def object_created(context, key: str) -> None:
    context.images_site.upload(key)


@given("the renditions of the story were made before the base path was set")
def renditions_before_base(context) -> None:
    site = context.images_site
    before = BasedImageSite(None)
    context.add_cleanup(before.cleanup)
    before.configure_function()
    before.upload_all()
    before.release_function()
    site.site_store = before.site_store


@when("the site is rendered from the site store")
def render_from_store(context) -> None:
    context.images_site.render_from_store()


@when("the site is reconciled against its output")
def reconcile_output(context) -> None:
    site = context.images_site
    from papyrus_content.renditions import DirectoryRenditionStore

    projector = StandardMarkusProjector.from_static_directory(site.static, renditions=DirectoryRenditionStore(site.out), environ={"PAPYRUS_SITE_PUBLIC_URL": ""})
    before = tree(site.out)
    projection = ProjectionContext(source=DirectoryContentSource(site.content), projector=projector, writer=LocalDirectoryWriter(site.out), keep_state=False)
    context.reconcile_report = reconcile(projection)
    context.tree_before_reconcile = before


@when('the settings of a site with base path "{base}", an images section and a media section are read')
def read_settings(context, base: str) -> None:
    work = Path(tempfile.mkdtemp(prefix="based-images-settings-"))
    context.add_cleanup(lambda: shutil.rmtree(work, ignore_errors=True))
    raw = {"site": {"name": "Example"}, "urls": {"basePath": base}, "images": {}, "media": {"originals": True}}
    context.settings_error = None
    try:
        StandardMarkusProjector.from_static_directory(static_directory(work, raw), environ={"PAPYRUS_SITE_PUBLIC_URL": ""})
    except ValueError as error:
        context.settings_error = error


@then("the pictured settings are accepted")
def settings_accepted(context) -> None:
    assert context.settings_error is None, context.settings_error


@then('the output holds the renditions of the chart under "{prefix}"')
def output_has_renditions(context, prefix: str) -> None:
    keys = [key for key in tree(context.images_site.out) if key.startswith(prefix) and "/chart" in key]
    assert any(key.endswith("chart.meta.json") for key in keys) and any(key.endswith("chart-400.webp") for key in keys), sorted(tree(context.images_site.out))


@then('the output holds the original "{key}"')
def output_has_original(context, key: str) -> None:
    site = context.images_site
    assert tree(site.out).get(key) == site.pictures[CHART], sorted(tree(site.out))


@then('the output holds nothing under "{first}" and nothing under "{second}" at its root')
def output_has_no_root_assets(context, first: str, second: str) -> None:
    stray = [key for key in tree(context.images_site.out) if key.startswith((first, second))]
    assert not stray, stray


@then('every image URL in "{key}" starts with "{prefix}"')
def image_urls_start(context, key: str, prefix: str) -> None:
    urls = image_urls((context.images_site.out / key).read_text(encoding="utf-8"))
    assert len(urls) >= 12, urls
    assert all(url.startswith(prefix) for url in urls), [url for url in urls if not url.startswith(prefix)]


@then('every image URL in "{key}" is a file of the output at that path')
def image_urls_exist(context, key: str) -> None:
    site = context.images_site
    urls = image_urls((site.out / key).read_text(encoding="utf-8"))
    missing = [url for url in urls if not exists(site, url)]
    assert not missing, missing


@then('the pictured page "{key}" has a light and a dark variant of the chart')
def has_pair(context, key: str) -> None:
    html = (context.images_site.out / key).read_text(encoding="utf-8")
    light = re.search(r'<div class="papyrus-image-light">(.*?)</div>', html, re.S)
    dark = re.search(r'<div class="papyrus-image-dark">(.*?)</div>', html, re.S)
    assert light and dark, html[:3000]
    context.light_html, context.dark_html = light.group(1), dark.group(1)
    assert "/chart-800.png" in context.light_html and "/chart.dark-800.png" in context.dark_html


@then('both variants use only URLs under "{prefix}"')
def pair_urls(context, prefix: str) -> None:
    for html in (context.light_html, context.dark_html):
        urls = image_urls(html)
        assert urls and all(url.startswith(prefix) for url in urls), urls


@then('the pictured page "{key}" carries the rule that shows the dark variant only in dark mode')
def dark_rule(context, key: str) -> None:
    html = (context.images_site.out / key).read_text(encoding="utf-8")
    assert ".papyrus-image-dark{display:none}" in html
    assert ":root[data-theme=dark] .papyrus-image-dark" in html and ":root.dark:not([data-theme=light]) .papyrus-image-dark" in html


@then("the srcset widths of both variants are files of the output")
def pair_files(context) -> None:
    site = context.images_site
    for html in (context.light_html, context.dark_html):
        widths = {int(width) for width in re.findall(r"\s(\d+)w", html)}
        assert widths == {200, 400, 800}, widths
        assert all(exists(site, url) for url in image_urls(html))


@then('the Markdown picture of "hello" is a responsive image whose URLs start with "{prefix}"')
def markdown_picture(context, prefix: str) -> None:
    html = (context.images_site.out / "articles/hello/index.html").read_text(encoding="utf-8")
    figure = re.search(r'<figure[^>]*>(?:(?!</figure>).)*alt="A photo"(?:(?!</figure>).)*</figure>', html, re.S) or re.search(r'<(?:picture|img)[^>]*>(?:(?!</picture>).)*alt="A photo".*?(?:</picture>|>)', html, re.S)
    assert figure, html[-3000:]
    urls = image_urls(figure.group(0))
    assert urls and all(url.startswith(prefix) and "/photo-" in url for url in urls), urls
    assert all(exists(context.images_site, url) for url in urls)


@then('the pictured page "{key}" says "{text}"')
def page_says(context, key: str, text: str) -> None:
    body = (context.images_site.out / key).read_text(encoding="utf-8")
    assert text in body, body[:3000]


@then('the pictured page "{key}" does not say "{text}"')
def page_does_not_say(context, key: str, text: str) -> None:
    body = (context.images_site.out / key).read_text(encoding="utf-8")
    assert text not in body, body[:3000]


@then("the reconcile finds no orphan pages and deletes nothing")
def reconcile_clean(context) -> None:
    report = context.reconcile_report
    assert not report.orphan_pages, report.orphan_pages
    lost = sorted(set(context.tree_before_reconcile) - set(tree(context.images_site.out)))
    assert not lost, lost


@then('the output still holds the renditions of the chart under "{prefix}"')
def output_still_has_renditions(context, prefix: str) -> None:
    output_has_renditions(context, prefix)


@then('the site store holds the description "{key}"')
def store_holds_description(context, key: str) -> None:
    assert (context.images_site.site_store / key).is_file(), sorted(tree(context.images_site.site_store))


@then('the site store holds the original "{key}" equal to the uploaded object')
def store_holds_original(context, key: str) -> None:
    site = context.images_site
    assert tree(site.site_store).get(key) == site.pictures[CHART]


@then("the site store holds nothing at its root")
def store_empty_at_root(context) -> None:
    stray = [key for key in tree(context.images_site.site_store) if not key.startswith("articles/")]
    assert not stray, stray


@then("the pages of the cloud render equal the pages of the local render")
def cloud_equals_local(context) -> None:
    site = context.images_site
    assert site.error is None, site.error
    local = pages(site.out)
    cloud = pages(site.cloud_out)
    assert set(local) == set(cloud), (sorted(set(local) ^ set(cloud)))
    different = [key for key in cloud if cloud[key] != local[key]]
    assert not different, different


@then('the render fails naming "{key}" and the renditions command')
def render_fails(context, key: str) -> None:
    message = str(context.images_site.error or "")
    assert key in message and "papyrus ops content renditions --source" in message, message


@then("the pages equal the recorded pages of the site before base paths covered images")
def pages_equal_recorded(context) -> None:
    site = context.images_site
    assert site.error is None, site.error
    rendered = pages(site.cloud_out)
    recorded = {path.relative_to(EXPECTED_ROOT).as_posix(): path.read_bytes() for path in sorted(EXPECTED_ROOT.rglob("*")) if path.is_file()}
    assert set(rendered) == set(recorded), sorted(set(rendered) ^ set(recorded))
    different = [key for key in recorded if rendered[key] != recorded[key]]
    assert not different, different
