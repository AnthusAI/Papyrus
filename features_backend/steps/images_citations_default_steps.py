from __future__ import annotations

import json
import os
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

from papyrus_content.markus_renderer.body_features import install_body_features  # noqa: E402
from papyrus_content.markus_renderer.derive import derive_body  # noqa: E402
from papyrus_content.projection.standard.projector import StandardMarkusProjector  # noqa: E402
from papyrus_content.renditions import DEFAULT_IMAGE_SETTINGS, DirectoryRenditionStore, make_renditions  # noqa: E402
from procedures.newsroom.tests.based_images_support import CHART, PICTURES, picture  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import static_directory  # noqa: E402
from features_backend.steps.content_actions_steps import call_action, draft_payload, load_handler_module  # noqa: E402

FRONT_MATTER = (
    "title: Hello\ncitations:\n  smith:\n    type: book\n    title: A Book Cited\n"
    "    author: [{family: Smith, given: Ann}]\n    issued: {date-parts: [[2020]]}\n"
)
PICTURE = f'::image{{src="{CHART}" alt="A chart"}}\n'
CITING = "As shown [@smith].\n\n::citations\n"
BODIES = {
    "with only words": "Only words here.\n",
    "with a picture": PICTURE,
    "that cites a source": CITING,
    "with a picture and a citation": PICTURE + "\n" + CITING,
}
SETTINGS = {
    "declares no images and no citations": {},
    "declares nothing": {},
    "turns images off": {"images": False},
    "turns citations off": {"citations": False},
    "turns images and citations off": {"images": False, "citations": False},
    "declares its own image widths": {"images": {"widths": [200, 400], "formats": ["webp"]}},
}
BASE = {"site": {"name": "Example", "productionUrl": "https://example.com"}, "urls": {"style": "directory"}}


class Site:
    def __init__(self, declared: dict) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="images-default-"))
        self.declared = declared
        self.static = static_directory(self.work, {**BASE, **declared})
        self.store = DirectoryRenditionStore(self.work / "site-store")
        self.has_store = True

    def projector(self) -> StandardMarkusProjector:
        return StandardMarkusProjector.from_static_directory(
            self.static, renditions=self.store if self.has_store else None, environ={"PAPYRUS_SITE_PUBLIC_URL": ""}
        )

    def upload_pictures(self) -> None:
        settings = self.projector()._settings.images or DEFAULT_IMAGE_SETTINGS
        for index, (source, size) in enumerate(PICTURES.items()):
            make_renditions(settings, self.store, source, picture(size, 40 + 30 * index))

    def render(self, body: str) -> str:
        return self.projector()._fragment(f"---\n{FRONT_MATTER}---\n{body}", 1)

    def renders(self, body: str) -> bool:
        try:
            self.render(body)
        except Exception:  # noqa: BLE001 - a page that cannot be rendered does not go live
            return False
        return True


def new_site(context, declares: str) -> Site:
    site = Site(SETTINGS[declares])
    context.add_cleanup(shutil.rmtree, site.work, True)
    context.site = site
    return site


@given("a Papyrus site whose projection.json {declares}")
def given_site(context, declares: str) -> None:
    if declares in SETTINGS:
        new_site(context, declares)
        context.sites = getattr(context, "sites", []) + [context.site]
    else:
        raise AssertionError(f"unknown site description: {declares}")


@given("the Story's pictures are uploaded to the site's media store")
def uploaded(context) -> None:
    context.site.upload_pictures()


@given("the site has no media store")
def no_store(context) -> None:
    context.site.has_store = False


def save(context, body: str) -> None:
    site = context.site
    context.body = body
    context.derivation = derive_body(FRONT_MATTER, body, site.projector().body_features())


@when("the Story with a picture and a citation is saved")
def save_picture_and_citation(context) -> None:
    save(context, BODIES["with a picture and a citation"])


@when("a Story that cites a source is saved")
def save_citing(context) -> None:
    save(context, BODIES["that cites a source"])


@when("a Story with only words is saved")
def save_words(context) -> None:
    save(context, BODIES["with only words"])


@when("the Story {kind} is saved")
def save_kind(context, kind: str) -> None:
    save(context, BODIES[kind])


