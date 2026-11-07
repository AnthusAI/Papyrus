"""papyrus stories lens-check and the deterministic lens checks (features_backend/lens-check.feature). Nothing here calls a model or the network."""

from __future__ import annotations

import io
import json
import shlex
import sys
import tempfile
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content import audience_lenses as lenses  # noqa: E402
from papyrus_content import lens_evidence as evidence  # noqa: E402
from papyrus_content import story_commands  # noqa: E402
from papyrus_content.projection.standard.config import standard_settings_from_mapping  # noqa: E402
from papyrus_content.projection.standard.environment import resolve_environment  # noqa: E402

LINEAGE = "story-1"
NOW = "2026-11-07T09:00:00.000000Z"
ORIGIN = "https://example.test"
DEFAULT_FRONT = "title: Board refuses\n"


def state(context) -> dict:
    if not hasattr(context, "lens"):
        context.lens = {"front": DEFAULT_FRONT, "body": "", "stage": "copywriting", "site": None, "settings": None, "environ": {}, "fault": False, "title": None}
    return context.lens


def row_of(lens: dict) -> dict:
    metadata = {"frontMatterYaml": lens["front"]}
    title = lens["title"] or "Board refuses"
    return {"id": f"{LINEAGE}-v1", "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current", "type": "article", "slug": "board", "section": None,
            "status": "draft", "stage": lens["stage"], "headline": title, "title": title, "aliases": [], "metadata": json.dumps(metadata),
            "bodyMarkus": lens["body"], "createdAt": NOW, "updatedAt": NOW, "versionCreatedAt": NOW}


def settings_mapping(lens: dict) -> dict:
    return lens["settings"]


def set_site(context, mapping: dict, environ: dict | None = None) -> None:
    lens = state(context)
    lens["settings"], lens["environ"] = mapping, environ or {}
    standard = standard_settings_from_mapping(mapping)
    lens["site"] = evidence.LensSite(standard, resolve_environment(standard, lens["environ"]))


LIVE = {"site": {"name": "Example", "productionUrl": ORIGIN}, "seo": {"publisherName": "Example"}}


@given("the site is live with a public address")
def site_live(context):
    set_site(context, LIVE, {"PAPYRUS_SITE_PUBLIC_URL": ORIGIN})


@given("the site has no public address")
def site_no_address(context):
    set_site(context, {"site": {"name": "Example"}})


@given("the site is not live yet")
def site_not_live(context):
    set_site(context, LIVE, {"PAPYRUS_SITE_PUBLIC_URL": "https://staging.example.test"})


@given("the site publishes no Markdown copies")
def site_no_markdown(context):
    set_site(context, {**LIVE, "agents": {"markdown": False, "llmsTxt": False, "llmsFull": False}}, {"PAPYRUS_SITE_PUBLIC_URL": ORIGIN})


@given('the site has a description "{text}"')
def site_description(context, text):
    set_site(context, {"site": {"name": "Example", "description": text, "productionUrl": ORIGIN}}, {"PAPYRUS_SITE_PUBLIC_URL": ORIGIN})


@given("the site has a default share picture")
def site_default_picture(context):
    set_site(context, {**LIVE, "seo": {"publisherName": "Example", "defaultImage": "/assets/site.png", "defaultImageAlt": "The site's mark"}},
             {"PAPYRUS_SITE_PUBLIC_URL": ORIGIN})


@given("a Story with this body")
def story_with_body(context):
    lens = state(context)
    lens["front"], lens["body"], lens["title"] = DEFAULT_FRONT, context.text.strip("\n") + "\n", None


@given('a Story titled "{title}"')
def story_titled(context, title):
    lens = state(context)
    lens["front"], lens["body"], lens["title"] = f"title: {title}\n", "Words.\n", title


@given("a Story with the front matter")
def story_with_front(context):
    lens = state(context)
    lens["front"], lens["title"] = context.text.strip("\n") + "\n", None
    lens.setdefault("body", "")


@given("the Story body")
def story_body(context):
    state(context)["body"] = context.text.strip("\n") + "\n"


