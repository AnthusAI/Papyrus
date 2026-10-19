import re

import pytest

from papyrus_content.graphql_authoring import LIST_DEFINITIONS
from papyrus_content.tenant_adoption import apply_tenant_adoption, plan_tenant_adoption
from papyrus_content.tenant_adoption_commands import adoption_tenant_from_options
from procedures.newsroom.tests.test_tenancy import InMemoryGraphQLBackend, tenant_client

LIST_FIELD_TO_MODEL = {definition["field"]: model for model, definition in LIST_DEFINITIONS.items()}
MUTATION_PATTERN = re.compile(r"\b(?:create|update|delete)[A-Z]\w+\(input")


class LegacyBackend(InMemoryGraphQLBackend):
    def _read(self, field, variables):
        if field in LIST_FIELD_TO_MODEL:
            return {"items": [dict(row) for row in self.tables.get(LIST_FIELD_TO_MODEL[field], {}).values()], "nextToken": None}
        return super()._read(field, variables)

    @property
    def mutation_count(self):
        return sum(1 for query, _ in self.queries if MUTATION_PATTERN.search(query))


def legacy_backend():
    backend = LegacyBackend()
    backend.tables = {
        "Item": {
            "item-articles-hello": {"id": "item-articles-hello", "slug": "hello", "typeStatus": "article#published", "sectionStatus": "articles#published"},
            "item-page-about": {"id": "item-page-about", "slug": "about", "typeStatus": "page#draft"},
        },
        "PublishedItem": {
            "published-item-articles-hello": {"id": "published-item-articles-hello", "slug": "hello", "typeStatus": "article#published", "sectionStatus": "articles#published"},
        },
        "MediaAsset": {"media-1": {"id": "media-1", "itemId": "item-articles-hello", "storagePath": "media/a/b.png"}},
        "PublishedMediaAsset": {"pmedia-1": {"id": "pmedia-1", "storagePath": "media/a/b.png"}},
        "NewsroomSection": {
            "mission": {"id": "mission", "title": "Mission", "sortOrder": 1},
            "world": {"id": "world", "title": "World", "tenantId": "alpha", "sortOrder": 2},
        },
    }
    return backend


def run_adoption(backend, tenant="alpha", apply=True):
    client = tenant_client(backend, None)
    plan = plan_tenant_adoption(client, tenant)
    return plan, apply_tenant_adoption(client, plan) if apply else None


def test_a_dry_run_reports_what_it_would_adopt_and_writes_nothing():
    backend = legacy_backend()
    plan, _ = run_adoption(backend, apply=False)
    report = plan.to_dict()
    assert report["models"]["Item"]["counts"]["adopt"] == 2
    assert report["models"]["NewsroomSection"]["counts"]["reid"] == 2
    assert report["models"]["MediaAsset"]["sample"]["adopt"] == ["media-1"]
    assert backend.mutation_count == 0


def test_applying_stamps_the_tenant_and_index_fields_without_changing_ids_or_storage_paths():
    backend = legacy_backend()
    run_adoption(backend)
    hello = backend.tables["Item"]["item-articles-hello"]
    assert hello["tenantId"] == "alpha"
    assert hello["tenantSlug"] == "alpha#hello"
    assert hello["typeStatus"] == "alpha#article#published"
    assert hello["sectionStatus"] == "alpha#articles#published"
    assert "sectionStatus" not in backend.tables["Item"]["item-page-about"]
    assert backend.tables["MediaAsset"]["media-1"]["storagePath"] == "media/a/b.png"
    assert backend.tables["PublishedMediaAsset"]["pmedia-1"]["tenantId"] == "alpha"
    assert set(backend.tables["Item"]) == {"item-articles-hello", "item-page-about"}


def test_applying_moves_bare_sections_to_tenant_scoped_ids_whether_or_not_they_carried_a_tenant():
    backend = legacy_backend()
    run_adoption(backend)
    assert sorted(backend.tables["NewsroomSection"]) == ["alpha#mission", "alpha#world"]
    assert backend.tables["NewsroomSection"]["alpha#mission"]["title"] == "Mission"
    assert backend.tables["NewsroomSection"]["alpha#world"]["tenantId"] == "alpha"


def test_a_tenant_client_finds_adopted_rows_by_id_and_by_list():
    backend = legacy_backend()
    run_adoption(backend)
    alpha = tenant_client(backend, "alpha")
    assert alpha.get_record("NewsroomSection", "mission")["title"] == "Mission"
    assert {row["id"] for row in alpha.list_records("Item")} == {"item-articles-hello", "item-page-about"}


def test_a_second_run_finds_nothing_to_do_and_writes_nothing():
    backend = legacy_backend()
    run_adoption(backend)
    mutations_after_first_run = backend.mutation_count
    plan, written = run_adoption(backend)
    assert plan.pending_writes == 0
    assert written == {"adopted": 0, "reidentified": 0}
    assert backend.mutation_count == mutations_after_first_run


def test_rows_of_a_different_tenant_are_never_touched_and_are_reported():
    backend = legacy_backend()
    backend.tables["Item"]["item-other"] = {"id": "item-other", "slug": "other", "tenantId": "beta", "typeStatus": "beta#article#draft"}
    backend.tables["NewsroomSection"]["beta#mission"] = {"id": "beta#mission", "tenantId": "beta", "title": "Beta"}
    before = {name: {key: dict(row) for key, row in rows.items()} for name, rows in backend.tables.items()}
    plan, _ = run_adoption(backend)
    assert plan.to_dict()["models"]["Item"]["sample"]["otherTenant"] == ["item-other"]
    assert plan.to_dict()["models"]["NewsroomSection"]["counts"]["otherTenant"] == 1
    assert backend.tables["Item"]["item-other"] == before["Item"]["item-other"]
    assert backend.tables["NewsroomSection"]["beta#mission"] == before["NewsroomSection"]["beta#mission"]


def test_a_bare_section_next_to_an_existing_scoped_section_is_left_alone_and_reported():
    backend = legacy_backend()
    backend.tables["NewsroomSection"]["alpha#mission"] = {"id": "alpha#mission", "tenantId": "alpha", "title": "Newer"}
    plan, _ = run_adoption(backend)
    assert plan.to_dict()["models"]["NewsroomSection"]["counts"]["conflicts"] == 1
    assert backend.tables["NewsroomSection"]["mission"]["title"] == "Mission"
    assert backend.tables["NewsroomSection"]["alpha#mission"]["title"] == "Newer"


def test_the_command_refuses_to_run_without_a_tenant(monkeypatch):
    monkeypatch.delenv("PAPYRUS_TENANT_ID", raising=False)
    with pytest.raises(ValueError):
        adoption_tenant_from_options({})


def test_the_command_refuses_to_run_when_the_tenant_environment_variable_is_set(monkeypatch):
    monkeypatch.setenv("PAPYRUS_TENANT_ID", "alpha")
    with pytest.raises(ValueError):
        adoption_tenant_from_options({"tenant": "alpha"})


def test_the_command_accepts_a_valid_tenant_flag(monkeypatch):
    monkeypatch.delenv("PAPYRUS_TENANT_ID", raising=False)
    assert adoption_tenant_from_options({"tenant": "p-apyr-us"}) == "p-apyr-us"