@then("the save is accepted")
def accepted(context) -> None:
    assert context.derivation.ok, [error.message for error in context.derivation.errors]


@then('the save is refused with "{text}"')
def refused_with(context, text: str) -> None:
    assert not context.derivation.ok
    assert any(text in error.message for error in context.derivation.errors), [error.message for error in context.derivation.errors]


@then('the save is refused with "{text}" and the note that the site turned images off')
def refused_images_off(context, text: str) -> None:
    refused_with(context, text)
    refused_with(context, "turned images off")


@then("the save is refused with the note that the site turned citations off")
def refused_citations_off(context) -> None:
    refused_with(context, "turned citations off")


@then("rendering the Story would have been refused as well")
def render_refused(context) -> None:
    assert not context.site.renders(context.body)


@then("the save verdict is the verdict of rendering the Story")
def same_verdict(context) -> None:
    assert context.derivation.ok == context.site.renders(context.body), (context.derivation.ok, [e.message for e in context.derivation.errors])


@when("the site renders the Story")
def render(context) -> None:
    context.page = context.site.render(context.body)


@then("the page shows the chart as a responsive picture from the site's renditions")
def picture_shown(context) -> None:
    assert "<picture" in context.page and re.search(r"assets/responsive/assets/[^\"]*chart-\d+\.webp", context.page), context.page


@then("the page lists the source the Story cites")
def source_listed(context) -> None:
    assert "A Book Cited" in context.page


@when("both render a Story with only words and a link to a picture elsewhere")
def render_both(context) -> None:
    body = "Only words and ![a picture](https://example.com/a.png).\n"
    context.pages = [site.render(body) for site in context.sites]


@then("the two pages are identical")
def identical(context) -> None:
    assert len(context.pages) == 2 and context.pages[0] == context.pages[1]


# ------------------------------------------------------------------ the newsroom's save


@given("the content actions of a Papyrus site that turned images off")
def content_actions(context) -> None:
    site = Site({"images": False})
    context.add_cleanup(shutil.rmtree, site.work, True)
    saved = {name: os.environ.get(name) for name in ("PAPYRUS_PUBLICATION_KIND", "PAPYRUS_SITE_STATIC_DIR")}
    os.environ["PAPYRUS_PUBLICATION_KIND"] = "s3-projection"
    os.environ["PAPYRUS_SITE_STATIC_DIR"] = str(site.static)

    def restore() -> None:
        install_body_features(None)
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    context.add_cleanup(restore)
    context.client = FakeAuthoringClient()
    context.handler_module = load_handler_module()   # installs the projector's features as the save's


@when("the editor saves a Story with a picture as a draft")
def editor_saves(context) -> None:
    context.response = call_action(context, "saveItemDraft", draft_payload(frontMatterYaml=FRONT_MATTER, bodyMarkus=PICTURE))


@then("the save response fails because the site turned images off")
def response_fails(context) -> None:
    assert context.response["ok"] is False
    assert any("turned images off" in error["message"] for error in context.response["errors"]), context.response


@then("nothing is saved")
def nothing_saved(context) -> None:
    assert not context.client.list_by_index("itemBySlug", "hello")



# ------------------------------------------------------------------ the post-deploy render

import subprocess  # noqa: E402

from papyrus_content.projection.deploy_render import deploy_render  # noqa: E402
from papyrus_content.projection.directory_source import DirectoryContentSource  # noqa: E402
from papyrus_content.projection.engine import ProjectionContext, project_all  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402

STORY = "---\ntitle: {title}\ndate: '2026-10-01'\n---\n\n{body}\n"


class FailingWriter(LocalDirectoryWriter):
    def put(self, key, body, **kwargs):
        raise OSError("the site bucket is not reachable")


def deploy_context(context, writer_class=LocalDirectoryWriter) -> ProjectionContext:
    site = context.site
    context.content = site.work / "content"
    context.out = site.work / "out"
    context.content.mkdir(exist_ok=True)
    context.writer = writer_class(context.out)
    context.projection = ProjectionContext(
        source=DirectoryContentSource(context.content), projector=site.projector(), writer=context.writer, keep_state=False
    )
    return context.projection


