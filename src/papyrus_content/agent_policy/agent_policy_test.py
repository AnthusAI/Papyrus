import pytest

from papyrus_content.agent_policy import AgentPolicyStore, PolicyError, PolicyState, decide_start, effective, validate_document
from papyrus_content.images.handlers import Caller
from papyrus_content.site_store import SiteStore
from papyrus_content.site_store_test import FakeS3, FakeTable

ADMIN = Caller(kind="person", subject="ada", is_admin=True)


def make():
    table = FakeTable()
    return AgentPolicyStore(SiteStore(FakeS3(), "bucket", table, now=lambda: "2026-11-16T00:00:00Z")), table


def doc(agents=None, site=None):
    return {"schemaVersion": 1, "site": site or {}, "agents": agents or {}}


@pytest.mark.parametrize("bad, fragment", [
    ({"schemaVersion": 2, "site": {}, "agents": {}}, "schemaVersion"),
    (doc({"Rate": {"rung": "off"}}), "responsibility"),
    (doc({"rate": {"rung": "max"}}), "rung"),
    (doc({"rate": {"rung": "off", "paused": True}}), "pausedReason"),
    (doc({"rate": {"rung": "off", "loopLimit": 0}}), "loopLimit"),
    (doc({"rate": {"rung": "off", "overrides": [{"rung": "draft"}]}}), "at least one"),
    (doc({"rate": {"rung": "off", "overrides": [{"section": "a", "rung": "draft"}, {"section": "a", "rung": "prepare"}]}}), "unique"),
    (doc(site={"budget": {"amountUsd": -1, "period": "week"}}), "amountUsd"),
    (doc(site={"quietWindow": {"start": "22:00", "end": "06:00", "timeZone": "Nowhere/Land"}}), "timeZone"),
    (doc(site={"unknown": 1}), "unknown"),
])
def test_invalid_documents_name_the_field(bad, fragment):
    with pytest.raises(PolicyError) as error:
        validate_document(bad)
    assert error.value.code == "invalid_input" and fragment in error.value.message


def test_override_order_does_not_matter():
    entries = [{"channel": "x", "rung": "prepare"}, {"list": "w", "rung": "draft"}, {"channel": "x", "kind": "k", "rung": "observe"}]
    for ordering in (entries, entries[::-1]):
        state = PolicyState(1, doc({"announce": {"rung": "publish_soft", "overrides": ordering}}))
        assert effective(state, "announce", {"channel": "x", "kind": "k", "list": "w"}).rung == "draft"
        assert effective(state, "announce", {"channel": "x", "kind": "k"}).rung == "observe"
        assert effective(state, "announce", {"channel": "x"}).rung == "prepare"
        assert effective(state, "announce", {}).rung == "publish_soft"


def test_site_pause_wins_over_agent_state_and_names_version():
    state = PolicyState(7, doc({"rate": {"rung": "draft"}}, {"paused": True, "pausedReason": "audit"}))
    decision = decide_start(state, "rate")
    assert not decision.start and decision.run_fields() == {"policyVersion": 7, "rung": "draft"}


def test_stale_change_is_refused_and_writes_nothing(monkeypatch):
    store, table = make()
    store.set_rung("alpha", ADMIN, "rate", "observe", reason="one")
    real = store.read
    stale = real("alpha")
    store.set_rung("alpha", ADMIN, "rate", "draft", reason="two")
    monkeypatch.setattr(store, "read", lambda tenant: stale)
    with pytest.raises(PolicyError) as error:
        store.set_rung("alpha", ADMIN, "rate", "propose", reason="three")
    assert error.value.code == "stale_version"
    monkeypatch.undo()
    assert store.read("alpha").version == 2 and store.read("alpha").document["agents"]["rate"]["rung"] == "draft"


def test_unchanged_document_writes_no_version():
    store, _ = make()
    store.set_rung("alpha", ADMIN, "rate", "draft", reason="one")
    assert store.set_rung("alpha", ADMIN, "rate", "draft", reason="again").version == 1


def test_removing_the_last_override_and_unknown_scope():
    store, _ = make()
    store.set_rung("alpha", ADMIN, "improve", "prepare", reason="a")
    store.set_rung("alpha", ADMIN, "improve", "draft", reason="b", scope={"section": "briefs"})
    store.remove_override("alpha", ADMIN, "improve", {"section": "briefs"}, reason="c")
    assert store.read("alpha").document["agents"]["improve"] == {"rung": "prepare"}
    with pytest.raises(PolicyError):
        store.remove_override("alpha", ADMIN, "improve", {"section": "briefs"}, reason="d")
