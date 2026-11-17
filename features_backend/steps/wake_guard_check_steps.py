import json

from behave import given, then, when

from papyrus_content import wake_guard_check


class StartBackend:
    """A site backend as the start mutation answers: the record's id comes from the wake key, and a second create is a duplicate."""

    def __init__(self, once_only=True):
        self.once_only, self.records, self.requests = once_only, {}, []

    def graphql(self, query, variables):
        self.requests.append(query)
        if "startNewsroomProcedureRun" in query:
            run_id = "run-for-" + variables["wakeKey"]
            if run_id in self.records and self.once_only:
                return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": True, "runId": run_id, "runStatus": "started"})}
            record_id = run_id if self.once_only else f"{run_id}-{len(self.records)}"
            self.records[record_id] = {"id": record_id, "runStatus": "started", "wakeKey": variables["wakeKey"]}
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": False, "runId": record_id})}
        if "getNewsroomProcedureRun" in query:
            return {"getNewsroomProcedureRun": json.dumps(self.records[variables["id"]])}
        if "updateProcedureRun" in query:
            self.records[variables["input"]["id"]].update(variables["input"])
            return {"updateProcedureRun": {"id": variables["input"]["id"]}}
        raise AssertionError(f"unexpected request: {query}")


@given("a site backend that answers the start as the newsroom function does")
def _backend(context):
    context.backend, context.result, context.error = StartBackend(), None, None


@given("the site backend ignores the once-only condition")
def _ignores(context):
    context.backend = StartBackend(once_only=False)


def _run(context, request_id, apply=True, procedure_key="newsroom.fact-check"):
    try:
        context.result = wake_guard_check.check_wake_guard(context.backend, procedure_key=procedure_key, request_id=request_id, apply=apply)
    except Exception as error:  # noqa: BLE001 - the scenario asserts which error it was
        context.error = error


@when('the wake guard check runs for the procedure "{key}"')
def _runs(context, key):
    _run(context, "wake-guard-check-1", procedure_key=key)


@when('the wake guard check is previewed for the procedure "{key}"')
def _previewed(context, key):
    _run(context, "wake-guard-check-1", apply=False, procedure_key=key)


@when('the wake guard check runs with the request id "{request_id}"')
def _runs_with(context, request_id):
    _run(context, request_id)


@then("the check is proved")
def _proved(context):
    assert context.error is None, context.error
    assert context.result["status"] == "proved"
    assert context.result["answers"]["first"]["duplicate"] is False and context.result["answers"]["second"]["duplicate"] is True


@then("the site holds {count:d} run record")
@then("the site holds {count:d} run records")
def _holds(context, count):
    assert len(context.backend.records) == count, context.backend.records


@then('the record is finished as nothing to do with the reason "{reason}"')
@then('the first record is finished as nothing to do with the reason "{reason}"')
def _finished(context, reason):
    record = next(iter(context.backend.records.values()))
    assert (record["runStatus"], record["outcome"], record["outcomeReason"]) == ("completed", "nothing", reason), record


@then("no procedure was loaded or run")
def _none_loaded(context):
    assert not any("getNewsroomProcedureDefinition" in query for query in context.backend.requests)


@then("the check shows its wake key and made no request")
def _dry(context):
    assert context.result["status"] == "dry-run" and context.result["wakeKey"] == "procedure:newsroom.fact-check|manual|wake-guard-check-1"
    assert context.backend.requests == []


@then("the check fails because the second answer was not a duplicate")
def _failed(context):
    assert isinstance(context.error, wake_guard_check.WakeGuardCheckFailed), context.error


@then("the check is refused for its request id")
def _refused(context):
    assert isinstance(context.error, ValueError) and "request id" in str(context.error), context.error
