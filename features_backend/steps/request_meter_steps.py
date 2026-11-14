"""The request meter and the batched reads (features_backend/request-meter.feature, features_backend/batched-reads.feature). The backend is a fake."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from fake_appsync import FakeAppSync  # noqa: E402
from papyrus_content import request_meter  # noqa: E402
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient  # noqa: E402
import test_auto_accept_batched_reads as batched  # noqa: E402

ENDPOINT = "https://example.appsync-api.us-east-1.amazonaws.com/graphql"


def client_for(backend: FakeAppSync) -> PapyrusGraphQLAuthoringClient:
    client = PapyrusGraphQLAuthoringClient(endpoint=ENDPOINT, header_factory=lambda body: {}, site_tenant=False)
    client._open_connection = lambda: backend  # type: ignore[method-assign]
    return client


@contextlib.contextmanager
def capture(context):
    """What the process wrote to stdout and stderr while it ran (behave's own capture is per step)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            yield
        finally:
            context.out, context.err = out.getvalue(), err.getvalue()


def reset(context) -> None:
    os.environ["PAPYRUS_GRAPHQL_AUTH"] = "iam"
    os.environ.pop(request_meter.ENV_MODE, None)
    os.environ.pop(request_meter.ENV_BUDGET, None)
    request_meter.reset_for_tests()
    context.backend = FakeAppSync(gets={"getReference": {}})
    context.client = client_for(context.backend)
    context.run_kwargs, context.error = {}, None


def read_references(context, count: int) -> None:
    for n in range(count):
        context.client.get_record("Reference", f"ref-{n}")


# request meter ------------------------------------------------------------------------------------------------------------------

@given('a command named "{name}" given {count:d} ids')
@given('a command named "{name}" given {count:d} id')
def _(context, name, count):
    reset(context)
    context.run_kwargs = {"caller": f"cli:{name}", "units": count, "emit": "stderr"}


@given('a command named "{name}" with a budget of {budget:d}')
def _(context, name, budget):
    reset(context)
    context.run_kwargs = {"caller": f"cli:{name}", "emit": "stderr", "budget": budget}


@given('a Lambda named "{name}" invoked for the task "{task}"')
def _(context, name, task):
    reset(context)
    context.run_kwargs = {"caller": f"lambda:{name}:{task}", "emit": "log"}


@given("another run of the same command given {count:d} ids")
def _(context, count):
    context.second_units = count


@when("it makes {count:d} reads of a Reference")
def _(context, count):
    try:
        with capture(context), request_meter.run(**context.run_kwargs) as run:
            read_references(context, count)
        context.run_result = run
    except Exception as error:   # noqa: BLE001
        context.error = error


@when('it makes {count:d} reads of a Reference inside the sweep "{name}"')
def _(context, count, name):
    with capture(context), request_meter.run(**context.run_kwargs) as run:
        with request_meter.sweep(name):
            read_references(context, count)
    context.run_result = run


@when('it lists every Reference twice, and once more inside the sweep "{name}"')
def _(context, name):
    context.backend.indexes["listReferences"] = {}
    with capture(context), request_meter.run(**context.run_kwargs) as run:
        context.client.list_records("Reference")
        context.client.list_records("Reference")
        with request_meter.sweep(name):
            context.client.list_records("Reference")
    context.run_result = run


@when("the stop switch is on and a command with a budget of {budget:d} makes {count:d} reads")
def _(context, budget, count):
    request_meter.reset_for_tests()
    os.environ[request_meter.ENV_MODE] = "stop"
    try:
        with capture(context), request_meter.run("cli:stopped", emit="stderr", budget=budget):
            read_references(context, count)
    except request_meter.RequestBudgetExceeded as error:
        context.error = error
    finally:
        os.environ.pop(request_meter.ENV_MODE, None)


def captured(context) -> tuple[str, str]:
    return getattr(context, "out", ""), getattr(context, "err", "")


@then('stderr has one line that starts "{prefix}"')
def _(context, prefix):
    lines = [line for line in captured(context)[1].splitlines() if line.startswith("papyrus requests:")]
    assert len(lines) == 1 and lines[0].startswith(prefix), lines
    context.summary_line = lines[0]


@then('the line names "{text}"')
def _(context, text):
    assert text in context.summary_line


@then('its log has one JSON line with event "{event}", caller "{caller}" and {count:d} requests')
def _(context, event, caller, count):
    summaries = [json.loads(line) for line in captured(context)[0].splitlines() if line.startswith("{") and f'"{event}"' in line]
    assert len(summaries) == 1 and summaries[0]["caller"] == caller and summaries[0]["requests"] == count, summaries


@then("the second budget is {factor:d} times the per-id amount larger than the first")
def _(context, factor):
    base, per_unit = request_meter.budget_parameters(context.run_kwargs["caller"])
    first = request_meter.Run(**context.run_kwargs)
    second = request_meter.Run(**{**context.run_kwargs, "units": context.second_units})
    assert second.budget() - first.budget() == factor * per_unit


@then("all {count:d} reads were made")
def _(context, count):
    assert context.run_result.requests == count and context.error is None


@then('stderr has exactly one warning that names "{name}" and the budget of {budget:d}')
def _(context, name, budget):
    warnings = [line for line in captured(context)[1].splitlines() if "WARNING papyrus request meter" in line]
    assert len(warnings) == 1 and name in warnings[0] and f"budget of {budget}" in warnings[0], warnings


@then("no error was raised")
def _(context):
    assert context.error is None


@then("the run is stopped with a budget error")
def _(context):
    assert isinstance(context.error, request_meter.RequestBudgetExceeded)


@then("all {count:d} reads were counted and none was held to the budget")
def _(context, count):
    assert context.run_result.requests == count and context.run_result.budgeted == 0


@then("stderr has no warning")
def _(context):
    assert "WARNING" not in captured(context)[1]


@then("its log says once that the unbounded list of Reference was made outside a named sweep")
def _(context):
    entries = [line for line in captured(context)[0].splitlines() if '"papyrus_unbounded_list"' in line]
    assert len(entries) == 1 and json.loads(entries[0])["model"] == "Reference"


@then("its summary counts {count:d} unbounded lists of Reference")
def _(context, count):
    assert context.run_result.unbounded == {"Reference": count}


@given("the allowlist of files that may read a whole table")
def _(context):
    from papyrus_content import whole_table_reads_test as guard
    context.guard = guard


@then("no file reads more whole tables than the allowlist records")
def _(context):
    context.guard.test_no_new_whole_table_reads_outside_the_allowlist()


# batched reads ------------------------------------------------------------------------------------------------------------------

@given("{count:d} References and 1 id that does not exist")
def _(context, count):
    reset(context)
    context.rows = {f"ref-{n}": {"id": f"ref-{n}"} for n in range(count)}
    context.backend.gets["getReference"] = context.rows
    context.ids = [*context.rows, "missing"]


@given("{count:d} References")
def _(context, count):
    reset(context)
    context.rows = {f"ref-{n}": {"id": f"ref-{n}"} for n in range(count)}
    context.backend.gets["getReference"] = context.rows
    context.backend.indexes["listReferences"] = {"": list(context.rows.values())}
    context.ids = list(context.rows)


@when("the client gets them all by id")
def _(context):
    context.found = context.client.get_many("Reference", context.ids)


@when("the client gets them with get_records_by_id")
def _(context):
    context.found = context.client.get_records_by_id("Reference", context.ids)


@when("the client gets them all by id inside a metered run")
def _(context):
    with request_meter.run("test:batch", emit="log") as run:
        context.client.get_many("Reference", context.ids)
    context.run_result = run


@then("{count:d} requests were made")
def _(context, count):
    assert len(context.backend.requests) == count, len(context.backend.requests)


@then("{count:d} requests were made and none of them listed every Reference")
def _(context, count):
    assert len(context.backend.requests) == count and not any("listReferences" in q for q in context.backend.requests)


@then("the {count:d} References come back and the missing one does not")
def _(context, count):
    assert len(context.found) == count and "missing" not in context.found


@then("the run counted 1 request that folded {count:d} reads")
def _(context, count):
    assert context.run_result.requests == 1 and context.run_result.aliases == count


@given("{partitions:d} partitions of relations and one partition with {long:d} relations, read {page:d} to a page")
def _(context, partitions, long, page):
    reset(context)
    context.page = page
    relations = {f"reference#lin-{n}#current": [{"id": f"rel-{n}"}] for n in range(partitions)}
    relations["reference#long#current"] = [{"id": f"long-{n}"} for n in range(long)]
    context.backend.indexes["listSemanticRelationsBySubjectState"] = relations
    context.keys = list(relations)


@when("the client reads the partitions together")
def _(context):
    context.together = context.client.index_many("semanticRelationsBySubjectState", context.keys, limit=context.page)


@then("each partition returns the same rows as reading it alone")
def _(context):
    for key in context.keys:
        assert context.together[key] == context.client.list_by_index("semanticRelationsBySubjectState", key, limit=context.page), key


@then("the long partition returns all {count:d} relations")
def _(context, count):
    assert len(context.together["reference#long#current"]) == count


@given("a publication whose editors voted on {votes:d} References and has {pending:d} waiting")
@given("another whose editors voted on {votes:d} and has {pending:d} waiting")
def _(context, votes, pending):
    if not hasattr(context, "passes"):
        reset(context)
        context.passes = []
    context.passes.append((votes, pending))


@when("automatic acceptance runs on each as a dry run")
def _(context):
    context.outcomes = [batched.pass_requests(votes, pending) for votes, pending in context.passes]


@then("each pass made its index reads, plus one request per 25 voted References and one per 25 waiting ones")
def _(context):
    for (votes, pending), (requests, _result) in zip(context.passes, context.outcomes):
        assert requests == batched.expected_requests(votes, pending), (votes, pending, requests)


@then("both passes decided the same way as the per-Reference pass: every vote counted, every waiting confident Reference a candidate")
def _(context):
    for (votes, pending), (_requests, result) in zip(context.passes, context.outcomes):
        assert result["votes"] == votes and result["candidates"] == pending


@given("a signed-in site with one canonical publication corpus")
def _(context):
    from fake_appsync import FakeAppSync
    corpus = {"id": "knowledge-corpus-demo", "role": "canonical", "name": "Demo"}
    backend = FakeAppSync(indexes={"listKnowledgeCorporaByRoleAndName": {"canonical": [corpus]}, "listKnowledgeCorpora": {"": [corpus]}})
    context.corpus_client = PapyrusGraphQLAuthoringClient(endpoint=ENDPOINT, header_factory=lambda body: {}, site_tenant=False)
    context.corpus_client._open_connection = lambda: backend


@when("capture-transcripts, capture-thumbnails and repair-titles resolve their corpus without a --corpus-key")
def _(context):
    from papyrus_content import references_thumbnails, references_titles, references_transcripts
    request_meter.reset_for_tests()
    with request_meter.run("cli:references capture-transcripts", emit="log") as run:
        context.corpus_answers = [module.corpus_ids_of(context.corpus_client, None)
                                  for module in (references_transcripts, references_thumbnails, references_titles)]
    context.run_result = run


@then("each covers the canonical corpus and the request meter records no unbounded list of KnowledgeCorpus")
def _(context):
    assert context.corpus_answers == [["knowledge-corpus-demo"]] * 3
    assert context.run_result.unbounded == {}
