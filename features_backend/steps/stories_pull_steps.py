"""Steps for features_backend/stories-pull.feature. The backend is the in-memory fake; nothing leaves the process."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content import story_commands  # noqa: E402
from test_story_cli_live_test_edges import run  # noqa: E402

LINEAGE = "edge-story"
VERSIONS = {
    1: ("Old body of the story.\n", "title: Edge story\n"),
    2: ('Current body, with a picture.\n\n::image{src="assets/edge-story/chart.png" alt="A chart"}\n\nA claim.[@key]\n',
        "title: Edge story\ndek: A dek\nimage: assets/edge-story/chart.png\ncitations:\n  key:\n    type: webpage\n    title: A source\n"),
}


def _row(number):
    body, front = VERSIONS[number]
    return {"id": f"{LINEAGE}-v{number}", "lineageId": LINEAGE, "versionNumber": number, "versionState": "current" if number == 2 else "superseded",
            "versionCreatedAt": f"2026-11-0{number}T10:00:00Z", "headline": "Edge story", "title": "Edge story", "stage": "reporting", "slug": "edge-story",
            "type": "article", "section": "news", "status": "draft", "bodyMarkus": body, "metadata": json.dumps({"frontMatterYaml": front})}


def _go(context, *flags):
    context.out, context.err, context.failure = run(story_commands.stories_pull, context.client, *flags)


@given('a Story "edge-story" with a first version and a second, current version')
def _story(context):
    context.client = FakeAuthoringClient({"Item": [_row(1), _row(2)]})
    context.client.endpoint = "https://example.test/graphql"
    context.dir = Path(tempfile.mkdtemp(prefix="stories-pull-"))
    context.body_file, context.front_file = context.dir / "body.md", context.dir / "front.yaml"
    context.calls_before = len(context.client.calls)


def _pull(context, lineage, *extra):
    _go(context, "--story", lineage, "--body-file", str(context.body_file), "--front-matter-file", str(context.front_file), *extra)


@when('the agent pulls "{lineage}" to a body file and a front matter file')
def _pull_current(context, lineage):
    _pull(context, lineage)


@when('the agent pulls "{lineage}" as JSON')
def _pull_json(context, lineage):
    _pull(context, lineage, "--json")


@when('the agent pulls version {number:d} of "{lineage}"')
def _pull_version(context, number, lineage):
    _pull(context, lineage, "--version", str(number))


@when("the agent saves the pulled files unchanged as a new version")
def _save(context):
    out, err, failure = run(story_commands.stories_save_version, context.client, "--story", LINEAGE, "--body-file", str(context.body_file),
                            "--front-matter-file", str(context.front_file), "--reason", "Round trip", "--author-label", "Ada Example", "--no-check")
    assert failure is None, (failure, err)


@then("the pull succeeds and prints version {number:d}")
def _ok(context, number):
    assert context.failure is None, context.failure
    assert f"version {number}" in context.out and context.out.startswith(f"stories\tpull\t{LINEAGE}\t"), context.out


@then("the body file holds the text of version {number:d} exactly")
def _body(context, number):
    assert context.failure is None, context.failure
    assert context.body_file.read_bytes() == VERSIONS[number][0].encode()


@then("the front matter file holds the front matter of version {number:d} exactly")
def _front(context, number):
    assert context.front_file.read_bytes() == VERSIONS[number][1].encode()


@then('"{lineage}" has {count:d} versions')
def _count(context, lineage, count):
    assert len(story_commands.story_versions(context.client, lineage)) == count


def _record(context, number):
    return next(row for row in story_commands.story_versions(context.client, LINEAGE) if row["versionNumber"] == number)


@then("version {number:d} has the same body and front matter as version {other:d}")
def _same(context, number, other):
    a, b = _record(context, number), _record(context, other)
    assert a["bodyMarkus"] == b["bodyMarkus"]
    assert json.loads(a["metadata"])["frontMatterYaml"] == json.loads(b["metadata"])["frontMatterYaml"]


@then("the picture paths of version {number:d} are the stored paths of version {other:d}")
def _pictures(context, number, other):
    for record, path in ((_record(context, number), "assets/edge-story/chart.png"), (_record(context, other), "assets/edge-story/chart.png")):
        assert path in record["bodyMarkus"] and f"image: {path}" in json.loads(record["metadata"])["frontMatterYaml"]


@then('the pull fails saying "{text}"')
def _fails(context, text):
    assert context.failure is not None and text in str(context.failure), (context.failure, context.out)


@then("no file was written")
def _no_files(context):
    assert not context.body_file.exists() and not context.front_file.exists()


@then("no Story row was created or updated")
def _no_writes(context):
    assert context.failure is None, context.failure
    writes = [call for call in context.client.calls[context.calls_before:] if call[0] in ("create", "update", "upsert", "delete")]
    assert writes == [], writes


@then('the JSON names story "{lineage}", version {number:d} and both files')
def _json(context, lineage, number):
    data = json.loads(context.out)
    assert (data["story"], data["version"], data["bodyFile"], data["frontMatterFile"]) == (lineage, number, str(context.body_file), str(context.front_file)), data
