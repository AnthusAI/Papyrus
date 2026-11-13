from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_wiki import commands as wiki_commands  # noqa: E402
from papyrus_content.knowledge_wiki.pages import KIND_ENTITY, PageSpec, front_matter_yaml  # noqa: E402
from papyrus_content.knowledge_wiki.sync import apply_plan, plan_sync  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item  # noqa: E402
from papyrus_content.tenancy import TenantError  # noqa: E402
from papyrus_content.wiki_stamp import WIKI_PAGE_ITEM_TYPE, review_mapping  # noqa: E402
from procedures.newsroom.tests.test_knowledge_wiki import WikiClient  # noqa: E402
from procedures.newsroom.tests.test_tenancy import InMemoryGraphQLBackend, tenant_client  # noqa: E402

DAY = "2026-11-12"


@given("a backend shared by two tenants")
def step_shared(context):
    context.backend = InMemoryGraphQLBackend()


@when('the wiki page "{title}" is written and published as the tenant "{tenant}"')
def step_write(context, title, tenant):
    client = tenant_client(context.backend, tenant)
    spec = PageSpec(KIND_ENTITY, f"maker--{title.lower().replace(' ', '-')}", f"maker-{title.lower().replace(' ', '-')}", {"title": title, "entityKey": "maker--acme"}, f"{title} makes looms.\n")
    plan = plan_sync([spec], {KIND_ENTITY: "wiki"}, [], {})
    apply_plan(client, plan, actor="ai")
    page = plan.pages[0]
    stamped = {"title": title, "entityKey": "maker--acme", "review": review_mapping("ai", None, DAY), "updated": DAY}
    save_item(
        client,
        ItemFields(type=WIKI_PAGE_ITEM_TYPE, slug=spec.slug, section="wiki", front_matter_yaml=front_matter_yaml(stamped), body_markus=spec.body, aliases=[], id=page.lineage_id),
        actor="ai",
    )
    publish_item(client, page.lineage_id, actor="ai")
    context.page_id, context.tenant, context.slug = page.lineage_id, tenant, spec.slug


@then('the page\'s Item and PublishedItem rows both carry the tenant id "{tenant}"')
def step_ids(context, tenant):
    rows = _rows(context)
    assert [row["tenantId"] for row in rows] == [tenant, tenant], rows


@then("both rows carry the tenant slug, the type status and the section status prefixed with the tenant")
def step_prefixed(context):
    item, published = _rows(context)
    prefix = f"{context.tenant}#"
    for row in (item, published):
        assert row["tenantSlug"] == f"{prefix}{context.slug}", row
        assert row["typeStatus"].startswith(prefix) and row["sectionStatus"].startswith(prefix), row


@then('the tenant "{tenant}" lists the page among its published wiki pages')
def step_lists(context, tenant):
    assert [row["slug"] for row in _published_wiki(context, tenant)] == [context.slug]


@then('the tenant "{tenant}" lists no wiki page')
def step_none(context, tenant):
    assert _published_wiki(context, tenant) == []


def _rows(context):
    item = context.backend.tables["Item"][context.page_id]
    published = next(iter(context.backend.tables["PublishedItem"].values()))
    return [item, published]


def _published_wiki(context, tenant):
    return [row for row in tenant_client(context.backend, tenant).list_records("PublishedItem") if row.get("type") == WIKI_PAGE_ITEM_TYPE]


def _tenanted_backend(context, tenant):
    client = WikiClient()
    row = {"id": "item-posts-alpha", "type": "article", "slug": "alpha", "section": "posts", "status": "published", "versionState": "current"}
    client.tables["Item"] = {row["id"]: {**row, **({"tenantId": tenant} if tenant else {})}}
    for module in (wiki_commands,):
        patcher = mock.patch.object(module, "create_authoring_client", lambda *args, **kwargs: (client, {}))
        patcher.start()
        context.add_cleanup(patcher.stop)
    context.client, context.refusal, context.writes_before = client, None, len(client.write_calls())


@given('a backend whose Items belong to the tenant "{tenant}"')
def step_tenanted(context, tenant):
    _tenanted_backend(context, tenant)


@given("a backend whose Items belong to no tenant")
def step_untenanted(context):
    _tenanted_backend(context, None)


def _attempt(context, command, flags):
    try:
        command(flags)
    except TenantError as error:
        context.refusal = str(error)


@when("the wiki sync runs with no tenant")
def step_sync(context):
    _attempt(context, wiki_commands.knowledge_wiki_sync, ["--apply"])


@when("the wiki publish runs with no tenant")
def step_publish(context):
    _attempt(context, wiki_commands.knowledge_wiki_publish, ["--all-drafts", "--actor", "ai", "--apply", "--no-trigger", "--on", DAY])


@then('the command is refused saying the Items belong to "{tenant}" and nothing is written')
def step_refused(context, tenant):
    assert context.refusal and f"Items belong to tenant {tenant}" in context.refusal, context.refusal
    assert len(context.client.write_calls()) == context.writes_before


@then("the command is not refused")
def step_not_refused(context):
    assert context.refusal is None