@given("the Markdown copy is built with a fault that loses the last paragraph")
def twin_fault(context):
    state(context)["fault"] = True


@given('a Story at the "{stage}" stage with this body')
def cli_story(context, stage):
    lens = state(context)
    lens["front"], lens["body"], lens["stage"] = DEFAULT_FRONT, context.text.strip("\n") + "\n", stage
    context.client = FakeAuthoringClient({"Item": [row_of(lens)]})


def run_checks(context, lens_name=None):
    lens = state(context)
    story = evidence.story_from_row(row_of(lens))
    with ExitStack() as stack:
        if lens["fault"]:
            real = evidence.item_markdown

            def lossy(entry, source_text, canonical, notes=(), origin=None):
                text = real(entry, source_text, canonical, notes, origin)
                return text.rstrip("\n").rsplit("\n\n", 1)[0] + "\n"

            stack.enter_context(patch.object(evidence, "item_markdown", lossy))
        context.findings = evidence.run_checks(story, lens["site"], lens=lens_name)


@when("the lens checks run")
def lens_checks_run(context):
    run_checks(context)


@when('the lens checks run for the lens "{name}"')
def lens_checks_run_for(context, name):
    run_checks(context, name)


def finding(context, key) -> dict:
    return next(row for row in context.findings if row["check"] == key)


@then('the finding "{key}" is a "{expected}"')
def finding_state(context, key, expected):
    assert finding(context, key)["state"] == expected, finding(context, key)


@then('the finding "{key}" says "{text}"')
def finding_says(context, key, text):
    assert text in finding(context, key)["message"], finding(context, key)["message"]


@then('the finding "{key}" does not say "{text}"')
def finding_does_not_say(context, key, text):
    assert text not in finding(context, key)["message"], finding(context, key)["message"]


@then('the finding "{key}" lists "{text}" as not checked')
def finding_not_checked(context, key, text):
    assert any(text in item for item in finding(context, key)["evidence"]["notChecked"]), finding(context, key)["evidence"]


@then('"{key}" is among the problems that block a lens step')
def among_blockers(context, key):
    assert key in {row["check"] for row in evidence.blockers(context.findings)}


@then("no lens step is blocked")
def nothing_blocked(context):
    assert evidence.blockers(context.findings) == [], evidence.blockers(context.findings)


@then('"{key}" has the default severity "{severity}"')
def default_severity(context, key, severity):
    assert lenses.CHECK_BY_KEY[key].severity == severity and finding(context, key)["severity"] == severity


@then("every finding has a step, a check, a state, a method and a message")
def finding_shape(context):
    for row in context.findings:
        assert row["step"] in lenses.LENS_STEP_KEYS and row["check"] in lenses.CHECK_BY_KEY and row["state"] in lenses.STATES, row
        assert row["method"] in lenses.METHODS and row["message"], row


@then('the finding "{key}" is shown in the lens "{step}"')
def finding_in_lens(context, key, step):
    assert finding(context, key)["step"] == step


@then('the finding "{first}" and the finding "{second}" are the same fact shown in two lenses')
def mirrored_pair(context, first, second):
    a, b = finding(context, first), finding(context, second)
    assert a["state"] == b["state"] and a["step"] != b["step"] and second in a["mirrors"] and first in b["mirrors"], (a, b)


@then('every finding is in the lens "{step}"')
def all_in_lens(context, step):
    assert context.findings and {row["step"] for row in context.findings} == {step}


@when("the lens checks are listed as not run")
def listed_not_run(context):
    context.not_run = {row["check"]: row for row in evidence.not_run()}


@then('"{key}" is listed as not run because "{reason}"')
def listed_because(context, key, reason):
    assert reason in context.not_run[key]["reason"], context.not_run[key]


@then("no check that is run is also listed as not run")
def disjoint(context):
    ran = {row["check"] for row in evidence.run_checks(evidence.story_from_row(row_of(state(context))), None)}
    assert not ran & set(context.not_run), ran & set(context.not_run)


# --- the command ------------------------------------------------------------------------------------------------------------------------

