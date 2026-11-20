import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

from papyrus_newsroom import reference_curation_signals

NAME_OF_EACH_STAGE_IN_THE_RUN_RESULT = {
    "identifier": "identifierPrepass",
    "title and subtitle": "titleSubtitle",
    "summary": "summary",
    "quality": "quality",
}


def reference_id_for(name: str) -> str:
    return f"reference-{name}-v1"


def name_of_reference(reference_id: str) -> str:
    return reference_id.removeprefix("reference-").removesuffix("-v1")


def names_listed_in(text: str) -> list[str]:
    return [name.strip() for name in text.split(",") if name.strip()]


class PublicationWhoseCurationStagesAreStandIns:
    def __init__(self, *, time_now: str, references: list[dict]):
        self.time_now = time_now
        self.references = references
        self.references_whose_identifier_cannot_be_worked_out = set()
        self.references_with_no_identifier_to_find = set()
        self.reason_the_summary_fails_by_reference = {}
        self.stages_tried = []
        self.stages_that_saved_something = []
        self.folder_for_run_manifests = Path(tempfile.mkdtemp(prefix="reference-curation-preview-"))

    def resolve_reference(self, semantic_client, reference_id):
        for reference in self.references:
            if reference["id"] == reference_id:
                return reference
        raise ValueError(f"Reference {reference_id} was not found")

    def identifier_prepass(self, *, reference, catalog_entry):
        name = name_of_reference(reference["id"])
        self.stages_tried.append((name, "identifier"))
        if name in self.references_whose_identifier_cannot_be_worked_out:
            return {"status": "failed", "failureReason": "the identifier lookup did not answer"}
        if name in self.references_with_no_identifier_to_find:
            return {"status": "no_identifier_found"}
        return {"status": "ok", "identifiers": {"doi": f"10.1/{name}"}}

    def stage_was_tried(self, reference_id, stage, *, apply):
        self.stages_tried.append((name_of_reference(reference_id), stage))
        if apply:
            self.stages_that_saved_something.append((name_of_reference(reference_id), stage))

    def resolve_title_and_subtitle(self, *, reference_id, apply, **options):
        self.stage_was_tried(reference_id, "title and subtitle", apply=apply)
        return {"action": "update"}

    def summarize(self, *, reference_id, apply, **options):
        self.stage_was_tried(reference_id, "summary", apply=apply)
        reason_it_fails = self.reason_the_summary_fails_by_reference.get(name_of_reference(reference_id))
        if reason_it_fails:
            raise RuntimeError(reason_it_fails)
        return {"action": "create"}

    def assess_quality(self, *, reference_id, apply, **options):
        self.stage_was_tried(reference_id, "quality", apply=apply)
        return {"action": "create"}

    def run_the_preview(self, **options):
        self.stages_tried = []
        with ExitStack() as stand_ins:
            for name_in_the_module, stand_in in {
                "_now": lambda: self.time_now,
                "PAPYRUS_ROOT": self.folder_for_run_manifests,
                "_semantic_client": lambda: object(),
                "_resolve_reference": self.resolve_reference,
                "list_references_by_corpus": lambda corpus_id, limit=None: list(self.references),
                "_run_identifier_prepass": self.identifier_prepass,
                "reference_title_subtitle_resolve": self.resolve_title_and_subtitle,
                "reference_summarize": self.summarize,
                "reference_quality_assess": self.assess_quality,
            }.items():
                stand_ins.enter_context(patch.object(reference_curation_signals, name_in_the_module, stand_in))
            return reference_curation_signals.reference_curate_recent(corpus_key="test-corpus", **options)


@given('it is "{time_now}" and the publication holds these References')
def publication_holds_these_references(context, time_now):
    context.publication = PublicationWhoseCurationStagesAreStandIns(
        time_now=time_now,
        references=[
            {
                "id": reference_id_for(row["reference"]),
                "lineageId": f"reference-{row['reference']}",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-test-corpus",
                "externalItemId": row["reference"],
                "title": row["reference"],
                "curationStatus": row["status"],
                **({"importedAt": row["arrived"]} if row["arrived"] else {}),
            }
            for row in context.table
        ],
    )
    context.preview = None
    context.preview_refusal = None


def run_the_preview(context, **options):
    try:
        context.preview = context.publication.run_the_preview(**options)
    except ValueError as refusal:
        context.preview_refusal = str(refusal)


@when("the curation preview runs")
def curation_preview_runs(context):
    run_the_preview(context)


@when('the curation preview runs for everything since "{since}"')
def curation_preview_runs_since(context, since):
    run_the_preview(context, since=since)


@when("the curation preview runs for every Reference")
def curation_preview_runs_for_every_reference(context):
    run_the_preview(context, curate_all=True)


@when("the curation preview runs for every Reference with a maximum of {max_count:d}")
def curation_preview_runs_for_every_reference_with_maximum(context, max_count):
    run_the_preview(context, curate_all=True, max_count=max_count)


