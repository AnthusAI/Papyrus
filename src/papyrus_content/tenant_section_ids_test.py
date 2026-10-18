import copy
import re

from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
from papyrus_content.newsroom_sections import build_newsroom_section_records, load_newsroom_section_seeds
from papyrus_content.tenancy import tenant_stamped_payload

ENDPOINT = "https://example.invalid/graphql"


class InMemoryNewsroomSectionBackend:
    def __init__(self):
        self.rows = {}

    def __call__(self, query, variables=None):
        variables = variables or {}
        mutation = re.search(r"\b(create|update|delete)NewsroomSection\(input", query)
        if mutation:
            payload = variables["input"]
            if mutation.group(1) == "delete":
                self.rows.pop(payload["id"], None)
            elif mutation.group(1) == "create":
                assert payload["id"] not in self.rows
                self.rows[payload["id"]] = copy.deepcopy(payload)
            else:
                self.rows[payload["id"]].update(copy.deepcopy(payload))
            return {}
        if "getNewsroomSection" in query:
            return {"getNewsroomSection": copy.deepcopy(self.rows.get(variables["id"]))}
        return {"listNewsroomSections": {"items": copy.deepcopy(list(self.rows.values())), "nextToken": None}}


def client_for(backend, tenant_id):
    client = PapyrusGraphQLAuthoringClient(endpoint=ENDPOINT, header_factory=lambda payload: {}, tenant_id=tenant_id)
    client.graphql = backend
    return client


def section_record(section_key, title):
    return {"id": section_key, "title": title, "shortTitle": title, "type": "canonical", "editorialMission": "m",
            "editorialPolicy": "p", "enabled": True, "enabledStatus": "enabled", "sortOrder": 1}


def test_a_client_without_a_tenant_stores_the_bare_section_key():
    backend = InMemoryNewsroomSectionBackend()
    client = client_for(backend, None)
    client.upsert("NewsroomSection", section_record("mission", "Mission"))
    assert list(backend.rows) == ["mission"]
    assert "tenantId" not in backend.rows["mission"]
    assert client.get_record("NewsroomSection", "mission")["id"] == "mission"


def test_a_tenant_client_stores_the_section_under_a_tenant_scoped_id():
    backend = InMemoryNewsroomSectionBackend()
    client_for(backend, "alpha").upsert("NewsroomSection", section_record("mission", "Alpha Mission"))
    assert list(backend.rows) == ["alpha#mission"]
    assert backend.rows["alpha#mission"]["tenantId"] == "alpha"


def test_a_tenant_client_reads_sections_back_under_the_bare_section_key():
    backend = InMemoryNewsroomSectionBackend()
    client = client_for(backend, "alpha")
    client.upsert("NewsroomSection", section_record("mission", "Alpha Mission"))
    assert [row["id"] for row in client.list_records("NewsroomSection")] == ["mission"]
    assert client.get_record("NewsroomSection", "mission")["id"] == "mission"
    assert client.get_record("NewsroomSection", "mission")["storedId"] == "alpha#mission"
    assert set(client.get_records_by_id("NewsroomSection", ["mission"])) == {"mission"}


def test_two_tenants_with_the_same_section_key_each_list_only_their_own():
    backend = InMemoryNewsroomSectionBackend()
    alpha, beta = client_for(backend, "alpha"), client_for(backend, "beta")
    alpha.upsert("NewsroomSection", section_record("mission", "Alpha Mission"))
    beta.upsert("NewsroomSection", section_record("mission", "Beta Mission"))
    assert sorted(backend.rows) == ["alpha#mission", "beta#mission"]
    assert [row["title"] for row in alpha.list_records("NewsroomSection")] == ["Alpha Mission"]
    assert [row["title"] for row in beta.list_records("NewsroomSection")] == ["Beta Mission"]


def test_writing_a_section_in_one_tenant_never_changes_the_other_tenants_section():
    backend = InMemoryNewsroomSectionBackend()
    alpha, beta = client_for(backend, "alpha"), client_for(backend, "beta")
    alpha.upsert("NewsroomSection", section_record("mission", "Alpha Mission"))
    beta.upsert("NewsroomSection", section_record("mission", "Beta Mission"))
    alpha.update_record("NewsroomSection", section_record("mission", "Alpha Renamed"))
    assert beta.get_record("NewsroomSection", "mission")["title"] == "Beta Mission"
    alpha.delete_record("NewsroomSection", "mission")
    assert beta.get_record("NewsroomSection", "mission")["title"] == "Beta Mission"
    assert alpha.get_record("NewsroomSection", "mission") is None


def test_a_row_read_back_can_be_written_again_without_double_scoping():
    backend = InMemoryNewsroomSectionBackend()
    client = client_for(backend, "alpha")
    client.upsert("NewsroomSection", section_record("mission", "Alpha Mission"))
    row = client.get_record("NewsroomSection", "mission")
    row["title"] = "Edited"
    client.update_record("NewsroomSection", row)
    assert list(backend.rows) == ["alpha#mission"]
    assert "storedId" not in backend.rows["alpha#mission"]


def test_seeded_section_records_keep_the_bare_key_until_the_client_writes_them():
    sections = load_newsroom_section_seeds()
    records = build_newsroom_section_records(sections[:1], now="2026-10-18T00:00:00Z")
    expected = records[0]["expected"]
    assert expected["id"] == sections[0]["id"]
    assert tenant_stamped_payload("NewsroomSection", "alpha", expected)["id"] == f"alpha#{sections[0]['id']}"
    assert tenant_stamped_payload("Item", "alpha", {"id": "x"})["id"] == "x"