@given('a web directory whose projection.json describes a live site at "{origin}"')
def web_directory(context, origin):
    directory = tempfile.mkdtemp(prefix="lens-web-")
    context.add_cleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
    Path(directory, "projection.json").write_text(json.dumps({"site": {"name": "Example", "productionUrl": origin}}), encoding="utf-8")
    context.web_directory = directory
    state(context)["environ"] = {"PAPYRUS_SITE_PUBLIC_URL": origin}


def run_command(context, flags: str) -> None:
    client = context.client
    out, err = io.StringIO(), io.StringIO()
    context.succeeded, context.error = True, None
    before = len(client.calls)
    with ExitStack() as stack:
        stack.enter_context(patch.object(story_commands, "create_authoring_client", lambda: (client, None)))
        stack.enter_context(patch.dict("os.environ", {"PAPYRUS_SITE_PUBLIC_URL": state(context)["environ"].get("PAPYRUS_SITE_PUBLIC_URL", "")}))
        stack.enter_context(redirect_stdout(out))
        stack.enter_context(redirect_stderr(err))
        try:
            story_commands.stories_lens_check(shlex.split(flags))
        except Exception as error:
            context.succeeded, context.error = False, error
    context.output, context.errors, context.reads = out.getvalue(), err.getvalue(), client.calls[before:]


@when('I run "stories lens-check" with "{flags}"')
def run_lens_check(context, flags):
    run_command(context, flags)


@when('I run "stories lens-check" with "{flags}" and that web directory')
def run_lens_check_static(context, flags):
    run_command(context, f"{flags} {context.web_directory}")


def lines_of(context):
    return [line.split("\t") for line in context.output.splitlines()]


@then('the lens-check output has a finding line for "{key}" that starts with the word "{word}"')
def finding_line(context, key, word):
    line = next(line for line in lines_of(context) if line[:1] == ["finding"] and line[2] == key)
    assert line[3] == word, line


@then("the lens-check output has a summary line for each of the four lenses")
def summary_lines(context):
    assert [line[1] for line in lines_of(context) if line[:1] == ["summary"]] == list(lenses.LENS_STEP_KEYS), context.output


@then('the lens-check output has a "blocked" line for "{key}"')
def blocked_line(context, key):
    assert any(line[:1] == ["blocked"] and line[2] == key for line in lines_of(context)), context.output


@then("the lens-check output says how many checks were not run")
def says_not_run(context):
    assert any(line[:1] == ["notrun"] and "checks were not run" in line[1] for line in lines_of(context)), context.output


@then('the lens-check output reads "{word}" for "{key}"')
def output_reads(context, word, key):
    line = next(line for line in lines_of(context) if line[:1] == ["finding"] and line[2] == key)
    assert line[3] == word, line


@then("the lens-check command wrote no records")
def wrote_nothing(context):
    assert context.succeeded, repr(context.error)
    assert context.client.write_calls() == []


@then("the command read only the Story's own versions")
def read_only_story(context):
    assert context.succeeded, repr(context.error)
    assert context.reads, "nothing was read"
    allowed = {("list_by_index", "itemsByLineageAndVersion", LINEAGE)}
    assert all(call in allowed or (call[0] == "get" and call[1] == "Item") for call in context.reads), context.reads


@then('the JSON findings are all in the lens "{step}"')
def json_in_lens(context, step):
    payload = json.loads(context.output)
    assert payload["findings"] and {row["step"] for row in payload["findings"]} == {step}


@then("the JSON result lists the checks that were not run")
def json_not_run(context):
    payload = json.loads(context.output)
    assert any(row["check"] == "S9" for row in payload["notRun"]) and not any(row["check"] == "S5" for row in payload["notRun"]), payload["notRun"]


@then("the JSON result says the site settings were not read")
def json_no_settings(context):
    assert json.loads(context.output)["siteSettingsRead"] is False


@then('the lens-check command failed saying "{text}"')
def command_failed(context, text):
    assert not context.succeeded and text in str(context.error), repr(context.error)
