from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.tenant_section_ids_test import InMemoryNewsroomSectionBackend, client_for, section_record  # noqa: E402
from papyrus_content.tenant_adoption import apply_tenant_adoption, plan_tenant_adoption  # noqa: E402


def mutation_count(backend) -> int:
    from papyrus_content.tenant_adoption_test import MUTATION_PATTERN

    return sum(1 for query, _ in backend.queries if MUTATION_PATTERN.search(query))


class RecordingSectionBackend(InMemoryNewsroomSectionBackend):
    def __init__(self):
        super().__init__()
        self.queries = []

    def __call__(self, query, variables=None):
        self.queries.append((query, variables))
        return super().__call__(query, variables)


@given('a backend shared by the tenants "{first}" and "{second}"')
def shared_backend(context, first: str, second: str) -> None:
    from papyrus_content.markus_import_tenant_test import ImportBackend
    from procedures.newsroom.tests.test_tenancy import tenant_client

    context.sections_backend = RecordingSectionBackend()
    context.items_backend = ImportBackend()
    context.tenant_ids = (first, second)
    context.tenant_item_client = lambda tenant: tenant_client(context.items_backend, tenant)
    context.temp = Path(tempfile.mkdtemp())
    context.tenant_imports = {}


@given('tenant "{tenant}" has the Section "{key}" titled "{title}"')
def tenant_has_section(context, tenant: str, key: str, title: str) -> None:
    client_for(context.sections_backend, tenant).upsert("NewsroomSection", section_record(key, title))


@when('tenant "{tenant}" renames the Section "{key}" to "{title}"')
def tenant_renames_section(context, tenant: str, key: str, title: str) -> None:
    client_for(context.sections_backend, tenant).update_record("NewsroomSection", section_record(key, title))


@then('tenant "{tenant}" lists only the Section titles "{titles}"')
def tenant_lists_only_titles(context, tenant: str, titles: str) -> None:
    listed = [row["title"] for row in client_for(context.sections_backend, tenant).list_records("NewsroomSection")]
    assert listed == titles.split(", "), listed


def import_content_directory(context, tenant: str) -> None:
    from papyrus_content.markus_import_tenant_test import content_directory, import_for

    content = content_directory(context.temp, tenant, tenant.title())
    report = import_for(tenant, content, context.tenant_item_client(tenant), context.temp / "bucket")
    assert report.ok, report.errors


@given('tenant "{tenant}" has imported its content directory')
def tenant_has_imported(context, tenant: str) -> None:
    import_content_directory(context, tenant)
    context.tenant_imports[tenant] = copy.deepcopy(context.items_backend.tables["Item"])


@when('tenant "{tenant}" imports its content directory')
def tenant_imports(context, tenant: str) -> None:
    import_content_directory(context, tenant)


@then('tenant "{tenant}" still has exactly the items it imported')
def tenant_items_unchanged(context, tenant: str) -> None:
    items = context.items_backend.tables["Item"]
    for item_id, row in context.tenant_imports[tenant].items():
        assert items[item_id] == row, item_id


@then('tenant "{tenant}" has its own items with the same slugs')
def tenant_has_own_items(context, tenant: str) -> None:
    items = context.items_backend.tables["Item"]
    own = {item_id: row for item_id, row in items.items() if row["tenantId"] == tenant}
    other = {item_id: row for item_id, row in items.items() if row["tenantId"] != tenant}
    assert own and own.keys().isdisjoint(other.keys())
    assert {row["slug"] for row in own.values()} == {row["slug"] for row in other.values()}


@when("each tenant's site cyclotron is built")
def build_each_cyclotron(context) -> None:
    from papyrus_content.site_cyclotron import build_site_cyclotron, newsroom_sections_of_tenant, tenant_site_cyclotron_steering
    from papyrus_content.site_sweep_test import prepared

    steering = prepared(context.temp)
    context.cyclotron_plans = {}
    for tenant in context.tenant_ids:
        sections = newsroom_sections_of_tenant(client_for(context.sections_backend, tenant), tenant)
        context.cyclotron_plans[tenant] = build_site_cyclotron(tenant_site_cyclotron_steering(steering, tenant), sections)


@then('tenant "{tenant}" has a site cyclotron with the Sections "{sections}"')
def cyclotron_has_sections(context, tenant: str, sections: str) -> None:
    from papyrus_content.site_cyclotron import SECTION_FIT_CLASSIFIER_PREFIX, section_fit_classifier_id

    classifiers = {spec.id for spec in context.cyclotron_plans[tenant].definition.classifiers}
    fit = {classifier for classifier in classifiers if classifier.startswith(SECTION_FIT_CLASSIFIER_PREFIX)}
    assert fit == {section_fit_classifier_id(key) for key in sections.split(", ")}, fit


@then("the two site cyclotrons have different ids")
def cyclotron_ids_differ(context) -> None:
    first, second = (context.cyclotron_plans[tenant] for tenant in context.tenant_ids)
    assert first.local_path != second.local_path


@given("a backend holding rows written before tenant scoping")
def legacy_rows(context) -> None:
    from papyrus_content.tenant_adoption_test import legacy_backend
    from procedures.newsroom.tests.test_tenancy import tenant_client

    context.legacy = legacy_backend()
    context.legacy_client = lambda tenant: tenant_client(context.legacy, tenant)


@when('the adoption dry run for tenant "{tenant}" is run')
def adoption_dry_run(context, tenant: str) -> None:
    context.mutations_before = mutation_count(context.legacy)
    context.adoption_plan = plan_tenant_adoption(context.legacy_client(None), tenant)


@when('the adoption for tenant "{tenant}" is applied')
def adoption_applied(context, tenant: str) -> None:
    context.mutations_before = mutation_count(context.legacy)
    client = context.legacy_client(None)
    apply_tenant_adoption(client, plan_tenant_adoption(client, tenant))


@then("it would adopt {items:d} items and re-id {sections:d} Sections")
def dry_run_counts(context, items: int, sections: int) -> None:
    counts = context.adoption_plan.to_dict()["models"]
    assert counts["Item"]["counts"]["adopt"] == items
    assert counts["NewsroomSection"]["counts"]["reid"] == sections


@then("nothing was written to the legacy backend")
def no_records_written(context) -> None:
    assert mutation_count(context.legacy) == context.mutations_before


@then('tenant "{tenant}" sees the Section "{key}" by id and {count:d} items by list')
def tenant_sees_adopted(context, tenant: str, key: str, count: int) -> None:
    client = context.legacy_client(tenant)
    assert client.get_record("NewsroomSection", key) is not None
    assert len(client.list_records("Item")) == count


@then("the media storage path is unchanged")
def media_path_unchanged(context) -> None:
    assert context.legacy.tables["MediaAsset"]["media-1"]["storagePath"] == "media/a/b.png"
