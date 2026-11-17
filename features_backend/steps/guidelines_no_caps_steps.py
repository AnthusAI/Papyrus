"""A set of guideline files has no made-up limit (features_backend/guidelines-no-caps.feature). In-memory; the paging is the real client's own paging loop."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient  # noqa: E402
from papyrus_content.guidelines import field_files  # noqa: E402
from papyrus_content.guidelines.store import GuidelineStore  # noqa: E402
from features_backend.steps.guidelines_cloud_files_steps import rule_text, tone_files, write_folder  # noqa: E402


class PagedBackend:
    """The fake backend behind the real client's index paging: every list answers ``page`` rows and a token for the next page."""

    def __init__(self, backend, page: int):
        self._backend = backend
        self._page = page
        self.tenant_id = None

    def __getattr__(self, name):
        return getattr(self._backend, name)

    def graphql(self, query, variables):
        key = next(value for name, value in variables.items() if name not in ("limit", "nextToken"))
        rows = self._backend.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", key)
        start = int(variables.get("nextToken") or 0)
        end = start + self._page
        return {"listModelAttachmentsByOwnerRoleAndSortKey": {"items": rows[start:end], "nextToken": str(end) if end < len(rows) else None}}

    def list_by_index(self, index, key, **kwargs):
        if index != "modelAttachmentsByOwnerRoleAndSortKey":
            return self._backend.list_by_index(index, key, **kwargs)
        return PapyrusGraphQLAuthoringClient.list_by_index(self, index, key, **kwargs)


@given("a folder of {count:d} guideline files")
def step_many(context, count):
    context.files_in = {**tone_files("Warm."), **{f"rule-{n:04d}/GUIDELINE.md": rule_text(f"rule-{n:04d}", avoid=[f"word{n}"]) for n in range(count - 1)}}
    context.folder = write_folder(context, context.files_in)


@given("a folder with one guideline file of {kib:d} KiB")
def step_big(context, kib):
    long_tone = "Warm and plain. " * (kib * 1024 // 16)
    context.files_in = tone_files(long_tone)
    assert max(len(text.encode("utf-8")) for text in context.files_in.values()) > kib * 1024
    context.folder = write_folder(context, context.files_in)


@given("the database answers each attachment query one page of {page:d} rows at a time")
def step_paged(context, page):
    context.backend = PagedBackend(context.backend, page)
    context.store = GuidelineStore(context.backend, context.files)


@then("resolving the writing guidelines finds every rule of the folder")
def step_resolved(context):
    stored = GuidelineStore(context.backend, context.files).read("writing")["files"]
    wanted = {path for path in context.files_in if path.endswith("/GUIDELINE.md") and not path.startswith("tone/")}   # the tone file is a field of the document, not a rule
    assert wanted and stored == context.files_in
    assert {rule["files"][0] for rule in field_files.view_of(stored).rules} and len(field_files.view_of(stored).rules) == len(wanted)