@given('the curation preview has run for the Reference "{name}"')
@when('the curation preview runs for the Reference "{name}"')
def curation_preview_runs_for_the_reference(context, name):
    run_the_preview(context, reference_ids=[reference_id_for(name)])


@when('the curation preview runs for the References "{names}"')
def curation_preview_runs_for_the_references(context, names):
    run_the_preview(context, reference_ids=[reference_id_for(name) for name in names_listed_in(names)])


@when("the curation preview runs with {count:d} References at a time")
def curation_preview_runs_in_parallel(context, count):
    run_the_preview(context, max_parallel=count)


@when("the curation preview is resumed from its manifest")
def curation_preview_is_resumed(context):
    run_the_preview(context, resume=context.preview["manifestPath"])


@given('the identifier of "{name}" cannot be worked out')
def identifier_cannot_be_worked_out(context, name):
    context.publication.references_whose_identifier_cannot_be_worked_out.add(name)


@given('"{name}" has no identifier to find')
def reference_has_no_identifier_to_find(context, name):
    context.publication.references_with_no_identifier_to_find.add(name)


@given('the summary of "{name}" fails with "{reason}"')
def summary_fails_with(context, name, reason):
    context.publication.reason_the_summary_fails_by_reference[name] = reason


@given('the summary of "{name}" works again')
def summary_works_again(context, name):
    del context.publication.reason_the_summary_fails_by_reference[name]


def the_preview(context) -> dict:
    assert context.preview_refusal is None, context.preview_refusal
    return context.preview


def result_for_reference(context, name) -> dict:
    return next(item for item in the_preview(context)["items"] if item["referenceId"] == reference_id_for(name))


@then('the preview picks "{names}" in that order')
def preview_picks_in_that_order(context, names):
    picked = [name_of_reference(item["referenceId"]) for item in the_preview(context)["items"]]
    assert picked == names_listed_in(names), picked


@then("the preview picks all {count:d} References")
def preview_picks_all_references(context, count):
    assert the_preview(context)["count"] == count, the_preview(context)["count"]


@then('the curation preview is refused with "{reason}"')
def preview_is_refused(context, reason):
    assert context.preview_refusal == reason, context.preview_refusal


@then('the preview reports that "{name}" could not be picked')
def preview_reports_reference_could_not_be_picked(context, name):
    failures = the_preview(context)["selectionFailures"]
    assert [failure["referenceId"] for failure in failures] == [reference_id_for(name)], failures
    assert failures[0]["status"] == "selection_failed", failures


@then("the run is degraded")
def run_is_degraded(context):
    assert the_preview(context)["degraded"] is True and the_preview(context)["ok"] is False, the_preview(context)["summary"]


@then("the run is not degraded")
def run_is_not_degraded(context):
    assert the_preview(context)["degraded"] is False and the_preview(context)["ok"] is True, the_preview(context)["items"]


@then('the stages tried for "{name}" are "{stages}" in that order')
@then('the stages tried for "{name}" in the resumed run are "{stages}" in that order')
def stages_tried_in_that_order(context, name, stages):
    the_preview(context)
    tried = [stage for reference_name, stage in context.publication.stages_tried if reference_name == name]
    assert tried == names_listed_in(stages), tried


@then("nothing was saved by any stage")
def nothing_was_saved(context):
    assert context.publication.stages_that_saved_something == []


@then('the title and subtitle, summary and quality stages of "{name}" are skipped because "{reason}"')
def later_stages_are_skipped(context, name, reason):
    stages = result_for_reference(context, name)["stages"]
    for stage in ("title and subtitle", "summary", "quality"):
        outcome = stages[NAME_OF_EACH_STAGE_IN_THE_RUN_RESULT[stage]]
        assert outcome["status"] == "skipped" and outcome["failureReason"] == reason, (stage, outcome)


@then('the Reference "{name}" is reported as failed because "{reason}"')
def reference_is_reported_as_failed_because(context, name, reason):
    result = result_for_reference(context, name)
    assert result["status"] == "failed" and reason in result["failureReasons"], result


@then('the Reference "{name}" is reported as failed')
def reference_is_reported_as_failed(context, name):
    assert result_for_reference(context, name)["status"] == "failed"


@then('the Reference "{name}" is reported as fine')
def reference_is_reported_as_fine(context, name):
    assert result_for_reference(context, name)["status"] == "ok"


@then("the run counts {succeeded:d} succeeded and {failed:d} failed")
def run_counts(context, succeeded, failed):
    summary = the_preview(context)["summary"]
    assert (summary["succeededCount"], summary["failedCount"]) == (succeeded, failed), summary


@then('the run warns "{warning}"')
def run_warns(context, warning):
    assert the_preview(context)["warnings"] == [warning], the_preview(context)["warnings"]
