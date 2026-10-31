"""A publication starts with working editorial policies: the default starter packs are imported once, as data."""
import json

from papyrus_content import editorial_checks as editorial


class MemoryStore:
    def __init__(self, policies=None, settings=None):
        self.policies = list(policies or [])
        self.settings = settings
        self.settings_writes = []

    def list_policies(self):
        return list(self.policies)

    def get_settings(self):
        return None if self.settings is None else {"id": "settings", "settings": json.dumps(self.settings)}

    def create_policy(self, record):
        self.policies.append(record)

    def update_policy(self, record):
        self.policies = [record if row["id"] == record["id"] else row for row in self.policies]

    def put_settings(self, values, *, exists):
        self.settings_writes.append(exists)
        self.settings = values

    def list_feedback(self):
        return []


def test_a_site_with_no_policies_gets_the_default_starter_pack():
    store = MemoryStore()
    result = editorial.ensure_default_policies(store)
    assert result["packs"]["ai-writing-tells"]["created"] > 0
    assert {row["source"] for row in store.policies} == {"starter:ai-writing-tells"}
    assert store.settings["defaultStarterPacks"] == ["ai-writing-tells"]
    assert store.settings_writes == [False]


def test_running_again_adds_nothing_even_after_an_admin_deleted_every_policy():
    store = MemoryStore()
    editorial.ensure_default_policies(store)
    store.policies = []
    result = editorial.ensure_default_policies(store)
    assert result["packs"]["ai-writing-tells"] == {"created": 0, "skipped": 0, "alreadyApplied": True}
    assert store.policies == []


def test_existing_settings_are_kept_and_updated_in_place():
    store = MemoryStore(settings={"enabled": False, "guidance": "House style."})
    editorial.ensure_default_policies(store)
    assert store.settings["enabled"] is False and store.settings["guidance"] == "House style."
    assert store.settings_writes == [True]


def test_a_policy_the_site_already_has_is_left_alone():
    store = MemoryStore()
    editorial.ensure_default_policies(store, packs=("ai-writing-tells",))
    edited = dict(store.policies[0], title="Edited by an admin")
    fresh = MemoryStore(policies=[edited])
    editorial.ensure_default_policies(fresh)
    assert next(row for row in fresh.policies if row["id"] == edited["id"])["title"] == "Edited by an admin"


class CheckingStore(MemoryStore):
    def __init__(self, items, **kwargs):
        super().__init__(**kwargs)
        self.items = {item["id"]: item for item in items}
        self.runs = {}

    def get_item(self, item_id):
        return self.items.get(item_id)

    def put_check_run(self, record):
        self.runs[record["id"]] = record

    def get_check_run(self, item_id):
        return self.runs.get(item_id)

    def list_check_runs_by_lineage(self, lineage_id, limit):
        return sorted((run for run in self.runs.values() if run["lineageId"] == lineage_id), key=lambda run: -run["versionNumber"])[:limit]

    def get_editorial_context(self, section):
        from papyrus_content.editorial_context import build_context
        return build_context({"key": "example"}, {"sectionId": section}, [
            {"scope": "publication", "kind": "policy", "text": "Synthetic", "source": {"id": "p"}}], mode="cloud")


def test_a_saved_version_is_checked_and_the_result_is_stored_with_it():
    store = CheckingStore([{"id": "story-v2", "lineageId": "story", "versionNumber": 2, "section": "news", "contentHash": "h2",
                            "bodyMarkus": "Great question! Let's delve into this game-changing landscape."}])
    editorial.ensure_default_policies(store)
    services = editorial.Services(store=store, decision_model=None, generator=None)
    summary = editorial.check_item_version({"itemId": "story-v2"}, services)
    run = store.runs["story-v2"]
    assert run["lineageId"] == "story" and run["versionNumber"] == 2 and run["contentHash"] == "h2"
    assert summary["violations"] == run["violations"] and run["violations"] > 0
    assert all({"id", "policyId", "status"} <= set(finding) for finding in run["findings"])


def test_identical_content_is_checked_once():
    body = "Great question! Let's delve into this game-changing landscape."
    store = CheckingStore([{"id": "story-v1", "lineageId": "story", "versionNumber": 1, "section": "news", "contentHash": "h", "bodyMarkus": body},
                           {"id": "story-v2", "lineageId": "story", "versionNumber": 2, "section": "news", "contentHash": "h", "bodyMarkus": body}])
    editorial.ensure_default_policies(store)
    first = editorial.Services(store=store, decision_model=None, generator=None)
    editorial.check_item_version({"itemId": "story-v1"}, first)
    assert first.last_check_request is not None
    again = editorial.Services(store=store, decision_model=None, generator=None)
    summary = editorial.check_item_version({"itemId": "story-v2"}, again)
    assert again.last_check_request is None and summary["skipped"] == "unchanged"
    assert store.runs["story-v2"]["findings"] == store.runs["story-v1"]["findings"] and store.runs["story-v2"]["versionNumber"] == 2


def test_checks_turned_off_are_a_skip_not_an_error():
    store = CheckingStore([{"id": "story-v1", "bodyMarkus": "Text."}], settings={"enabled": False})
    result = editorial.check_item_version({"itemId": "story-v1"}, editorial.Services(store=store, decision_model=None, generator=None))
    assert result == {"itemId": "story-v1", "skipped": "disabled"} and store.runs == {}


def test_the_starter_pack_catalog_comes_from_humanus_at_run_time():
    from humanus.packs import list_builtin_packs
    store = MemoryStore()
    editorial.ensure_default_policies(store)
    catalog = editorial.list_starter_packs({}, editorial.Services(store=store))
    assert [pack["name"] for pack in catalog["packs"]] == list_builtin_packs()
    tells = next(pack for pack in catalog["packs"] if pack["name"] == "ai-writing-tells")
    assert tells["isDefault"] and tells["importedCount"] == tells["policyCount"] > 0 and tells["title"]


def test_drafts_needing_a_check_are_unpublished_and_unchecked_or_changed():
    from papyrus_content.editorial_commands import unchecked_draft_versions
    items = [
        {"id": "a-v1", "type": "article", "versionState": "draft", "status": "draft", "contentHash": "1"},
        {"id": "b-v1", "type": "article", "versionState": "draft", "status": "draft", "contentHash": "2"},
        {"id": "c-v1", "type": "article", "versionState": "draft", "status": "draft", "contentHash": "new"},
        {"id": "d-v1", "type": "article", "versionState": "current", "status": "published", "contentHash": "4"},
        {"id": "e-v1", "type": "doctrine", "versionState": "current", "status": "private", "contentHash": "5"},
        {"id": "f-v1", "type": "article", "versionState": "superseded", "status": "draft", "contentHash": "6"},
    ]
    runs = [{"id": "b-v1", "contentHash": "2"}, {"id": "c-v1", "contentHash": "old"}]
    assert [item["id"] for item in unchecked_draft_versions(items, runs)] == ["a-v1", "c-v1"]
