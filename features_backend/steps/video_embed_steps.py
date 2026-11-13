from __future__ import annotations

import io
import json
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

from papyrus_content import lens_evidence as evidence  # noqa: E402
from papyrus_content.markus_renderer.body_features import BodyFeatures  # noqa: E402
from papyrus_content.markus_renderer.content_markup import parse_attrs  # noqa: E402
from papyrus_content.markus_renderer.derive import derive_body  # noqa: E402
from papyrus_content.markus_renderer.video import parse_video  # noqa: E402
from papyrus_content.projection.directory_source import DirectoryContentSource  # noqa: E402
from papyrus_content.projection.engine import ProjectionContext, project_all  # noqa: E402
from papyrus_content.projection.standard.config import standard_settings_from_mapping  # noqa: E402
from papyrus_content.projection.standard.environment import resolve_environment  # noqa: E402
from papyrus_content.projection.standard.projector import StandardMarkusProjector  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.renditions import DirectoryRenditionStore  # noqa: E402
from procedures.newsroom.tests.standard_frontend_content_support import item, write_items  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import static_directory  # noqa: E402

VIDEO = "UytYrhYLOKI"
SITE = {"name": "Example", "productionUrl": "https://example.org"}
IMAGES = {"formats": ["webp"], "widths": [200, 400]}
FORBIDDEN_HOSTS = ("ytimg", "img.youtube.com", "googlevideo", "ggpht", "googleapis", "gstatic", "doubleclick", "i.ytimg")
PROVIDER_ADDRESS = re.compile(
    r"https?://(?:[\w-]+\.)*(?:youtube(?:-nocookie)?\.com|youtu\.be|vimeo\.com|instagram\.com|ytimg\.com|google\w*\.com)[^\s\"'<>]*", re.I
)


# ------------------------------------------------------------------ reading the directive

@when('I read the directive with src "{src}" title "{title}" and credit "{credit}"')
def read_plain(context, src, title, credit):
    _read(context, {"src": src, "title": title, "credit": credit})


@when('I read the directive with src "{src}" and these attributes: {raw}')
def read_with_attributes(context, src, raw):
    _read(context, {"src": src, **parse_attrs(raw)})


@when("I read the directive with these attributes only: {raw}")
def read_only_attributes(context, raw):
    _read(context, parse_attrs(raw))


def _read(context, attributes):
    context.video, context.refusal = None, None
    try:
        context.video = parse_video(attributes, "::video{...}")
    except ValueError as error:
        context.refusal = str(error)


@then('the video is "{identifier}"')
def video_is(context, identifier):
    assert context.refusal is None, context.refusal
    assert context.video.video_id == identifier


@then('the provider is "{provider}" and the video is "{identifier}"')
def provider_and_video(context, provider, identifier):
    assert context.refusal is None, context.refusal
    assert (context.video.provider, context.video.video_id) == (provider, identifier), context.video


@then("the directive is accepted and carries no poster")
def accepted_without_poster(context):
    assert context.refusal is None, context.refusal
    assert not hasattr(context.video, "poster")


@then('the address of the video on the page is "{address}"')
def watch_address(context, address):
    assert context.video.watch_url == address


@then('the directive is refused saying "{text}"')
def refused(context, text):
    assert context.refusal is not None, "the directive was accepted"
    assert text in context.refusal, context.refusal


@then('the refusal names the allowed provider "{name}"')
def names_provider(context, name):
    assert "Allowed providers" in context.refusal and name in context.refusal, context.refusal


@then('the layout is "{layout}" and there is no caption and no start time')
def defaults(context, layout):
    assert context.video.layout == layout and context.video.caption is None and context.video.start is None


@then('the start time is {start:d} seconds and the layout is "{layout}" and the caption is "{caption}"')
def read_values(context, start, layout, caption):
    assert (context.video.start, context.video.layout, context.video.caption) == (start, layout, caption), context.video


# ------------------------------------------------------------------ saving

@when("a Story with this body is saved on a site with embeds {state}:")
def save_story(context, state):
    features = BodyFeatures(video_embeds=state == "on")
    context.derivation = derive_body(None, context.text.strip() + "\n", features)


@then("converting the Markus of that Story gives the same page whether or not it names a credit and a caption")
def same_page(context):
    from papyrus_content.markus_renderer.convert import convert_text_in_process

    plain = 'Words.\n\n::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" poster="/assets/poster.jpg"}\n'
    wide = plain.replace('poster=', 'credit="Example Channel" caption="The first pass." start="90" poster=')
    assert convert_text_in_process(plain) == convert_text_in_process(wide)
    assert "<video" in convert_text_in_process(plain)


@then('the save is refused saying "{text}"')
def save_refused_saying(context, text):
    assert not context.derivation.ok
    assert any(text in error.message for error in context.derivation.errors), context.derivation.errors


