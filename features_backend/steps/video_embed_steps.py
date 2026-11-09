from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from PIL import Image  # noqa: E402

from papyrus_content import lens_evidence as evidence  # noqa: E402
from papyrus_content.markus_renderer.body_features import BodyFeatures  # noqa: E402
from papyrus_content.markus_renderer.content_markup import parse_attrs  # noqa: E402
from papyrus_content.markus_renderer.derive import derive_body  # noqa: E402
from papyrus_content.markus_renderer.video import REGISTRY, parse_video  # noqa: E402
from papyrus_content.projection.directory_source import DirectoryContentSource  # noqa: E402
from papyrus_content.projection.engine import ProjectionContext, project_all  # noqa: E402
from papyrus_content.projection.standard.config import standard_settings_from_mapping  # noqa: E402
from papyrus_content.projection.standard.environment import resolve_environment  # noqa: E402
from papyrus_content.projection.standard.projector import StandardMarkusProjector  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.reference_thumbnails import Response, Unreachable, fetch_thumbnail  # noqa: E402
from papyrus_content.renditions import DirectoryRenditionStore, images_from_projection, make_renditions  # noqa: E402
from papyrus_content.video_posters import stories_capture_video_posters  # noqa: E402
from procedures.newsroom.tests.standard_frontend_content_support import item, write_items  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import static_directory  # noqa: E402

VIDEO = "UytYrhYLOKI"
SITE = {"name": "Example", "productionUrl": "https://example.org"}
IMAGES = {"formats": ["webp"], "widths": [200, 400]}
FORBIDDEN_HOSTS = ("ytimg", "img.youtube.com", "googlevideo", "ggpht", "google.com", "googleapis", "gstatic", "doubleclick", "i.ytimg")
PROVIDER_ADDRESS = re.compile(
    r"https?://(?:[\w-]+\.)*(?:youtube(?:-nocookie)?\.com|youtu\.be|vimeo\.com|instagram\.com|ytimg\.com|google\w*\.com)[^\s\"'<>]*", re.I
)


