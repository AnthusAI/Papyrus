from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from behave import given, then, when
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import review_requests  # noqa: E402
from papyrus_content.knowledge_cloud.fakes import make_run  # noqa: E402
from papyrus_content.knowledge_cloud.preview_gate import HISTORY_FILE, series_of  # noqa: E402
from papyrus_content.knowledge_cloud.stages import run_stage  # noqa: E402

AWS = {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1"}


def _plan(kinds):
    pages = [
        {"action": "create", "section": "wiki", "slug": f"{kind}-{n}", "kind": "entity", "entityKind": kind, "title": f"Title {kind} {n}", "note": ""}
        for kind, count in kinds.items()
        for n in range(count)
    ]
    return {"mode": "dry-run", "counts": {}, "pages": pages, "warnings": [], "written": {}}


def _kinds(text):
    """'40 "personauthor" pages and 3 "maker" pages' -> {'personauthor': 40, 'maker': 3}"""
    found = {}
    for part in text.replace(" and ", ",").split(","):
        words = part.strip().split()
        if len(words) >= 2 and words[0].isdigit():
            found[words[1].strip('"')] = int(words[0])
    return found


def _start(context, kinds, execution):
    work = Path(tempfile.mkdtemp())
    run, shell = make_run(work, execution=execution)
    if getattr(context, "preview_run", None) is not None:  # the same publication: its state and its data API carry over
        run.state, run.services = context.preview_run.state, context.preview_run.services
    if getattr(context, "preview_client", None) is not None:
        run.services.client = context.preview_client
    shell.wiki_plan = _plan(kinds)
    context.preview_run, context.preview_shell, context.preview_code = run, shell, None


def _applied(context):
    return [call for call in context.preview_shell.calls if call[:4] == ["papyrus", "knowledge", "wiki", "sync"] and "--apply" in call]


def _published(context):
    return [call for call in context.preview_shell.calls if call[:4] == ["papyrus", "knowledge", "wiki", "publish"]]


def _requests(context):
    return [review_requests.read_review(row) for row in context.preview_run.services.record_client({}).list_records("ReviewRequest")]


def _go(context, kinds, execution):
    _start(context, kinds, execution)
    context.preview_code = run_stage("wiki-sync", context.preview_run)


@given('a publication whose knowledge run is on its stage "wiki-sync"')
def step_background(context):
    context.mock = mock_aws()
    context.mock.start()
    context.add_cleanup(context.mock.stop)
    saved = {key: os.environ.get(key) for key in AWS}
    os.environ.update(AWS)
    context.add_cleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in saved.items()])
    context.preview_run = None
    context.preview_client = None


@when('execution "{execution}" plans {kinds}')
@given('execution "{execution}" plans {kinds}')
def step_plans(context, execution, kinds):
    _go(context, _kinds(kinds), execution)


@when('execution "{execution}" has nothing to write')
def step_none(context, execution):
    _go(context, {}, execution)


@given("a person accepts the request")
@when("a person accepts the request")
def step_accept(context):
    review_requests.answer_review(context.preview_run.services.record_client({}), _requests(context)[0]["id"], decision="approve", by="a-person")


@when("a person rejects the request")
def step_reject(context):
    review_requests.answer_review(context.preview_run.services.record_client({}), _requests(context)[0]["id"], decision="reject", by="a-person")


@when("an agent accepts the request")
def step_agent(context):
    review_requests.answer_review(context.preview_run.services.record_client({}), _requests(context)[0]["id"], decision="approve", by="agent:editor")


@when('the stage "projection" runs in the held execution')
def step_projection(context):
    assert run_stage("projection", context.preview_run) == 0


@given("the site wrote {counts} \"{kind}\" pages in its earlier runs")
def step_history(context, counts, kind):
    numbers = [int(part) for part in counts.replace(" and ", ",").split(",") if part.strip().isdigit()]
    state = _fresh_state(context)
    entries = [
        {"runId": f"earlier-{index}", "week": "2026-W40", "at": "2026-10-01T00:00:00Z", "fingerprint": f"f{index}", "outcome": "written", "series": series_of(_plan({kind: number}))}
        for index, number in enumerate(numbers)
    ]
    state.write_text(HISTORY_FILE, json.dumps({"version": 1, "runs": entries}))


def _fresh_state(context):
    _start(context, {}, "setup")
    return context.preview_run.state


@given("the site's data API cannot be reached")
def step_broken(context):
    class Broken:
        def get_record(self, *args):
            return None

        def list_records(self, *args):
            return []

        def create_record(self, *args):
            raise RuntimeError("the data API is not reachable")

    context.preview_client = Broken()


@then("the stage held the run and wrote no page")
def step_held_then(context):
    assert context.preview_code == 0 and not _applied(context) and not _published(context)


@then("the stage wrote its pages and published them")
def step_wrote(context):
    assert context.preview_code == 0 and _applied(context) and _published(context)


@then("the stage wrote its pages and raised no request")
def step_wrote_quiet(context):
    assert context.preview_code == 0 and _applied(context) and not _requests(context)


@then("the stage failed and wrote no page")
def step_failed(context):
    assert context.preview_code == 1 and not _applied(context)


@then("the Notification Center holds one hard gate that says nothing has been written")
def step_gate(context):
    [request] = _requests(context)
    assert request["mode"] == "hard_gate" and request["state"] == "open" and "Nothing has been written" in request["reason"]


@then('the gate lists "{line}" and a sample of the page titles')
def step_lists(context, line):
    [request] = _requests(context)
    assert line in request["ask"] and "Title " in request["ask"]


@then("the plan is kept in the run's state")
def step_kept(context):
    kept = json.loads(context.preview_run.state.read_text("runs/2026-W44/wiki-sync-preview.json"))
    assert kept["plan"]["pages"] and kept["decision"]["status"] == "held"


@then("nothing was projected")
def step_not_projected(context):
    assert not [call for call in context.preview_shell.calls if call[:4] == ["papyrus", "ops", "content", "project"]]


@then("there is still only one request")
def step_one(context):
    assert len(_requests(context)) == 1


@then('the request says "{text}" and that it is unlike this site\'s earlier runs')
def step_says(context, text):
    open_requests = [request for request in _requests(context) if request["state"] == "open"]
    assert len(open_requests) == 1 and text in open_requests[0]["ask"] and "unlike this site's earlier runs" in open_requests[0]["reason"]
