"""Console links (features_backend/cli-console-links.feature), through the real code. The site is an in-memory fake; no network, browser or keychain."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content import console_links, env, site_document, story_commands  # noqa: E402
from papyrus_content.console_links import ConsoleLink  # noqa: E402

class SiteClient(FakeAuthoringClient):
    def safe_list_records(self, model_name):
        return list(self.tables.get(model_name, {}).values())


CONSOLE = "https://newsroom.news.example.test/newsroom"
BUILDERS = {
    "reference": console_links.reference_url, "concept": console_links.concept_url,
    "assignment": console_links.assignment_url, "review": console_links.review_url,
}


def _world(context):
    if getattr(context, "links", None) is None:
        context.links = type("World", (), {})()
        world = context.links
        world.published = {}        # what the signed-in site's site file says
        world.environment = {}
        world.flag = None
        world.client = SiteClient({})
        world.reads = []
        world.out = world.err = ""
        world.failure = None
        world.built = []
        world.url = None
    return context.links


def _story_rows(lineage, slug):
    base = {"lineageId": lineage, "slug": slug, "headline": "A story", "title": "A story", "stage": "reporting", "type": "article"}
    return [{**base, "id": lineage, "versionNumber": 1, "versionState": "superseded", "status": "draft"},
            {**base, "id": f"{lineage}-v2", "versionNumber": 2, "versionState": "current", "status": "draft"}]


@given('the console is at "{address}"')
def console_is_at(context, address):
    world = _world(context)
    world.published = {"console_url": address}
    world.flag = None


@given("the person is signed in to a site that publishes no console address")
def no_console_published(context):
    _world(context).published = {}


@given("no console address is given")
def no_flag(context):
    world = _world(context)
    world.flag = None
    world.environment = {}


@given('the signed-in site publishes the console address "{address}"')
def site_publishes(context, address):
    _world(context).published = {"console_url": address}


@given('the environment names the console address "{address}"')
def environment_names(context, address):
    _world(context).environment = {console_links.CONSOLE_URL_VARIABLE: address}


@given('the site has the story "{lineage}" with the slug "{slug}" at versions 1 and 2, version 2 current')
def site_has_story(context, lineage, slug):
    _world(context).client = SiteClient({"Item": _story_rows(lineage, slug)})


@given('the site has the Reference "{record}" in lineage "{lineage}"')
def site_has_reference(context, record, lineage):
    world = _world(context)
    world.client.tables.setdefault("Reference", {})[record] = {"id": record, "lineageId": lineage, "versionNumber": 1, "versionState": "current"}


@given('the site has the concept "{name}" with the node key "{key}" and the lineage "{lineage}"')
def site_has_concept(context, name, key, lineage):
    world = _world(context)
    world.client.tables.setdefault("SemanticNode", {})[lineage + "-v1"] = {
        "id": lineage + "-v1", "lineageId": lineage, "nodeKey": key, "displayName": name, "label": name, "versionState": "current", "status": "accepted"}


@given('the site has the Assignment "{identifier}"')
def site_has_assignment(context, identifier):
    world = _world(context)
    world.client.tables.setdefault("Assignment", {})[identifier] = {"id": identifier}


def _run_links(world, flags):
    out, err = io.StringIO(), io.StringIO()
    world.failure = None
    reads = world.reads
    published = lambda name: (reads.append(name), world.published.get(name))[1]   # noqa: E731
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            mock.patch.dict(os.environ, world.environment, clear=False), \
            mock.patch.object(env, "site_published", published), \
            mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(world.client, {})):
        os.environ.pop(console_links.CONSOLE_URL_VARIABLE, None) if not world.environment else None
        try:
            console_links.links_command(flags)
        except BaseException as error:  # noqa: BLE001
            world.failure = error
    world.out, world.err = out.getvalue(), err.getvalue()


def _parsed(world) -> dict[str, str]:
    found = {}
    for line in world.out.splitlines():
        parts = line.split("\t")
        if parts[0] == "links" and len(parts) >= 3:
            found.setdefault(parts[1], parts[2])
    return found


@when('the person runs the links command "{command}"')
def person_runs(context, command):
    import shlex

    world = _world(context)
    words = shlex.split(command)
    assert words[:2] == ["papyrus", "links"] or words == ["papyrus", "links"], words
    flags = words[2:]
    if "--console-url" in flags:
        world.flag = flags[flags.index("--console-url") + 1]
    _run_links(world, flags)


@when('the story addresses are built for lineage "{lineage}" and version "{version}"')
def build_story(context, lineage, version):
    world = _world(context)
    world.built = console_links.story_links(CONSOLE, lineage, version)
    world.reads.clear()


@when('the "{kind}" address is built for "{identifier}"')
def build_one(context, kind, identifier):
    world = _world(context)
    world.url = BUILDERS[kind](world.published["console_url"].rstrip("/"), identifier)


@then('the "{kind}" link is "{url}"')
def link_is(context, kind, url):
    world = _world(context)
    found = {link.kind: link.url for link in world.built} if world.built else _parsed(world)
    assert world.failure is None, world.failure
    assert found.get(kind) == url, (found, world.out)


@then('the "{kind}" link is the same as the "{other}" link')
def link_same(context, kind, other):
    found = {link.kind: link.url for link in _world(context).built}
    assert found[kind] == found[other]


@then("the checklist link is said to have no address of its own")
def checklist_note(context):
    [note] = [link.note for link in _world(context).built if link.kind == "checklist"]
    assert "no address of its own" in note, note


@then('the link is "{url}"')
def one_link_is(context, url):
    assert _world(context).url == url, _world(context).url


@then("no site was read and no network call was made")
def nothing_read(context):
    world = _world(context)
    assert world.reads == [] and not world.client.calls, (world.reads, world.client.calls)


@then("the command fails saying the console address is unknown and how to give it")
def fails_unknown(context):
    message = str(_world(context).failure)
    assert "unknown" in message and "--console-url" in message and "PAPYRUS_CONSOLE_URL" in message, message


@then("no link is printed")
def no_link(context):
    world = _world(context)
    assert "links\t" not in world.out, world.out


@then('the link printed is "{url}"')
def link_printed(context, url):
    world = _world(context)
    assert world.failure is None, world.failure
    assert any(line.split("\t")[2] == url for line in world.out.splitlines() if line.startswith("links\t")), world.out


@then("the command fails saying it is not a console address")
def not_console(context):
    assert "Not a console address" in str(_world(context).failure), _world(context).failure


@then('the site file value "{value}" is left out')
def site_file_left_out(context, value):
    assert "console_url" not in site_document.parse(json.dumps({"console_url": value}).encode())


@then('the site file value "{value}" is kept as "{kept}"')
def site_file_kept(context, value, kept):
    assert site_document.parse(json.dumps({"console_url": value}).encode())["console_url"] == kept


@then("the command fails saying the story has no version 9")
def no_version(context):
    assert "has no version 9" in str(_world(context).failure), _world(context).failure


@then("the command fails saying no story was found")
def no_story(context):
    assert "No story found" in str(_world(context).failure), _world(context).failure


@then("the command fails saying at least one item must be named")
def names_nothing(context):
    assert "at least one of --story" in str(_world(context).failure), _world(context).failure


@then('the JSON names the console and one "{kind}" link with its address')
def json_output(context, kind):
    data = json.loads(_world(context).out)
    assert data["ok"] is True and data["console"] == CONSOLE, data
    [link] = data["links"]
    assert link["kind"] == kind and link["url"] == f"{CONSOLE}/needs-me/rr-1", link


# The commands that print an item (a fake site; the write paths are stubbed because only the rows they print are under test).
def _run_command(world, command):
    out = io.StringIO()
    world.failure = None
    client = FakeAuthoringClient({"Item": _story_rows("item-story", "my-story")})
    published = lambda name: world.published.get(name)   # noqa: E731
    record = {"id": "item-story-v3", "lineageId": "item-story", "versionNumber": 3}
    patches = [mock.patch.object(env, "site_published", published),
               mock.patch.object(story_commands, "create_authoring_client", return_value=(client, {})),
               mock.patch.object(story_commands, "print_reminder"),
               mock.patch("papyrus_content.story_triggers.deliver_from_environment")]
    with contextlib.ExitStack() as stack, contextlib.redirect_stdout(out):
        for patch in patches:
            stack.enter_context(patch)
        try:
            if command == "stories create":
                stack.enter_context(mock.patch.object(story_commands, "create_story", return_value={"id": "item-created-v1", "lineageId": "item-created", "type": "article"}))
                story_commands.stories_create(["--title", "A new story"])
            elif command == "stories save-version":
                stack.enter_context(mock.patch.object(story_commands, "save_story_version", return_value=record))
                stack.enter_context(mock.patch.object(story_commands, "_version_author", return_value="ops"))
                story_commands.stories_save_version(["--story", "item-story", "--body", "text", "--reason", "r", "--no-check"])
            elif command == "stories show":
                story_commands.stories_show(["--story", "item-story"])
            elif command == "references show":
                from papyrus.operator.commands.references import run_references_show
                from papyrus.operator.config import OperatorConfig
                from papyrus.operator.output import OperatorRow

                row = OperatorRow(kind="reference", identifier="reference-a-v1", status="accepted", title="T", extra={"lineageId": "reference-a"})
                backend = mock.Mock(show_reference=mock.Mock(return_value=row))
                config = mock.Mock(spec=OperatorConfig, backend="cloud", fixture_root=None)
                stack.enter_context(mock.patch("papyrus.operator.commands.references.create_backend", return_value=backend))
                run_references_show(config, ["reference-a-v1"])
            else:
                raise AssertionError(command)
        except BaseException as error:  # noqa: BLE001
            world.failure = error
    world.out = out.getvalue()


@when('the person runs the "{command}" command')
def runs_command(context, command):
    _run_command(_world(context), command)


@then('a "console" row for the "story" link ends with "{ending}"')
def console_row(context, ending):
    world = _world(context)
    assert world.failure is None, world.failure
    rows = [line.split("\t") for line in world.out.splitlines() if "\tconsole\t" in line]
    assert any(row[3] == "story" and row[4].endswith(ending) for row in rows), world.out


@then('the output has the line "{line}"')
def has_line(context, line):
    world = _world(context)
    assert world.failure is None, world.failure
    assert line in world.out.splitlines(), world.out


@then('the output has a "console" row saying it is unavailable')
def row_unavailable(context):
    rows = [line.split("\t") for line in _world(context).out.splitlines() if "\tconsole\t" in line]
    assert rows and all(row[3] == "unavailable" and "unknown" in row[4] for row in rows), rows


@then("the command succeeded")
def succeeded(context):
    assert _world(context).failure is None, _world(context).failure


@then('the "story" console row is the editor page of the version just saved')
def row_is_version(context):
    rows = [line.split("\t") for line in _world(context).out.splitlines() if "\tconsole\t" in line and "\tstory\t" in line]
    assert rows and rows[0][4].endswith("/articles/item-story-v3"), rows


@then('the "story" console row has no "open=" drawer query')
def row_has_no_drawer(context):
    rows = [line.split("\t") for line in _world(context).out.splitlines() if "\tconsole\t" in line and "\tstory\t" in line]
    assert rows and "open=" not in rows[0][4], rows


@then('a "console" row for the "story-board" link ends with "{ending}"')
def board_row(context, ending):
    rows = [line.split("\t") for line in _world(context).out.splitlines() if "\tconsole\t" in line]
    assert any(row[3] == "story-board" and row[4].endswith(ending) for row in rows), rows


def _note(key):
    from papyrus_content.newsroom_process import STEP_BY_KEY

    note = STEP_BY_KEY[key].note
    assert "Share a review link" in note and "console" in note, note
    return note


@then('the "{key}" step note says to share a review link with the exact version')
def step_note_exact(context, key):
    assert "exact version" in _note(key)


@then('the "{key}" step note says to share a review link')
def step_note(context, key):
    _note(key)


@then("the template version and the step keys are unchanged")
def template_unchanged(context):
    from papyrus_content.newsroom_process import STEPS, TEMPLATE_VERSION

    assert TEMPLATE_VERSION == 4
    assert [step.key for step in STEPS][:7] == ["choose", "direction", "research", "outline", "draft", "fact_check", "copy_edit"]