def jpeg(size=(480, 360)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 90, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


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


@then('the poster is "{path}"')
def poster_is(context, path):
    assert context.refusal is None, context.refusal
    assert context.video.poster == path and context.video.poster_source == path.lstrip("/"), context.video


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
    """A one-Story site projected by the standard front end, with the rendition store standing in for the site bucket."""

    def __init__(self, embeds, body, poster, hooks=None):
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
        store = DirectoryRenditionStore(self.work / "store")
        for path in ([f"assets/video-posters/youtube-{VIDEO}.jpg"] if poster is True else list(poster or [])):
            make_renditions(images_from_projection(settings), store, path, jpeg())
        projector = StandardMarkusProjector.from_static_directory(static, renditions=store, environ={"PAPYRUS_SITE_PUBLIC_URL": ""})
        self.out = self.work / "out"
        report = project_all(ProjectionContext(source=DirectoryContentSource(content), projector=projector, writer=LocalDirectoryWriter(self.out), keep_state=False))
        assert report.ok, report.errors

    @property
    def tree(self) -> dict[str, bytes]:
        return {path.relative_to(self.out).as_posix(): path.read_bytes() for path in sorted(self.out.rglob("*")) if path.is_file()}

    def text(self, key: str) -> str:
        return (self.out / key).read_text(encoding="utf-8")


def _site(context, embeds, body, poster, hooks=None) -> VideoSite:
    site = VideoSite(embeds, body, poster, hooks)
    context.add_cleanup(shutil.rmtree, site.work, True)
    return site


@given("a site with embeds on that has the poster of \"{identifier}\" in its storage")
def site_on_with_poster(context, identifier):
    assert identifier == VIDEO
    context.embeds, context.poster, context.hooks = {"providers": ["youtube"]}, True, None


@given("a site with embeds on that has no poster for \"{identifier}\" in its storage")
def site_on_without_poster(context, identifier):
    context.embeds, context.poster, context.hooks = {"providers": ["youtube"]}, False, None


@given("a site with embeds off")
def site_off(context):
    context.embeds, context.poster, context.hooks = None, True, None


@given("a site with embeds that list no provider")
def site_lists_none(context):
    context.embeds, context.poster, context.hooks = {"providers": []}, True, None


@given("a site with embeds off and the Pilobolus hook for Instagram lines")
def site_off_with_hook(context):
    context.embeds, context.poster = None, True
    context.hooks = (REPO_ROOT / "features_backend" / "fixtures" / "video-embed" / "pilobolus-instagram" / "hooks.py").read_bytes()


@given('a site whose embeds list "{names}" and that has the poster "{name}" in its storage')
def site_lists_with_poster(context, names, name):
    context.embeds, context.poster, context.hooks = {"providers": names.split(",")}, [f"assets/video-posters/{name}.jpg"], None


@given('a site whose embeds list "{names}" and that has the picture "{path}" in its storage')
def site_lists_with_picture(context, names, path):
    context.embeds, context.poster, context.hooks = {"providers": names.split(",")}, [path.lstrip("/")], None


@given('a site whose embeds list "{names}" and that has no pictures in its storage')
def site_lists_without_pictures(context, names):
    context.embeds, context.poster, context.hooks = {"providers": names.split(",")}, [], None


@when("the Story is projected:")
def project_story(context):
    context.site = _site(context, context.embeds, context.text.strip() + "\n", context.poster, context.hooks)
    context.html = context.site.text("a.html")


def _article(context) -> str:
    return context.html


@then('the page has a button named "{name}"')
def has_button(context, name):
    assert f'<button type="button" class="papyrus-video-play" aria-label="{name}">' in context.html


@then("the button holds the Lucide play icon as a flat filled shape")
def play_icon(context):
    assert 'data-icon="play"' in context.html and 'fill="currentColor"' in context.html and 'stroke="none"' in context.html


@then('the poster is the site\'s own copy under "{prefix}"')
def poster_is_ours(context, prefix):
    poster = re.search(r'<span class="papyrus-video-poster"><picture>.*?</picture></span>', context.html, re.S)
    assert poster and prefix in poster.group(0), "no poster picture from the site's storage"
    assert 'alt=""' in poster.group(0)


@then('the poster is a plain link to "{address}" with the title as its text')
def poster_link(context, address):
    assert f'<a class="papyrus-video-link" href="{address}"' in context.html
    assert '<span class="papyrus-video-title">Aircraft demonstration</span></a>' in context.html


@then('the figure caption reads "{caption}" and credits "{credit}" with a link to the video')
def figure_caption(context, caption, credit):
    match = re.search(r"<figcaption>(.*?)</figcaption>", context.html, re.S)
    assert match, "no caption"
    assert match.group(1).startswith(caption + " · ")
    assert f'<span class="papyrus-image-credit"><a href="https://www.youtube.com/watch?v={VIDEO}' in match.group(1) and f">{credit}</a>" in match.group(1)


@then("the page has no frame")
def no_frame(context):
    assert "<iframe" not in context.html.lower()


@then("the player's address is kept as data for the script: the privacy-enhanced address with autoplay, the start time 90 and no related videos")
def embed_data(context):
    assert f'data-embed="https://www.youtube-nocookie.com/embed/{VIDEO}?autoplay=1&amp;rel=0&amp;start=90"' in context.html


@then('the player\'s address is kept as data for the script: "{address}"')
def embed_data_is(context, address):
    assert f'data-embed="{address}"' in context.html, re.findall(r'data-embed="[^"]*"', context.html)


@then("the stock rules give an Instagram player a portrait ratio")
def portrait(context):
    assert '.papyrus-video-player[data-provider="instagram"]{aspect-ratio:4 / 5}' in _style(context)


@then("the page loads the video script")
def loads_script(context):
    assert len(re.findall(r'<script src="/_plugins/papyrus-video-v1\.js\?v=[0-9a-f]+"></script>', context.html)) == 1
    assert "_plugins/papyrus-video-v1.js" in context.site.tree


@then("the page mentions no picture host, no frame and no stream host of the video provider")
def no_hosts(context):
    lowered = context.html.lower()
    found = [host for host in FORBIDDEN_HOSTS if host in lowered]
    assert not found, found
    assert "<iframe" not in lowered


def _without_allowed(html: str) -> str:
    html = re.sub(r'<a [^>]*href="[^"]*"', lambda m: re.sub(r'href="[^"]*"', 'href=""', m.group(0)), html)
    return re.sub(r'data-embed="[^"]*"', 'data-embed=""', html)


@then("the only provider addresses in the page are the plain links to the video and the player address kept as data for the script")
def only_links(context):
    leftover = PROVIDER_ADDRESS.findall(_without_allowed(context.html))
    assert not leftover, leftover
    embeds = re.findall(r'data-embed="([^"]*)"', context.html)
    assert embeds and all(value.startswith("https://www.youtube-nocookie.com/embed/") for value in embeds), embeds


@then("no image, script, stylesheet or link-preload address in the page is on the video provider")
def no_loaders(context):
    for tag in re.findall(r"<(?:img|script|link|source|video|audio|embed|object)\b[^>]*>", context.html, re.I):
        assert not PROVIDER_ADDRESS.search(tag), tag


def _style(context) -> str:
    return "".join(re.findall(r"<style>(.*?)</style>", context.html, re.S))


@then("the stock rules use the media ratio token with 16 by 9 as its fallback")
def ratio(context):
    assert "aspect-ratio:var(--papyrus-media-ratio,16 / 9)" in _style(context)


@then("the stock rules draw the button as a flat shape with no border and colours from the site's tokens")
def flat_button(context):
    css = _style(context)
    rule = re.search(r"\.papyrus-video-play\{[^}]*\}", css).group(0)
    assert "border:0" in rule and "var(--papyrus-media-play-ink" in rule
    assert "var(--papyrus-media-play-bg" in css and "box-shadow" not in css
    assert not re.search(r"border:\s*[1-9]", css) and "border-color" not in css


@then("the button is a real button element and the poster link is hidden once the script has made the button available")
def real_button(context):
    css = _style(context)
    assert "<button type=\"button\" class=\"papyrus-video-play\"" in context.html
    assert ".papyrus-video-play{display:none" in css and ".papyrus-video-player.is-ready .papyrus-video-play{display:flex}" in css
    assert ".papyrus-video-player.is-ready .papyrus-video-link{display:none}" in css


@then('the poster is a placeholder showing the title "{title}"')
def placeholder(context, title):
    assert '<span class="papyrus-video-placeholder" aria-hidden="true"></span>' in context.html
    assert f'<span class="papyrus-video-title">{title}</span>' in context.html
    assert "<picture>" not in re.search(r'<div class="papyrus-video-player".*?</div>', context.html, re.S).group(0)


@then('the figure has the classes "{classes}"')
def figure_classes(context, classes):
    assert f'<figure class="{classes}">' in context.html


@then("the page has {count:d} buttons and the stock rules once and the video script once")
def two_videos(context, count):
    assert context.html.count('class="papyrus-video-play"') == count
    assert context.html.count(".papyrus-video-player{position:relative") == 1
    assert context.html.count("/_plugins/papyrus-video-v1.js") == 1


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
    assert 'class="papyrus-video-play"' not in context.html and "<iframe" not in context.html.lower() and "data-papyrus-video=" not in context.html


@then("the page loads no video script")
def no_script(context):
    assert "papyrus-video" not in re.sub(r'class="[^"]*"', "", context.html)


@then("the site publishes no video script and no content-security-policy fragment")
def nothing_published(context):
    keys = set(context.site.tree)
    assert "_plugins/papyrus-video-v1.js" not in keys and "_config/content-security-policy.txt" not in keys


STORY = "Words only.\n"


@given("the same Story on a site with no embeds setting and on a site with embeds that list no provider")
def same_story_two_sites(context):
    body = '::video{src="https://youtu.be/UytYrhYLOKI" title="T"}\n'
    context.first = _site(context, None, body, True)
    context.second = _site(context, {"providers": []}, body, True)


@then("the two sites publish identical files")
def identical(context):
    assert context.first.tree == context.second.tree


@given("the same Story without a video on a site with embeds off and on a site with embeds on")
def same_story_without_video(context):
    context.first = _site(context, {"providers": []}, STORY, True)
    context.second = _site(context, {"providers": ["youtube"]}, STORY, True)


@then("every page of the two sites is identical")
def pages_identical(context):
    shared = set(context.first.tree) & set(context.second.tree)
    assert shared and all(context.first.tree[key] == context.second.tree[key] for key in shared), [key for key in shared if context.first.tree[key] != context.second.tree[key]]


@then("the site with embeds on publishes two more files: the video script and the content-security-policy fragment")
def two_more(context):
    assert set(context.second.tree) - set(context.first.tree) == {"_plugins/papyrus-video-v1.js", "_config/content-security-policy.txt"}
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


# ------------------------------------------------------------------ the script

@when("the video script is run against a minimal page")
def run_script(context):
    context.script = subprocess.run(["node", str(REPO_ROOT / "scripts" / "test-papyrus-video.cjs")], capture_output=True, text=True, cwd=REPO_ROOT)


@then("it passes: nothing is framed before a click, a click, Enter and Space each frame the player once, the start time is kept and an address that is not a registered provider's player is refused")
def script_passes(context):
    assert context.script.returncode == 0, context.script.stdout + context.script.stderr
    assert "papyrus-video-v1.js: ok" in context.script.stdout


@then("the script accepts exactly the player addresses of the registry")
def script_prefixes(context):
    from papyrus_content.projection.standard.projector import ASSET_DIRECTORY

    script = (ASSET_DIRECTORY / "papyrus-video.js").read_text(encoding="utf-8")
    listed = re.search(r"EMBED_PREFIXES = \[(.*?)\];", script, re.S).group(1)
    assert re.findall(r'"([^"]+)"', listed) == [spec.embed_prefix for spec in REGISTRY.values()]


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


# ------------------------------------------------------------------ capturing posters

class FakeStore:
    def __init__(self, existing=()):
        self.existing, self.puts = set(existing), []

    def exists(self, key):
        return key in self.existing

    def put(self, key, local, *, content_type, sha256):
        self.puts.append((key, content_type, Path(local).read_bytes()))
        self.existing.add(key)
        return "uploaded"


def _http(context):
    context.asked = []

    def http(address):
        context.asked.append(address)
        if context.youtube == "refuses":
            raise Unreachable("ConnectionResetError: refused")
        if context.youtube == "grey":
            return Response(404, "image/jpeg", jpeg((120, 90)))
        return Response(200, "image/jpeg", jpeg())

    return http


def _story(context, body, *, youtube, existing=()):
    context.body, context.youtube, context.store = body, youtube, FakeStore(existing)


def _video_line(identifier: str) -> str:
    return f'::video{{src="https://youtu.be/{identifier}" title="Video {identifier}" credit="Example Channel"}}'


@given('a Story whose current text has a video "{identifier}" and YouTube answers with a real thumbnail')
def story_real(context, identifier):
    _story(context, _video_line(identifier) + "\n", youtube="real")


@given('a Story whose current text has a video "{identifier}" whose poster is already stored')
def story_stored(context, identifier):
    _story(context, _video_line(identifier) + "\n", youtube="real", existing={f"media/assets/video-posters/youtube-{identifier}.jpg"})


@given('a Story whose current text has a video "{identifier}" and YouTube answers with a grey stand-in')
def story_grey(context, identifier):
    _story(context, _video_line(identifier) + "\n", youtube="grey")


@given("a Story whose current text has {count:d} different videos and YouTube refuses this connection")
def story_refused(context, count):
    ids = ["aaaaaaaaaa" + chr(ord("a") + index) for index in range(count)]
    _story(context, "\n\n".join(_video_line(identifier) for identifier in ids) + "\n", youtube="refuses")


@given("a Story whose current text shows a ::video line only inside a code fence")
def story_fenced(context):
    _story(context, "```\n" + _video_line(VIDEO) + "\n```\n", youtube="real")


def _run_capture(context, flags):
    http = _http(context)
    output = io.StringIO()
    row = {"id": "v1", "bodyMarkus": context.body}
    with patch("papyrus_content.story_reporting.current_story_version", return_value=row):
        context.status = stories_capture_video_posters(
            ["--story", "s1", *flags], client=object(), store=context.store, out=output, fetch=lambda address: fetch_thumbnail(address, http)
        )
    context.output = output.getvalue()


@when('I run "stories capture-video-posters" for that Story')
def run_capture(context):
    _run_capture(context, [])


@when('I run "stories capture-video-posters" for that Story with "{flags}"')
def run_capture_with(context, flags):
    _run_capture(context, flags.split())


@then('the thumbnail was asked for at "{address}"')
def asked_for(context, address):
    assert context.asked == [address], context.asked


@then('the picture was stored under "{key}"')
def stored_under(context, key):
    [(stored_key, content_type, data)] = context.store.puts
    assert stored_key == key and content_type == "image/jpeg" and data[:2] == b"\xff\xd8"


@then("the command says it stored the poster")
def says_stored(context):
    assert "\tstored\t" in context.output and context.status == 0, context.output


@given('a Story whose current text has an Instagram video "{identifier}" with no poster')
def story_instagram(context, identifier):
    _story(context, f'::video{{src="https://www.instagram.com/reel/{identifier}/" title="A reel" credit="Example Troupe"}}\n', youtube="real")


@given('a Story whose current text has a YouTube video "{identifier}" that names its own poster')
def story_own_poster(context, identifier):
    _story(context, f'::video{{src="https://youtu.be/{identifier}" title="A film" credit="Example" poster="/assets/own.jpg"}}\n', youtube="real")


@then("the command says the video needs a poster")
def says_needs(context):
    assert "\tneeds_poster\t" in context.output, context.output


@then("the command says the video has its own poster")
def says_own(context):
    assert "\town_poster\t" in context.output, context.output


@then("the video provider was not asked")
def not_asked(context):
    assert context.asked == [], context.asked


@then("the command says the poster was already there")
def says_already(context):
    assert "\talready_have\t" in context.output, context.output


@then("nothing was stored")
def nothing_stored(context):
    assert context.store.puts == []


@then("the command says it would fetch the poster")
def says_would(context):
    assert "\twould_fetch\t" in context.output, context.output


@then("the command says there is no poster for the video")
def says_none(context):
    assert "\tnone\t" in context.output, context.output


@then("the command stopped with status 3 after 3 refusals")
def stopped(context):
    assert context.status == 3 and len(context.asked) == 3, (context.status, context.asked)


@then("the command reports no videos")
def reports_none(context):
    assert "0 video(s)" in context.output and "no videos" in context.output, context.output
