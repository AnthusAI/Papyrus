"""A backend deploy gives older rows their language (features_backend/deploy-item-languages.feature).

The real post-deploy task of the content-actions function (``run_deploy_render_task``) runs against the in-memory fake CMS, a standard projector
built from a written projection.json and a recording site store. Only what reaches AWS is replaced: the publication record, the publish jobs table
and the editorial policies (recorded, to check the order). No network, no model."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.item_language_backfill import DEPLOY_MARKER_KEY  # noqa: E402
from papyrus_content.projection.engine import ProjectionContext, project  # noqa: E402
from papyrus_content.projection.source import PublishedContentSource  # noqa: E402
from papyrus_content.projection.standard.projector import StandardMarkusProjector  # noqa: E402
from papyrus_content.publishing import project_item_to_published, published_item_id_for  # noqa: E402
from fake_client import FakeAuthoringClient  # noqa: E402
from projection_fixtures import RecordingWriter  # noqa: E402

PROJECTION = {"site": {"name": "Example", "productionUrl": "https://example.test"}, "urls": {"style": "directory", "sections": {"articles": {"base": "articles", "label": "Articles"}}},
              "environment": {"guard": False}}
STORIES = ("alpha", "bravo", "charlie")
OLD = "2026-10-01T00:00:00Z"


def _handler():
    path = REPO_ROOT / "amplify/functions/content-actions/handler.py"
    specification = importlib.util.spec_from_file_location("content_actions_handler_item_languages", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class FailingOnce(FakeAuthoringClient):
    """The fake CMS, with one write that fails the first time (a throttle, a timeout)."""

    fail_on_update: int | None = None

    def update_record(self, model_name, payload):
        if self.fail_on_update is not None:
            self.fail_on_update -= 1
            if self.fail_on_update == 0:
                self.fail_on_update = None
                raise RuntimeError("throttled")
        super().update_record(model_name, payload)


def _old_site(work: Path):
    client = FailingOnce()
    items, published = client.tables.setdefault("Item", {}), client.tables.setdefault("PublishedItem", {})
    for slug in STORIES:   # written straight into the tables, as rows from before the fields were: no language, no group
        first = {"id": f"{slug}-v1", "lineageId": slug, "versionNumber": 1, "versionState": "superseded", "type": "article", "slug": slug, "section": "articles",
                 "title": slug.title(), "status": "draft", "updatedAt": OLD, "metadata": {"frontMatterYaml": f"title: {slug.title()}\n"}, "bodyMarkus": "Before.\n"}
        current = {**first, "id": f"{slug}-v2", "versionNumber": 2, "versionState": "current", "status": "published", "bodyMarkus": f"About {slug}.\n"}
        step = {"id": f"{slug}-step", "lineageId": f"{slug}-step", "versionNumber": 1, "versionState": "current", "type": "sub-task", "updatedAt": OLD}
        for row in (first, current, step):
            items[row["id"]] = copy.deepcopy(row)
        row, _media = project_item_to_published({**current, "language": "en", "languageGroupId": slug}, [], published_at=OLD, version_published_at=OLD,
                                                version_published_by="t", version_number=1)
        row.pop("language"), row.pop("languageGroupId")
        published[row["id"]] = row
    static = work / "web"
    static.mkdir(parents=True, exist_ok=True)
    (static / "projection.json").write_text(json.dumps(PROJECTION), encoding="utf-8")
    store = RecordingWriter(work / "site")
    projector = StandardMarkusProjector.from_static_directory(static, environ={})
    return client, store, ProjectionContext(source=PublishedContentSource(client), projector=projector, writer=store, keep_state=True)


@given("a site whose Stories and published pages were all written before rows carried a language")
def step_site(context):
    work = tempfile.TemporaryDirectory()
    context.add_cleanup(work.cleanup)
    context.client, context.store, context.projection = _old_site(Path(work.name))
    context.handler = _handler()


@given("the site's editorial settings have no languages")
def step_no_languages(context):
    context.client.tables.setdefault("EditorialCheckSettings", {})["settings"] = {"id": "settings", "settings": json.dumps({"enabled": True})}


@given('the site\'s primary language is "{tag}"')
def step_primary(context, tag):
    context.client.tables.setdefault("EditorialCheckSettings", {})["settings"] = {"id": "settings", "settings": json.dumps({"languages": {"primary": tag, "enabled": [tag]}})}


@given("writing the third row fails once")
def step_failing(context):
    context.client.fail_on_update = 3


def _deploy(context):
    handler, order = context.handler, []
    real_languages, real_render = handler.ensure_item_languages, handler.deploy_render

    def languages(*args, **kwargs):
        order.append("languages written")
        return real_languages(*args, **kwargs)

    def render(*args, **kwargs):
        order.append("render")
        return real_render(*args, **kwargs)

    context.client.calls.clear()
    context.client.updates.clear()
    context.store.operations.clear()
    patches = [
        mock.patch.object(handler, "projection_context", lambda client: context.projection),
        mock.patch.object(handler, "ensure_publication_from_environment", lambda client: None),
        mock.patch.object(handler, "ensure_default_editorial_policies", lambda client: order.append("editorial policies")),
        mock.patch.object(handler, "targeted_invalidation", lambda environ: False),
        mock.patch.object(handler, "publish_jobs_from_environment", lambda: None),
        mock.patch.object(handler, "ensure_item_languages", languages),
        mock.patch.object(handler, "deploy_render", render),
    ]
    for patch in patches:
        patch.start()
    try:
        context.result, context.failure = handler.run_deploy_render_task(context.client), None
    except Exception as error:  # noqa: BLE001 - the scenario checks what a failed deploy left
        context.result, context.failure = None, error
    finally:
        for patch in patches:
            patch.stop()
    context.order = order


@given("the backend was deployed once")
def step_deployed_once(context):
    _deploy(context)
    assert context.failure is None, context.failure


@when("the backend is deployed")
@when("the backend is deployed again")
def step_deploy(context):
    _deploy(context)
    assert context.failure is None, context.failure


@when("the backend is deployed and the deploy fails")
def step_deploy_fails(context):
    _deploy(context)
    assert context.failure is not None


@then('every Item row has the language "{tag}" and its own lineage as its group')
def step_items(context, tag):
    for row in context.client.tables["Item"].values():
        assert row.get("language") == tag and row.get("languageGroupId") == row["lineageId"], row


@then('every published row has the language "{tag}" and its own lineage as its group')
def step_published(context, tag):
    for row in context.client.tables["PublishedItem"].values():
        assert row.get("language") == tag and row.get("languageGroupId") == row["itemLineageId"], row


@then("each row keeps its own update time")
def step_times(context):
    assert all(row["updatedAt"] == OLD for row in context.client.tables["Item"].values())


@then("every published page was rendered")
def step_rendered(context):
    written = {key for _operation, key in context.store.operations}
    for slug in STORIES:
        assert f"articles/{slug}/index.html" in written, sorted(written)


@then("the steps ran in the order: languages written, editorial policies, render")
def step_order(context):
    assert context.order == ["languages written", "editorial policies", "render"], context.order


@then("the Items were read through the version-state index and each published row by its id")
def step_reads(context):
    reads = [call for call in context.client.calls if call[0] in ("list_by_index", "list") and call[1] != "PublishedItemSummary"]
    before_render = context.client.calls[: next(index for index, call in enumerate(context.client.calls) if call[0] == "update")]
    assert not [call for call in before_render if call[0] == "list"], before_render
    assert {call[1] for call in before_render if call[0] == "list_by_index"} == {"itemLanguageFieldsByVersionState"}, reads
    looked_up = {call[2] for call in before_render if call[0] == "get" and call[1] == "PublishedItem"}
    assert looked_up == {published_item_id_for(slug) for slug in STORIES}, looked_up


@then("no checklist step was looked up as a published row")
def step_no_steps(context):
    assert not [call for call in context.client.calls if call[0] == "get" and call[1] == "PublishedItem" and "step" in call[2]]


@then("no row was written")
def step_nothing(context):
    assert context.client.updates == [], context.client.updates


@then("the language step read only its marker")
def step_marker_only(context):
    first_render_read = next((index for index, call in enumerate(context.client.calls) if call[0] == "list" and call[1] in ("PublishedItem", "PublishedItemSummary")),
                             len(context.client.calls))
    before = context.client.calls[:first_render_read]
    assert not [call for call in before if call[0] == "list_by_index"], before
    assert context.result and context.store.get(DEPLOY_MARKER_KEY) is not None


@then("nothing was rendered and no page of the site changed")
def step_no_render(context):
    assert "render" not in context.order and not [key for operation, key in context.store.operations if operation == "put"], context.store.operations


@then("no marker was left")
def step_no_marker(context):
    assert context.store.get(DEPLOY_MARKER_KEY) is None


@when("a published row without a language is written later")
def step_late_row(context):
    row = copy.deepcopy(context.client.tables["PublishedItem"][published_item_id_for("alpha")])
    row.pop("language"), row.pop("languageGroupId")
    context.client.tables["PublishedItem"][row["id"]] = row


@when("that Story is projected")
def step_project_late(context):
    try:
        project(context.projection, "alpha-v2")
        context.refusal = None
    except Exception as error:  # noqa: BLE001 - the refusal is the point
        context.refusal = str(error)


@then('the late projection is refused naming "{text}"')
def step_refused_late(context, text):
    assert context.refusal and text in context.refusal, context.refusal


@then("a later deploy does not write it")
def step_not_written(context):
    _deploy(context)
    assert context.client.updates == []
    assert "language" not in context.client.tables["PublishedItem"][published_item_id_for("alpha")]