@then("the video save succeeds")
def save_ok(context):
    assert context.derivation.ok, [error.message for error in context.derivation.errors]


@then('the stored body data lists the video "{identifier}" with its title and credit')
def stored_video(context, identifier):
    videos = context.derivation.body_ir["papyrus"]["videos"]
    [entry] = videos.values()
    assert entry["videoId"] == identifier and entry["title"] == "Aircraft demonstration" and entry["credit"] == "Example Channel", entry


@then("the stored body data has no list of videos")
def no_videos(context):
    assert "videos" not in context.derivation.body_ir["papyrus"]


@then("the save gives no warning about embeds")
def no_embeds_warning(context):
    assert not [w for w in context.derivation.warnings if w.code == "video-embeds-off"]


@then('the save is refused with the code "{code}" saying "{text}"')
def save_refused(context, code, text):
    assert not context.derivation.ok
    [error] = context.derivation.errors
    assert error.code == code and text in error.message, error


@then('the save warns "{text}"')
def save_warns(context, text):
    assert [w for w in context.derivation.warnings if text in w.message], context.derivation.warnings


# ------------------------------------------------------------------ projecting

class VideoSite:
    """A one-Story site projected by the standard front end."""

    def __init__(self, embeds, body, hooks=None):
        self.work = Path(tempfile.mkdtemp(prefix="video-embed-"))
        settings = {"site": dict(SITE), "images": dict(IMAGES), "media": {"originals": True}}
        if embeds is not None:
            settings["embeds"] = embeds
        content = write_items(self.work / "content", [item("a", body=body)])
        extra = None
        if hooks is not None:
            settings["hooks"] = "hooks.py"
            extra = {"hooks.py": hooks}
        static = static_directory(self.work, settings, extra)
        store = DirectoryRenditionStore(self.work / "store")   # an empty stand-in for the site bucket: a video needs nothing from it
        projector = StandardMarkusProjector.from_static_directory(static, renditions=store, environ={"PAPYRUS_SITE_PUBLIC_URL": ""})
        self.out = self.work / "out"
        report = project_all(ProjectionContext(source=DirectoryContentSource(content), projector=projector, writer=LocalDirectoryWriter(self.out), keep_state=False))
        assert report.ok, report.errors

    @property
    def tree(self) -> dict[str, bytes]:
        return {path.relative_to(self.out).as_posix(): path.read_bytes() for path in sorted(self.out.rglob("*")) if path.is_file()}

    def text(self, key: str) -> str:
        return (self.out / key).read_text(encoding="utf-8")


def _site(context, embeds, body, hooks=None) -> VideoSite:
    site = VideoSite(embeds, body, hooks)
    context.add_cleanup(shutil.rmtree, site.work, True)
    return site


@given("a site with embeds on")
def site_on(context):
    context.embeds, context.hooks = {"providers": ["youtube"]}, None


@given("a site with embeds off")
def site_off(context):
    context.embeds, context.hooks = None, None


@given("a site with embeds that list no provider")
def site_lists_none(context):
    context.embeds, context.hooks = {"providers": []}, None


@given("a site with embeds off and the Pilobolus hook for Instagram lines")
def site_off_with_hook(context):
    context.embeds = None
    context.hooks = (REPO_ROOT / "features_backend" / "fixtures" / "video-embed" / "pilobolus-instagram" / "hooks.py").read_bytes()


@given('a site whose embeds list "{names}"')
def site_lists(context, names):
    context.embeds, context.hooks = {"providers": names.split(",")}, None


@when("the Story is projected:")
def project_story(context):
    context.site = _site(context, context.embeds, context.text.strip() + "\n", context.hooks)
    context.html = context.site.text("a.html")


def _article(context) -> str:
    return context.html


def _iframes(context) -> list[str]:
    return re.findall(r"<iframe\b[^>]*>", context.html)


@then('the page has an iframe titled "{title}" with the address "{address}"')
def has_iframe(context, title, address):
    [tag] = _iframes(context)
    assert f'src="{address}"' in tag and f'title="{title}"' in tag, tag


@then("the iframe is the provider's standard embed: lazy, fullscreen, strict referrer policy and the usual permissions")
def standard_iframe(context):
    [tag] = _iframes(context)
    for part in ('loading="lazy"', " allowfullscreen ", 'referrerpolicy="strict-origin-when-cross-origin"',
                 'allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"'):
        assert part in tag, (part, tag)


@then("the iframe fills a responsive 16 by 9 wrapper with no border and rounded corners")
def wrapper(context):
    assert re.search(r'<div class="papyrus-video-frame" data-provider="youtube"><iframe ', context.html), context.html
    css = _style(context)
    assert ".papyrus-video-frame{position:relative;width:100%;aspect-ratio:16 / 9;" in css and "border-radius:var(--papyrus-radius" in css
    assert ".papyrus-video-frame iframe{position:absolute;inset:0;display:block;width:100%;height:100%;border:0" in css