def write_story(context, slug: str, body: str) -> None:
    (context.content / f"{slug}.md").write_text(STORY.format(title=slug.title(), body=body), encoding="utf-8")


@given("three published Stories, one of which has a picture the site cannot render")
def three_stories(context) -> None:
    projection = deploy_context(context)
    write_story(context, "first", "Words.")
    write_story(context, "second", "More words.")
    write_story(context, "bad", "It used to be words only.")
    project_all(projection)   # the pages the site had before this deploy
    context.bad_page_keys = [path.relative_to(context.out).as_posix() for path in context.out.rglob("*") if path.is_file() and "bad" in path.name + path.parent.name]
    assert context.bad_page_keys, "the bad Story had a page before"
    write_story(context, "bad", PICTURE)
    write_story(context, "second", "More words, edited.")
    projection.source = DirectoryContentSource(context.content)   # a source reads its directory once: this deploy sees the edits


@given("the page store fails while the post-deploy render writes")
def failing_store(context) -> None:
    deploy_context(context, FailingWriter)
    write_story(context, "first", "Words.")


@when("the post-deploy render runs")
def run_deploy_render(context) -> None:
    context.render_error = None
    try:
        context.report = deploy_render(context.projection)
    except Exception as error:  # noqa: BLE001 - the scenario asserts on what the deploy would have seen
        context.render_error = error


@then("the render succeeds and writes the two Stories that can be rendered")
def render_succeeds(context) -> None:
    assert context.render_error is None, context.render_error
    assert context.report.ok, context.report.render.errors
    assert "More words, edited" in (context.out / next(k for k in map(str, context.report.render.written) if "second" in k)).read_text(encoding="utf-8")


@then("the report names the Story that could not be rendered and why")
def names_story(context) -> None:
    [failed] = context.report.render.unrenderable
    assert failed["slug"] == "bad" and "Unknown directive 'image'" in failed["error"], failed
    assert context.report.to_dict()["unrenderable"] == [failed]


@then("the drift count the alarm watches is not zero")
def drift_counted(context) -> None:
    assert context.report.drift_count >= 1


@then("the page the bad Story had before is still there")
def old_page_kept(context) -> None:
    assert all((context.out / key).is_file() for key in context.bad_page_keys)


@then("the render fails with the storage error")
def storage_error(context) -> None:
    assert isinstance(context.render_error, OSError) or (context.render_error is None and not context.report.ok)
    assert "not reachable" in str(context.render_error or context.report.render.errors)


# The resource that runs the render in CloudFormation (amplify/publication/reproject-on-deploy.ts)


@given('the deploy token of the previous deploy was "{token}"')
def previous_token(context, token: str) -> None:
    context.old_token = token


