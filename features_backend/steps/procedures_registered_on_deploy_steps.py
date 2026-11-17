from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content import model_attachments, procedure_deploy, procedure_registry  # noqa: E402

SITE_PROCEDURE = """Procedure {
    input = {
        proceeding = field.string{required = true, description = "Proceeding number"}
    },
    output = {
        title = field.string{required = true}
    },
    function(input)
        return {title = input.proceeding}
    end
}
"""


def header(kind: str) -> str:
    return f"-- papyrus-procedure-kind: {kind}\n"


class FakeBackend:
    """The few operations registration uses, over a dict; counts every write."""

    def __init__(self):
        self.records: dict[tuple[str, str], dict] = {}
        self.writes = 0
        self.uploads: list[tuple[str, str]] = []

    def get_record(self, model, record_id):
        return self.records.get((model, record_id))

    def create_record(self, model, payload):
        assert (model, payload["id"]) not in self.records
        self.writes += 1
        self.records[(model, payload["id"])] = dict(payload)

    def update_record(self, model, payload):
        self.writes += 1
        self.records[(model, payload["id"])].update(payload)

    def list_by_index(self, index, key, limit=100):
        return [record for (model, _), record in self.records.items() if model == "ProcedureVersion" and record["procedureId"] == key]

    def versions_of(self, kind):
        return sorted((r for (m, _), r in self.records.items() if m == "ProcedureVersion" and r["procedureKey"] == kind), key=lambda r: r["versionNumber"])

    def definition_of(self, kind):
        return next(r for (m, _), r in self.records.items() if m == "ProcedureDefinition" and r["procedureKey"] == kind)


def _patches(context):
    """Registration with no network: the corpus key and the attachment upload are replaced, and an edited core source is served for its kind."""
    edited = getattr(context, "edited_sources", {})
    real_source = procedure_registry.procedure_source_for_kind

    def source_for(kind):
        return edited.get(kind, real_source(kind))

    def upload(client, attachment, body):
        client.writes += 1
        client.uploads.append((attachment["ownerId"], attachment["sortKey"]))
        return attachment

    return [
        mock.patch("papyrus_content.steering.default_corpus_key", lambda *a, **k: "example-corpus"),
        mock.patch.object(procedure_deploy, "procedure_source_for_kind", source_for),
        mock.patch.object(model_attachments, "upload_attachment_body", upload),
    ]


def _core_plans(context):
    entered = [patch.start() for patch in _patches(context)]
    try:
        return procedure_deploy.core_plans()
    finally:
        mock.patch.stopall()
        del entered


def _run(context, action, *, site_registry=None):
    context.error = None
    context.results = None
    entered = [patch.start() for patch in _patches(context)]
    try:
        plans = procedure_deploy.plan_deploy(site_registry=site_registry, root=getattr(context, "site_root", Path(".")))
        if action == "apply":
            context.results = procedure_deploy.apply_deploy(context.backend, plans)
        elif action == "plan":
            context.results = procedure_deploy.plan_statuses(context.backend, plans)
        else:
            context.results = procedure_deploy.check_drift(context.backend, plans)
    except procedure_deploy.ProcedureDeployError as error:
        context.error = str(error)
    finally:
        mock.patch.stopall()
        del entered


def _by_kind(context):
    return {entry["procedureKey"]: entry for entry in context.results}


def _site_registry(context, kind, *, overrides=(), declares=None, write_file=True):
    root = Path(tempfile.mkdtemp(prefix="papyrus-site-procedures-"))
    context.tmp_dirs.append(root)
    context.site_root = root
    if write_file:
        (root / "procedures").mkdir()
        (root / "procedures" / "site.tac").write_text(header(declares or kind) + SITE_PROCEDURE)
    registry = {"version": 1, "procedures": {kind: "procedures/site.tac"}}
    if overrides:
        registry["overrides"] = list(overrides)
    path = root / procedure_deploy.SITE_REGISTRY_FILE
    path.write_text(json.dumps(registry))
    context.site_registry = path


@given("a site backend with no procedures registered")
def step_empty(context):
    context.backend = FakeBackend()


@given("a site backend where the core procedures were registered by an earlier deploy")
def step_registered(context):
    context.backend = FakeBackend()
    _run(context, "apply")
    assert context.error is None, context.error
    context.backend.writes = 0
    context.backend.uploads.clear()


@given('the source of the kind "{kind}" differs from what is published')
def step_edited(context, kind):
    context.edited_sources = {kind: procedure_registry.procedure_source_for_kind(kind) + "-- edited\n"}


