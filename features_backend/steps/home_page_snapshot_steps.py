from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.home_page.commands import home_page_snapshot  # noqa: E402
from papyrus_content.home_page.export import EXCLUDED_REFERENCE_FIELDS, PUBLIC_REFERENCE_FIELDS  # noqa: E402
from papyrus_content.home_page.task import home_page_settings_of, run_home_page_snapshot  # noqa: E402
from papyrus_content.projection.engine import reconcile  # noqa: E402
from procedures.newsroom.tests.reader_privacy import scan_files  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings  # noqa: E402

FIXTURE_FILE = REPO_ROOT / "features_backend" / "fixtures" / "home-page" / "references.json"
REFERENCES_KEY = "_data/home-page/references.json"
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
IDENTITY_SENTINELS = ("editor@example.test", "relay@example.test", "intake@example.test", "reader@example.test", "press@example.test", "auto:cyclotron")


class FixtureClient:
    """The authoring client calls the snapshot makes, answered from ``features_backend/fixtures/home-page/references.json``."""

    def __init__(self, fixture: dict | None = None) -> None:
        self.fixture = fixture or json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
        self.corpus_id = self.fixture["corpusId"]
        self.calls: list[str] = []

    def rows(self) -> list[dict]:
        return [entry["row"] for entry in self.fixture["references"]]

    def list_by_index(self, index_name: str, key_value: str, *, limit: int = 100) -> list[dict]:
        self.calls.append(index_name)
        if index_name == "referencesByCurationStatusKey":
            return [row for row in self.rows() if row["curationStatusKey"] == key_value]
        if index_name == "referencesByFeedStateAndPrediction":
            return [row for row in self.rows() if row["feedStateKey"] == key_value]
        raise AssertionError(f"unexpected index {index_name}")

    def list_semantic_relations_by_subject_state(self, subject_state_key: str) -> list[dict]:
        lineage = subject_state_key.removeprefix("reference#").removesuffix("#current")
        return [relation for entry in self.fixture["references"] if entry["row"]["lineageId"] == lineage for relation in entry["relations"]]

    def list_reference_attachments_by_lineage(self, reference_lineage_id: str) -> list[dict]:
        return [item for entry in self.fixture["references"] if entry["row"]["lineageId"] == reference_lineage_id for item in entry["attachments"]]

    def list_records(self, model_name: str) -> list[dict]:
        assert model_name == "NewsroomSection"
        return list(self.fixture["sections"])


def quoted(text: str) -> list[str]:
    return re.findall(r'"([^"]*)"', text)


def settings_with(context, extra: dict | None = None, base_path: str | None = None, home_page: dict | None = ...) -> dict:
    settings = fixture_settings("flat")
    if home_page is ...:
        home_page = {"references": {"corpus": "knowledge-corpus-example"}}
    if home_page is not None:
        settings["homePage"] = home_page
    if base_path:
        settings["urls"] = {"basePath": base_path}
    settings.update(extra or {})
    return settings


def start_site(context, **options) -> None:
    context.client = FixtureClient()
    context.site = ProjectedSite(settings=settings_with(context, **options), content=FIXTURES / "flat" / "content")
    context.add_cleanup(context.site.cleanup)
    context.reports = []
    context.base_path = options.get("base_path") or ""


def run_snapshot(context) -> dict:
    report = run_home_page_snapshot(context.site.context, context.client, home_page_settings_of(context.site.projector), now=NOW)
    context.reports.append(report)
    context.report = report
    return report


def snapshot_key(context) -> str:
    return f"{context.base_path}/{REFERENCES_KEY}".lstrip("/")


def document(context) -> dict:
    body = context.site.writer.get(snapshot_key(context))
    assert body is not None, "the snapshot file was not written"
    return json.loads(body)


def titled(context, title: str) -> dict:
    found = [record for record in document(context)["references"] if record["title"] == title]
    assert len(found) == 1, f"{title!r} appears {len(found)} times in {[r['title'] for r in document(context)['references']]}"
    return found[0]