def probe(context, token: str, *, function_fails: bool) -> dict:
    event = {
        "RequestType": "Update",
        "ResourceProperties": {"DeployToken": token, "FunctionName": "content-actions", "Task": "deploy-render"},
        "OldResourceProperties": {"DeployToken": context.old_token},
    }
    arguments = {"event": event}
    if function_fails:
        arguments.update(functionError="Unhandled", payload={"errorMessage": "the render function crashed"})
    done = subprocess.run(
        [str(REPO_ROOT / "node_modules/.bin/tsx"), str(REPO_ROOT / "scripts/reproject-handler-probe.ts"), json.dumps(arguments)],
        capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


@when('CloudFormation rolls the render resource back to the token "{token}" and the render function fails')
def rolled_back(context, token: str) -> None:
    context.outcome = probe(context, token, function_fails=True)


@when('CloudFormation updates the render resource to the token "{token}" and the render function fails')
def updated(context, token: str) -> None:
    context.outcome = probe(context, token, function_fails=True)


@then("the resource update succeeds without invoking the render function")
def rollback_succeeds(context) -> None:
    assert context.outcome["ok"] and context.outcome["invoked"] == 0, context.outcome


@then("the resource update fails with the render function's error")
def update_fails(context) -> None:
    assert not context.outcome["ok"] and "the render function crashed" in context.outcome["error"], context.outcome


# ------------------------------------------------------------------ publish checks the page first


@given("the content actions of a Papyrus site that declares no images, whose media store holds no renditions")
def content_actions_empty_store(context) -> None:
    from unittest import mock

    from papyrus_content.projection import runtime

    site = Site({})
    context.add_cleanup(shutil.rmtree, site.work, True)
    projector = site.projector()
    patches = [
        mock.patch.dict(os.environ, {"PAPYRUS_PUBLICATION_KIND": "s3-projection", "PAPYRUS_SITE_STATIC_DIR": str(site.static)}),
        mock.patch.object(runtime, "load_projector", return_value=projector),
    ]
    for patch in patches:
        patch.start()
        context.add_cleanup(patch.stop)
    context.add_cleanup(install_body_features, None)
    context.client = FakeAuthoringClient()
    context.handler_module = load_handler_module()


@then("the save is accepted by the site")
def save_accepted_by_site(context) -> None:
    assert context.response["ok"] is True, context.response
    context.item = context.response["item"]


@when("the editor publishes the saved Story")
def editor_publishes(context) -> None:
    context.response = call_action(context, "publishItem", {"id": context.item["id"]})


@then('the publish response fails with "{code}"')
def publish_fails(context, code: str) -> None:
    assert context.response["ok"] is False and context.response["errors"][0]["code"] == code, context.response


@then("nothing is published")
def nothing_published(context) -> None:
    assert not context.client.list_records("PublishedItem")


# ------------------------------------------------------------------ listings, feeds and the in-place save


@given("a section with an introduction and two good Stories, whose introduction and one more Story are then broken")
def broken_beside_good(context) -> None:
    from procedures.newsroom.tests.test_images_citations_default import broken_beside_good_fixture

    import tempfile

    work = Path(tempfile.mkdtemp(prefix="broken-beside-good-"))
    context.add_cleanup(shutil.rmtree, work, True)
    context.render_context, context.render_out, context.before = broken_beside_good_fixture(work)


@when("the post-deploy render runs on that site")
def run_on_that_site(context) -> None:
    context.report = deploy_render(context.render_context())
    context.written = {p.relative_to(context.render_out).as_posix(): p.read_bytes() for p in context.render_out.rglob("*") if p.is_file()}


@then("the render succeeds")
def succeeds(context) -> None:
    assert context.report.ok, context.report.render.errors


@then("the report names both broken Stories")
def both_named(context) -> None:
    assert sorted(f["slug"] for f in context.report.render.unrenderable) == ["broken", "index"]


@then("the broken Story's own page is as it was")
def broken_page_kept(context) -> None:
    kept = [k for k in context.before if k.startswith("notes/broken/")]
    assert kept and all(context.written[k] == context.before[k] for k in kept)


@then("the section listing, the feeds, the sitemap and the llms files are written with the good Stories")
def listings_written(context) -> None:
    for key in ("notes/index.html", "feed.xml", "atom.xml", "sitemap.xml", "llms.txt", "llms-full.txt"):
        assert key in context.written, key
    assert b"First good Story" in context.written["llms-full.txt"] and b"notes/one" in context.written["feed.xml"]


@then("the section listing has lost only its introduction")
def only_intro_lost(context) -> None:
    listing = context.written["notes/index.html"].decode()
    assert "One" in listing and "Two" in listing and "Welcome to the notes" not in listing


@given("a Story that is published with only words")
def published_story(context) -> None:
    from papyrus_content.publishing import publish_item

    context.response = call_action(context, "saveItemDraft", draft_payload(frontMatterYaml=FRONT_MATTER, bodyMarkus="Only words.\n"))
    context.item = context.response["item"]
    publish_item(context.client, context.item["id"], actor="behave")
    context.published_before = context.client.get_record("Item", context.item["id"])["bodyMarkus"]


@when("the editor saves that published Story in place with a picture")
def save_in_place(context) -> None:
    context.response = call_action(
        context, "saveItemDraft", draft_payload(id=context.item["id"], frontMatterYaml=FRONT_MATTER, bodyMarkus=PICTURE)
    )


@then('the save response fails with "{code}"')
def save_fails_with(context, code: str) -> None:
    assert context.response["ok"] is False and context.response["errors"][0]["code"] == code, context.response


@then("the published Story is unchanged")
def story_unchanged(context) -> None:
    assert context.client.get_record("Item", context.item["id"])["bodyMarkus"] == context.published_before
