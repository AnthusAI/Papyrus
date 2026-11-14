"""Steps for features_backend/cli-reads-signed-in.feature. Every client is an in-memory fake; nothing leaves the process."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_cli_reads as support  # noqa: E402
from papyrus.operator.errors import OperatorError  # noqa: E402
from papyrus_content import assignments_commands, projection_trigger, publication, steering, story_commands, story_reporting  # noqa: E402

STORIES = {"idea": "a", "reporting": "b", "spiked": "c"}


def _call(context, action):
    context.failure, context.result = None, None
    try:
        context.result = action()
    except (OperatorError, ValueError) as error:
        context.failure = error


@given('the signed-in site has the Reference "{lineage}" in the corpus "{key}"')
def _reference(context, lineage, key):
    context.client = support.Client({"Reference": [support.reference(f"{lineage}-v1", lineage, key)], "KnowledgeCorpus": [support.corpus(key)]})


@given('the signed-in site serves the corpus "{key}" with no References')
def _empty_corpus(context, key):
    context.client = support.Client({"KnowledgeCorpus": [support.corpus(key)]})


def _show(context, reference, key=None):
    cloud, patches = support.backend(context.client)
    with patches[0], patches[1]:
        _call(context, lambda: cloud.show_reference(reference, key))


@when('a signed-in person shows the Reference "{reference}"')
def _show_plain(context, reference):
    _show(context, reference)


@when('a signed-in person asks for the Reference "{reference}" in the corpus "{key}"')
def _show_keyed(context, reference, key):
    _show(context, reference, key)


@then('the shown Reference has the record id "{record}" and the lineage id "{lineage}"')
def _shown(context, record, lineage):
    assert context.failure is None, context.failure
    assert context.result.identifier == record and context.result.extra["lineageId"] == lineage, context.result


@then('the command fails saying the Reference is in the corpus "{actual}", not "{asked}"')
def _wrong_corpus(context, actual, asked):
    assert f"in corpus {actual}, not {asked}" in str(context.failure), context.failure


@then("the command fails saying the Reference was not found")
def _not_found(context):
    assert "Reference not found" in str(context.failure), context.failure


@when('a signed-in person lists the References of the corpus "{key}"')
def _list(context, key):
    context.failure = None
    try:
        context.result = support.list_with(context.client, key)
    except OperatorError as error:
        context.failure = error


@then('the command fails saying the corpus is unknown and the site serves "{served}"')
def _unknown_corpus(context, served):
    assert "Unknown corpus" in str(context.failure) and f"This site serves {served}" in str(context.failure), context.failure


@then("the list is empty and the command succeeds")
def _empty(context):
    assert context.failure is None and context.result == [], (context.failure, context.result)


@then('the corpus key "{given_key}" means the corpus "{key}"')
def _normalised(context, given_key, key):
    assert publication.normalize_corpus_key(given_key) == key


@given('the shipped steering file lists only the corpus "{key}"')
def _shipped(context, key):
    context.steering = {"corpora": [{"key": key, "name": key, "role": "canonical"}]}


@when('a catalog is registered with the corpus key "{key}"')
def _register(context, key):
    _call(context, lambda: publication.resolve_catalog_corpus(context.client, {"corpus-key": key}, lambda path: context.steering))


@then('the catalog registers into the corpus "{key}"')
def _registers(context, key):
    assert context.failure is None and context.result[0]["key"] == key, (context.failure, context.result)


@then('the command fails saying the site\'s corpus is "{key}"')
def _site_corpus(context, key):
    assert f"hosted canonical corpus {key}" in str(context.failure), context.failure


@given("a checkout of the Papyrus source tree that holds a steering file")
def _source_tree(context):
    context.root = _checkout(context, source=True)


def _checkout(context, *, source):
    temporary = tempfile.TemporaryDirectory()
    context.add_cleanup(temporary.cleanup)
    root = Path(temporary.name)
    (root / "corpora").mkdir()
    (root / "corpora" / "papyrus-steering.yml").write_text("x: 1\n")
    if source:
        (root / "pyproject.toml").write_text("")
        (root / "src" / "papyrus_content").mkdir(parents=True)
        (root / "src" / "papyrus").mkdir()
    return root


def _chosen(root):
    with mock.patch.dict("os.environ", {}), mock.patch.object(steering, "PAPYRUS_ROOT", root), \
            mock.patch.object(steering, "resolve_topics_steering_config_path", lambda: "corpora/papyrus-steering.yml"):
        import os
        os.environ.pop("PAPYRUS_STEERING_CONFIG", None)
        return steering.steering_config_chosen_by_site()


@then("the steering file is not treated as chosen by a site")
def _not_chosen(context):
    assert _chosen(context.root) is False


@then("a checkout of a site that holds a steering file does treat it as chosen")
def _site_chosen(context):
    assert _chosen(_checkout(context, source=False)) is True


@given('the signed-in site has the Stories "a" (idea), "b" (reporting) and "c" (spiked)')
def _stories(context):
    context.client = support.stories_client()


def _list_stories(context, flags):
    with mock.patch.object(story_commands, "create_authoring_client", return_value=(context.client, {})):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            _call(context, lambda: story_commands.stories_list(flags))
    context.listed = [line.split("\t")[2] for line in out.getvalue().splitlines()[:-1]]


@when("a signed-in person lists the Stories")
def _list_all(context):
    _list_stories(context, [])


@when('a signed-in person lists the Stories at the stage "{stage}" in the section "{section}"')
def _list_filtered(context, stage, section):
    _list_stories(context, ["--stage", stage, "--section", section])


@then('the Stories listed in order are "{first}" and "{second}"')
def _two(context, first, second):
    assert context.listed[:2] == [first, second] and "c" not in context.listed, context.listed


@then('the only Story listed is "{only}"')
def _one(context, only):
    assert context.listed == [only], context.listed


@given('the signed-in site has the Assignment "{identifier}" held by "{holder}" with one event')
def _assignment(context, identifier, holder):
    context.client = support.Client({
        "Assignment": [{"id": identifier, "status": "open", "assignmentTypeKey": "research.multi", "title": "Look", "queueKey": "q",
                        "sectionKey": "news", "itemLineageId": "a", "assigneeKey": holder}],
        "AssignmentEvent": [{"id": "e1", "assignmentId": identifier, "eventType": "created", "createdAt": "2026-11-01", "toStatus": "open"}]})


@when('a signed-in person shows the Assignment "{identifier}"')
def _show_assignment(context, identifier):
    client = getattr(context, "client", None) or support.Client()
    out = io.StringIO()
    with mock.patch.object(assignments_commands, "create_authoring_client", return_value=(client, {})), contextlib.redirect_stdout(out):
        _call(context, lambda: assignments_commands.assignments_show(["--assignment", identifier]))
    context.output = out.getvalue()


@then("the output gives the status, the Story, who holds it and the event")
def _assignment_output(context):
    assert context.failure is None, context.failure
    for expected in ("\tstatus\topen", "\tstory\ta", "\theld by\tsomeone", "created"):
        assert expected in context.output, context.output


@then("the command fails saying the Assignment was not found")
def _no_assignment(context):
    assert "Assignment not found" in str(context.failure), context.failure


@given('the signed-in site has the section "{section}" titled "{title}"')
def _section(context, section, title):
    context.client = support.Client({"NewsroomSection": [{"id": section, "title": title}]})


@when('a Story is created in the section "{name}"')
def _create(context, name):
    _call(context, lambda: story_reporting.create_story(context.client, title="T", section_key=name, actor="a"))


@then('the Story is stored in the section "{section}"')
def _stored(context, section):
    assert context.failure is None and context.result["section"] == section, (context.failure, context.result)


def _project_unknown(context, belongs):
    context.outputs = {"custom": {"publication": {"kind": projection_trigger.S3_PROJECTION_KIND}}} if belongs is not None else None


@given("a signed-in person has no amplify_outputs.json for the chosen site")
def _no_outputs(context):
    context.outputs, context.belongs = None, True


@given("a signed-in person has the amplify_outputs.json of a different site")
def _other_outputs(context):
    context.outputs, context.belongs = {"custom": {"publication": {"kind": projection_trigger.S3_PROJECTION_KIND}}}, False


def _requested(context):
    from papyrus_content import env
    loader = mock.Mock(side_effect=ValueError("none")) if context.outputs is None else mock.Mock(return_value=context.outputs)
    with mock.patch.dict("os.environ", {}), mock.patch.object(env, "load_amplify_outputs", loader), \
            mock.patch.object(env, "outputs_belong_to_selection", return_value=context.belongs), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True):
        import os
        os.environ.pop(projection_trigger.PUBLICATION_KIND_ENV, None)
        return projection_trigger.projection_requested(), projection_trigger.site_publication()


@then("the publish asks the newsroom to project the page")
def _asks(context):
    assert _requested(context)[0] is True


@then("that file is not used and the publish asks the newsroom to project the page")
def _not_used(context):
    requested, publication_found = _requested(context)
    assert requested is True and publication_found == {}


def _run_references_command(context, name, arguments):
    from papyrus.operator.commands import references as reference_commands
    from papyrus.operator.config import OperatorConfig

    config = OperatorConfig("cloud", None, None, None, None, None, None, None)
    cloud, patches = support.backend(context.client)
    context.failure, context.result = None, None
    with patches[0], patches[1], mock.patch.object(reference_commands, "create_backend", return_value=cloud), contextlib.redirect_stdout(io.StringIO()) as out:
        try:
            getattr(reference_commands, f"run_references_{name}")(config, arguments.split())
        except OperatorError as error:
            context.failure = error
    context.output = out.getvalue()


@when('a signed-in person runs references show with "{arguments}"')
def _run_show(context, arguments):
    _run_references_command(context, "show", arguments)


@when("a signed-in person runs references show with no arguments")
def _run_show_bare(context):
    _run_references_command(context, "show", "")


@when('a signed-in person runs references text with "{arguments}"')
def _run_text(context, arguments):
    _run_references_command(context, "text", arguments)


@then('the command fails with exit code 2 saying "{message}"')
def _exit_two(context, message):
    assert context.failure is not None and context.failure.exit_code == 2 and message in str(context.failure), context.failure


@then('the command prints the Reference with the record id "{record}"')
def _printed(context, record):
    assert context.failure is None and record in context.output, (context.failure, context.output)