@given('the kind "{kind}" has never been registered')
def step_never(context, kind):
    for key in [key for key, record in context.backend.records.items() if record.get("procedureKey") == kind]:
        del context.backend.records[key]


@given('a site backend holding the starter version "{version_id}" of "{kind}"')
def step_starter(context, version_id, kind):
    context.backend = FakeBackend()
    definition_id = "procedure-definition-" + kind.replace(".", "-")
    context.backend.records[("ProcedureDefinition", definition_id)] = {"id": definition_id, "procedureKey": kind, "currentVersionId": version_id}
    context.backend.records[("ProcedureVersion", version_id)] = {
        "id": version_id, "procedureId": definition_id, "procedureKey": kind, "versionNumber": 1, "status": "published", "isCurrent": True}


@given('a site repository that lists the kind "{kind}" in its papyrus-site-procedures.json')
def step_site(context, kind):
    context.backend = FakeBackend()
    _site_registry(context, kind)


@given('a site repository that lists the kind "{kind}" and names it under "overrides"')
def step_site_override(context, kind):
    context.backend = FakeBackend()
    _site_registry(context, kind, overrides=[kind])


@given('a site repository whose file for "{kind}" declares the kind "{declared}"')
def step_site_other_kind(context, kind, declared):
    context.backend = FakeBackend()
    _site_registry(context, kind, declares=declared)


@given('a site repository that lists the kind "{kind}" with a file that does not exist')
def step_site_missing(context, kind):
    context.backend = FakeBackend()
    _site_registry(context, kind, write_file=False)


@when("the deploy registers the core procedures")
def step_register(context):
    _run(context, "apply")


@when("the deploy registers the core procedures again")
def step_register_again(context):
    _run(context, "apply")


@when("the deploy registers the core procedures and the site's procedures")
def step_register_site(context):
    _run(context, "apply", site_registry=context.site_registry)


@when("the deploy plans the core procedures without applying them")
def step_plan(context):
    _run(context, "plan")


@when("the drift check runs")
def step_check(context):
    _run(context, "check")


@then("all {count:d} core kinds are published with a version whose id carries the digest of the packaged source and its metadata")
def step_all_published(context, count):
    assert context.error is None, context.error
    kinds = procedure_registry.registered_kinds()
    assert len(kinds) == count, kinds
    plans = {plan["procedureKey"]: plan for plan in _core_plans(context)}
    for kind in kinds:
        version = context.backend.records[("ProcedureVersion", plans[kind]["versionId"])]
        assert version["status"] == "published" and version["isCurrent"], kind
        assert context.backend.definition_of(kind)["currentVersionId"] == version["id"], kind
        assert version["id"].endswith(plans[kind]["contentDigest"]), kind


@then("each definition carries the title, category and description from the registry's metadata")
def step_definition_metadata(context):
    for kind in procedure_registry.registered_kinds():
        metadata = procedure_registry.procedure_metadata_for_kind(kind)
        definition = context.backend.definition_of(kind)
        assert (definition["title"], definition["category"], definition["description"]) == (
            metadata["title"], metadata["category"], metadata["description"]), kind


@then("each version carries the parameter schema and defaults from the registry's metadata")
def step_version_metadata(context):
    for kind in procedure_registry.registered_kinds():
        metadata = procedure_registry.procedure_metadata_for_kind(kind)
        version = context.backend.versions_of(kind)[-1]
        assert json.loads(version["parameterSchema"]) == metadata["parameterSchema"], kind
        stored = json.loads(version["defaults"])
        assert set(stored) == set(metadata["defaults"]), kind
        for name, value in metadata["defaults"].items():
            assert str(value).startswith("$") or stored[name] == value, (kind, name)


@then("every kind is reported unchanged")
def step_all_unchanged(context):
    assert context.error is None, context.error
    assert {entry["status"] for entry in context.results} == {"unchanged"}, context.results


@then("nothing was written to the backend")
def step_no_writes(context):
    assert context.backend.writes == 0, f"{context.backend.writes} writes"


@then('the kind "{kind}" is reported registered as version {number:d} and the other {others:d} are unchanged')
def step_registered_version(context, kind, number, others):
    assert context.error is None, context.error
    results = _by_kind(context)
    assert results[kind]["status"] == "registered" and results[kind]["versionNumber"] == number, results[kind]
    assert sorted(entry["status"] for key, entry in results.items() if key != kind) == ["unchanged"] * others