@then("the page has no poster, no placeholder and no play button of ours")
def no_facade(context):
    for part in ("papyrus-video-poster", "papyrus-video-placeholder", "papyrus-video-play", "papyrus-video-link", "is-ready", "data-embed"):
        assert part not in context.html, part


@then('the figure caption reads "{caption}" and credits "{credit}" with a link to the video')
def figure_caption(context, caption, credit):
    match = re.search(r"<figcaption>(.*?)</figcaption>", context.html, re.S)
    assert match, "no caption"
    assert match.group(1).startswith(caption + " · ")
    assert f'<span class="papyrus-image-credit"><a href="https://www.youtube.com/watch?v={VIDEO}' in match.group(1) and f">{credit}</a>" in match.group(1)


@then("the page has no frame")
def no_frame(context):
    assert "<iframe" not in context.html.lower()


@then("the stock rules give an Instagram frame a portrait ratio and a minimum height")
def portrait(context):
    assert '.papyrus-video-frame[data-provider="instagram"]{aspect-ratio:4 / 5;min-height:30rem' in _style(context)


@then("the page needs no script from us")
def needs_no_script(context):
    assert "_plugins/papyrus-video" not in context.html and "papyrus-video-v1" not in context.html
    assert not [tag for tag in re.findall(r"<script\b[^>]*>", context.html) if "video" in tag.lower()]


@then("the only address on a video provider in the page is the iframe and the plain link in the credit line")
def only_iframe_and_link(context):
    body = re.sub(r"<iframe\b[^>]*>", "<iframe>", context.html)
    body = re.sub(r'<a [^>]*href="[^"]*"', lambda m: re.sub(r'href="[^"]*"', 'href=""', m.group(0)), body)
    assert not PROVIDER_ADDRESS.findall(body), PROVIDER_ADDRESS.findall(body)
    for tag in re.findall(r"<(?:img|script|link|source|video|audio|embed|object)\b[^>]*>", context.html, re.I):
        assert not PROVIDER_ADDRESS.search(tag), tag
    assert not [host for host in FORBIDDEN_HOSTS if host in context.html.lower()]


def _style(context) -> str:
    return "".join(re.findall(r"<style>(.*?)</style>", context.html, re.S))


@then('the figure has the classes "{classes}"')
def figure_classes(context, classes):
    assert f'<figure class="{classes}">' in context.html


@then("the page has {count:d} iframes and the stock rules once")
def two_videos(context, count):
    assert len(_iframes(context)) == count
    assert context.html.count(".papyrus-video-frame{position:relative") == 1


@then('the page has the line "{line}" with the title linked to "{address}"')
def fallback_line(context, line, address):
    match = re.search(r'<p class="papyrus-video-line">(.*?)</p>', context.html, re.S)
    assert match, "no plain linked credit line"
    text = re.sub(r"<[^>]+>", "", match.group(1))
    assert text == line, text
    assert re.search(rf'<a href="{re.escape(address)}" rel="noopener noreferrer">[^<]+</a>', match.group(1)), match.group(1)


@then("the page has none of Papyrus's video markup")
def left_alone(context):
    assert "papyrus-video" not in context.html, "Papyrus drew a video on a site that lists no provider"


@then("the page holds the site's own Instagram embed")
def own_embed(context):
    assert '<div class="pilo-instagram"><blockquote class="instagram-media"' in context.html, context.html


@then("the page has no button and no frame")
def no_button(context):
    assert "papyrus-video-play" not in context.html and "<iframe" not in context.html.lower() and "data-papyrus-video=" not in context.html


@then("the site publishes no video script and no content-security-policy fragment")
def nothing_published(context):
    keys = set(context.site.tree)
    assert not [key for key in keys if "papyrus-video" in key] and "_config/content-security-policy.txt" not in keys


STORY = "Words only.\n"


@given("the same Story on a site with no embeds setting and on a site with embeds that list no provider")
def same_story_two_sites(context):
    body = '::video{src="https://youtu.be/UytYrhYLOKI" title="T"}\n'
    context.first = _site(context, None, body)
    context.second = _site(context, {"providers": []}, body)


@then("the two sites publish identical files")
def identical(context):
    assert context.first.tree == context.second.tree


@given("the same Story without a video on a site with embeds off and on a site with embeds on")
def same_story_without_video(context):
    context.first = _site(context, {"providers": []}, STORY)
    context.second = _site(context, {"providers": ["youtube"]}, STORY)


@then("every page of the two sites is identical")
def pages_identical(context):
    shared = set(context.first.tree) & set(context.second.tree)
    assert shared and all(context.first.tree[key] == context.second.tree[key] for key in shared), [key for key in shared if context.first.tree[key] != context.second.tree[key]]


