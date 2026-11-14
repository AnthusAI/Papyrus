from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.guidelines import GuidelineStore  # noqa: E402
from papyrus_content.guidelines.fakes import FakeBackend, FakeFiles  # noqa: E402
from papyrus_content.publishing import DryRunClient  # noqa: E402

DOCUMENT = {"schemaVersion": 1, "voice": {"name": "House"}, "tone": ["Warm."], "bodyMarkus": "Write plainly."}


def site(context, tenant):
    context.backend = FakeBackend(tenant_id=tenant)
    GuidelineStore(context.backend, FakeFiles(context.backend)).save(
        "writing", DOCUMENT, expected_current_version_id="none", actor="Ada Admin", reason="First guidelines", now="2026-11-14T10:00:00Z")


@given('a site whose tenant is "{tenant}" has saved writing guidelines')
def tenant_site(context, tenant):
    site(context, tenant)


@given("a site with no tenant has saved writing guidelines")
def no_tenant_site(context):
    site(context, None)


@when("the operator previews a publish through a dry run")
def preview(context):
    context.dry_run = DryRunClient(context.backend)
    context.error, context.found = None, None
    try:
        context.found = GuidelineStore(context.dry_run, FakeFiles(context.backend)).read("writing")
    except ValueError as error:
        context.error = error


@then("the dry run reads the saved writing guidelines")
def reads(context):
    assert context.error is None, str(context.error)
    assert context.found and context.found["document"]["voice"]["name"] == "House"


@then('the dry run is in the tenant "{tenant}"')
def in_tenant(context, tenant):
    assert context.dry_run.tenant_id == tenant