@then('the kind "{kind}" is reported registered as version {number:d}')
def step_registered_only(context, kind, number):
    assert context.error is None, context.error
    result = _by_kind(context)[kind]
    assert result["status"] == "registered" and result["versionNumber"] == number, result


@then('the first version of "{kind}" is archived and the definition points at the new version')
def step_archived(context, kind):
    versions = context.backend.versions_of(kind)
    assert [v["status"] for v in versions] == ["archived", "published"], versions
    assert context.backend.definition_of(kind)["currentVersionId"] == versions[-1]["id"]


@then("the starter version is archived")
def step_starter_archived(context):
    starter = context.backend.records[("ProcedureVersion", "procedure-version-newsroom-research-explorer-1")]
    assert starter["status"] == "archived" and not starter["isCurrent"]


@then('the kind "{kind}" is reported changed and the other {others:d} are reported unchanged')
def step_planned(context, kind, others):
    assert context.error is None, context.error
    results = _by_kind(context)
    assert results[kind]["status"] == "changed", results[kind]
    assert sorted(entry["status"] for key, entry in results.items() if key != kind) == ["unchanged"] * others


@then("the check passes")
def step_check_passes(context):
    assert context.error is None, context.error
    assert {entry["status"] for entry in context.results} == {"unchanged"}


@then('the check fails and names "{changed}" as changed and "{missing}" as missing')
def step_check_fails(context, changed, missing):
    assert context.error is not None, "the check passed"
    assert f"{changed} is changed" in context.error and f"{missing} is missing" in context.error, context.error


@then('the kind "{kind}" is published under the category "{category}"')
def step_site_published(context, kind, category):
    assert context.error is None, context.error
    assert context.backend.definition_of(kind)["category"] == category
    assert context.backend.versions_of(kind)[-1]["status"] == "published"


@then("all {count:d} core kinds are published")
def step_core_published(context, count):
    core = procedure_registry.registered_kinds()
    assert len(core) == count
    for kind in core:
        assert context.backend.versions_of(kind)[-1]["status"] == "published", kind


@then('the deploy stops and says the site kind "{kind}" shadows a core kind')
def step_shadow(context, kind):
    assert context.error is not None and f"The site kind {kind} shadows a core kind" in context.error, context.error


@then('the kind "{kind}" is published from the site\'s source on the core definition')
def step_override(context, kind):
    assert context.error is None, context.error
    definition = context.backend.definition_of(kind)
    assert definition["id"] == "procedure-definition-" + kind.replace(".", "-")
    version = context.backend.records[("ProcedureVersion", definition["currentVersionId"])]
    assert version["status"] == "published"
    assert version["changelog"].startswith("Registered from site.tac"), version["changelog"]


@then('the core source of "{kind}" is not written')
def step_core_not_written(context, kind):
    core_version = next(plan["versionId"] for plan in _core_plans(context) if plan["procedureKey"] == kind)
    assert ("ProcedureVersion", core_version) not in context.backend.records
    assert len(context.backend.versions_of(kind)) == 1


@then('the deploy stops and says the file declares "{declared}", not "{kind}"')
def step_wrong_kind(context, declared, kind):
    assert context.error is not None and f"declares the kind {declared}, not {kind}" in context.error, context.error
    assert context.backend.writes == 0


@then("the deploy stops and names the missing file")
def step_missing_file(context):
    assert context.error is not None and "procedures/site.tac" in context.error and "is not there" in context.error, context.error
    assert context.backend.writes == 0


@when("the registry loses the metadata of the first kind")
def step_lose_metadata(context):
    context.registry = {**context.registry, "procedureMetadata": {"demo.second": _METADATA}}


@when("the registry gains metadata for a kind it does not list")
def step_extra_metadata(context):
    context.registry = {**context.registry, "procedureMetadata": {**context.registry["procedureMetadata"], "demo.third": _METADATA}}


@then("the check names the first kind as having no metadata")
def step_no_metadata(context):
    assert any("no metadata for the kind demo.first" in problem for problem in procedure_registry.check_procedure_registry(context.registry, context.sources))


@then("the check names that kind as metadata for an unregistered kind")
def step_unregistered_metadata(context):
    assert any("metadata for demo.third, which is not a registered kind" in problem
               for problem in procedure_registry.check_procedure_registry(context.registry, context.sources))


_METADATA = {"title": "Demo", "category": "newsroom", "description": "A demo.", "parameterSchema": {"type": "object"}, "defaults": {}}