@then("the site with embeds on publishes one more file: the content-security-policy fragment")
def one_more(context):
    assert set(context.second.tree) - set(context.first.tree) == {"_config/content-security-policy.txt"}
    assert set(context.first.tree) <= set(context.second.tree)


@then("the Markdown copy holds the line exactly as written, with the title, caption, credit and address in it")
def twin_verbatim(context):
    line = '::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" caption="Two microphones, one jet." credit="Example Channel"}'
    twin = context.site.text("a.md")
    assert line in twin.split("\n"), twin
    assert "<" not in line and "papyrus-video" not in twin


# ------------------------------------------------------------------ settings and the policy

@then('the setting {setting} is refused saying "{message}"')
def setting_refused(context, setting, message):
    value = json.loads(setting)
    try:
        standard_settings_from_mapping({"site": dict(SITE), "embeds": value})
    except ValueError as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError("the setting was accepted")


@then('the site publishes the policy fragment "{policy}"')
def policy_fragment(context, policy):
    assert context.site.text("_config/content-security-policy.txt") == policy + "\n"


@then("the fragment allows no script, image, style, connect or default source")
def only_frames(context):
    text = context.site.text("_config/content-security-policy.txt")
    parts = text.strip().split(";")
    assert [part.split()[0] for part in parts] == ["frame-src"]
    assert all(word.startswith("https://") and word.count("/") == 2 for word in parts[0].split()[1:]), text


# ------------------------------------------------------------------ the checks

ORIGIN = "https://example.test"
FRONT = "title: Board refuses\nsummary: The board refused it.\ndate: 2026-03-03\nauthor: Dana Reyes\nimage: /assets/own.jpg\nimageAlt: A harbour\n"
CITATION = "citations:\n  demo:\n    type: webpage\n    title: The demonstration\n    URL: {url}\n"


def _lens_site(providers: list[str] | None):
    raw = {"site": {"name": "Example", "productionUrl": ORIGIN}, "seo": {"publisherName": "Example"}}
    if providers is not None:
        raw["embeds"] = {"providers": providers}
    standard = standard_settings_from_mapping(raw)
    return evidence.LensSite(standard, resolve_environment(standard, {"PAPYRUS_SITE_PUBLIC_URL": ORIGIN}))


def _run_checks(context, body, *, site, cites=None):
    front = FRONT + (CITATION.format(url=cites) if cites else "")
    row = {"id": "v1", "lineageId": "s1", "versionNumber": 1, "type": "article", "slug": "board", "section": None, "stage": "copywriting",
           "title": "Board refuses", "bodyMarkus": body.strip() + "\n", "metadata": json.dumps({"frontMatterYaml": front})}
    context.found = {found["check"]: found for found in evidence.run_checks(evidence.story_from_row(row), site)}


@when("the lens checks run on a Story with this body:")
def checks_plain(context):
    _run_checks(context, context.text, site=_lens_site(["youtube"]))


@when("the lens checks run on a Story with this body on a site with embeds {state}:")
def checks_on_site(context, state):
    _run_checks(context, context.text, site=_lens_site(["youtube"] if state == "on" else []))


@when('the lens checks run on a Story with this body on a site that lists "{names}":')
def checks_on_listing_site(context, names):
    _run_checks(context, context.text, site=_lens_site(names.split(",")))


@when('the lens checks run on a Story that cites the video "{url}" with this body:')
def checks_cited(context, url):
    _run_checks(context, context.text, site=_lens_site(["youtube"]), cites=url)


@when('the lens checks run on a Story that cites the video "{url}" with this body on a site with embeds on:')
def checks_cited_on_site(context, url):
    _run_checks(context, context.text, site=_lens_site(["youtube"]), cites=url)


@then("the check {key} looks fine")
def check_fine(context, key):
    assert context.found[key]["state"] == "pass", context.found[key]


@then('the check {key} looks fine saying "{text}"')
def check_fine_saying(context, key, text):
    assert context.found[key]["state"] == "pass" and text in context.found[key]["message"], context.found[key]


@then('the check {key} needs a look saying "{text}"')
def check_concern(context, key, text):
    found = context.found[key]
    assert found["state"] == "concern" and text in found["message"], found


@then('the check {key} is a problem saying "{text}"')
def check_problem(context, key, text):
    found = context.found[key]
    assert found["state"] == "problem" and text in found["message"], found


@then("the checks {keys} all look fine")
def checks_all_fine(context, keys):
    for key in re.findall(r"[PACS]\d+", keys):
        assert context.found[key]["state"] == "pass", context.found[key]


@then("the checks {keys} do not apply")
def checks_not_applicable(context, keys):
    for key in re.findall(r"[PACS]\d+", keys):
        assert context.found[key]["state"] == "not_applicable", context.found[key]