@given("a site whose projection.json has a homePage setting for a corpus of accepted, pending, rejected and archived References")
def site_with_home_page(context) -> None:
    start_site(context)


@given("a site with pages that place a references include and a homePage setting for a corpus of accepted, pending, rejected and archived References")
def site_with_reference_pages(context) -> None:
    site_directory = FIXTURES / "home-page"
    extra_files = {f"pages/{path.name}": path.read_bytes() for path in sorted((site_directory / "pages").glob("*.md"))}
    context.client = FixtureClient()
    context.site = ProjectedSite(settings=json.loads((site_directory / "projection.json").read_text(encoding="utf-8")), content=site_directory / "content", extra_files=extra_files)
    context.add_cleanup(context.site.cleanup)
    context.reports = []
    context.base_path = ""


@given("a site whose projection.json has no homePage setting")
def site_without_home_page(context) -> None:
    start_site(context, home_page=None)


@given('a site whose projection.json has a homePage setting and the base path "{base}"')
def site_with_base_path(context, base: str) -> None:
    start_site(context, base_path=base)


@when("the home-page-snapshot task runs")
def run_task(context) -> None:
    run_snapshot(context)


@when("the home-page-snapshot task runs again with no change in the References")
def run_task_again(context) -> None:
    context.site.writer.operations.clear()
    run_snapshot(context)


@when("a Reference is accepted and the home-page-snapshot task runs again")
def accept_and_run_again(context) -> None:
    for row in context.client.rows():
        if row["title"] == "Pending high":
            row["curationStatus"] = "accepted"
            row["curationStatusKey"] = f"{context.client.corpus_id}#accepted"
            row["feedStateKey"] = None
            row["curationStatusUpdatedAt"] = "2026-10-31T08:00:00.000Z"
    context.site.writer.operations.clear()
    run_snapshot(context)


@when("the site is reconciled")
def reconcile_site(context) -> None:
    context.reconcile_report = reconcile(context.site.context)


@then("the store holds no key under _data/home-page")
def nothing_stored(context) -> None:
    keys = [key for key in context.site.tree if "_data/home-page" in key]
    assert not keys, keys


@then("the task reports that the site has no homePage setting")
def reports_skip(context) -> None:
    assert "no homePage setting" in context.report["skipped"], context.report


@then("the accepted titles in the file, in order, are {titles}")
def accepted_titles(context, titles: str) -> None:
    wanted = quoted(titles)
    found = [record["title"] for record in document(context)["references"] if record["status"] == "accepted"]
    assert found == wanted, found


@then("every record has exactly the public fields in the allowlist order")
def records_have_allowlist(context) -> None:
    for record in document(context)["references"]:
        assert tuple(record) == PUBLIC_REFERENCE_FIELDS, list(record)
    assert document(context)["fields"] == list(PUBLIC_REFERENCE_FIELDS)


@then("no record has an excluded field")
def no_excluded_fields(context) -> None:
    for record in document(context)["references"]:
        present = sorted(set(record) & set(EXCLUDED_REFERENCE_FIELDS))
        assert not present, present


@then("the file mentions none of the excluded values the fixture holds")
def no_excluded_values(context) -> None:
    text = context.site.writer.get(snapshot_key(context)).decode("utf-8")
    found = [value for value in IDENTITY_SENTINELS if value in text]
    assert not found, found
    for row in context.client.rows():
        for value in (row["lineageId"], row["id"], row["storagePath"], row["sha256"], row["importRunId"]):
            assert value not in text, value


@then("the recommended titles in the file are {titles}")
def recommended_titles(context, titles: str) -> None:
    wanted = sorted(quoted(titles))
    found = sorted(record["title"] for record in document(context)["references"] if record["status"] == "recommended")
    assert found == wanted, found


@then("the file does not list {titles}")
def file_lacks(context, titles: str) -> None:
    listed = {record["title"] for record in document(context)["references"]}
    for title in quoted(titles):
        assert title not in listed, title


@then("every recommended record has no acceptedAt")
def recommended_have_no_accepted_at(context) -> None:
    for record in document(context)["references"]:
        if record["status"] == "recommended":
            assert record["acceptedAt"] is None, record


@then('the record titled "{title}" has confidence {confidence:f}')
def has_confidence(context, title: str, confidence: float) -> None:
    assert titled(context, title)["confidence"] == confidence, titled(context, title)


@then('the record titled "{title}" has no image, no summary and no site name')
def has_no_preview(context, title: str) -> None:
    record = titled(context, title)
    assert (record["image"], record["summary"], record["siteName"]) == (None, None, None), record


@then('the record titled "{title}" has an image, a summary and a site name')
def has_preview(context, title: str) -> None:
    record = titled(context, title)
    assert record["image"] and record["summary"] and record["siteName"], record


@then('the summary of "{title}" is at most 240 characters and ends on a sentence boundary')
def summary_is_clipped(context, title: str) -> None:
    summary = titled(context, title)["summary"]
    assert len(summary) <= 240 and summary.endswith("."), summary


@then("the identity scanner finds nothing in the file")
def scanner_clean(context) -> None:
    leaks = scan_files({snapshot_key(context): context.site.writer.get(snapshot_key(context))}, [])
    assert leaks == {}, leaks


@then("the file is not written again")
def not_written_again(context) -> None:
    puts = [key for operation, key in context.site.writer.operations if operation == "put" and key == snapshot_key(context)]
    assert not puts, puts
    assert context.report["unchanged"] == [snapshot_key(context)], context.report


@then("no page is re-rendered")
def no_pages(context) -> None:
    pages = [key for operation, key in context.site.writer.operations if operation == "put"]
    assert not pages and context.report["pagesRewritten"] == 0, (pages, context.report)


@then("the file is written")
def file_written(context) -> None:
    assert context.report["written"] == [snapshot_key(context)], context.report


@then("only pages that read the file are re-rendered")
def only_reading_pages(context) -> None:
    pages = [key for operation, key in context.site.writer.operations if operation == "put" and key != snapshot_key(context)]
    assert pages, "no page was re-rendered"
    assert all("references" in context.site.text(key) for key in pages), pages


@then('the page "{key}" was re-rendered')
def page_rewritten(context, key: str) -> None:
    assert ("put", key) in context.site.writer.operations, context.site.writer.operations


@then('the page "{key}" was not re-rendered')
def page_not_rewritten(context, key: str) -> None:
    assert ("put", key) not in context.site.writer.operations, context.site.writer.operations


@then("the file is still in the store")
def file_remains(context) -> None:
    assert context.site.writer.get(snapshot_key(context)) is not None
    assert snapshot_key(context) not in context.reconcile_report.orphan_pages


@then('the file is stored at "{key}"')
def stored_at(context, key: str) -> None:
    assert context.site.writer.get(key) is not None, sorted(context.site.tree)


@when("papyrus home-page snapshot --dry-run runs against an empty output directory")
def cli_dry_run(context) -> None:
    context.output_directory = tempfile.TemporaryDirectory()
    context.add_cleanup(context.output_directory.cleanup)
    client = FixtureClient()
    printed = io.StringIO()
    with mock.patch("papyrus_content.knowledge_snapshot.commands.authoring_client", return_value=client), mock.patch(
        "papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)
    ), contextlib.redirect_stdout(printed):
        home_page_snapshot(["--site", "example", "--out", context.output_directory.name, "--dry-run"])
    context.cli_output = printed.getvalue()


@then("the output directory is still empty")
def directory_empty(context) -> None:
    assert not list(Path(context.output_directory.name).rglob("*")), list(Path(context.output_directory.name).rglob("*"))


@then("the CLI printed the number of References and the size of the file")
def cli_printed(context) -> None:
    assert "12 references" in context.cli_output and "bytes" in context.cli_output, context.cli_output
