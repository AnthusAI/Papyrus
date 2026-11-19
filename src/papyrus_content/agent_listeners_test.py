"""The listener index: derived from definitions, read by its live version (the behaviour is in features_backend/item-change-feed.feature)."""
from types import SimpleNamespace

from papyrus_content import agent_listeners as listeners
from papyrus_content.site_store import SiteStore
from papyrus_content.site_store_test import FakeS3, FakeTable


def definition(agent, *changes, paid=False):
    return SimpleNamespace(id=agent, responsibility="r-" + agent, data={"procedure": f"p.{agent}", "paid": paid, "serialBy": "subject", "wakes": {"changes": list(changes)}})


def store():
    return SiteStore(FakeS3(), "bucket", FakeTable(), now=lambda: "2026-11-18T00:00:00Z")


def test_build_is_keyed_by_change_in_agent_order_and_ignores_schedule_only_agents():
    document = listeners.build([definition("b", {"kind": "Item", "change": "version_created"}), definition("a", {"kind": "Item", "change": "version_created", "filter": {"type": "story"}}),
                                SimpleNamespace(id="c", responsibility="r-c", data={"procedure": "p.c", "paid": False, "serialBy": "agent", "wakes": {"schedule": {}}})])
    assert [entry["agent"] for entry in document["changes"]["Item/version_created"]] == ["a", "b"] and list(document["changes"]) == ["Item/version_created"]
    assert document["changes"]["Item/version_created"][0]["filter"] == {"type": "story"}


def test_publish_writes_once_and_only_a_change_writes_again():
    site = store()
    first = listeners.publish(site, "alpha", [definition("a", {"kind": "Item", "change": "stage_entered"})], actor="release", apply=True)
    assert (first["action"], first["version"], first["applied"]) == ("created", 1, True)
    same = listeners.publish(site, "alpha", [definition("a", {"kind": "Item", "change": "stage_entered"})], actor="release", apply=True)
    assert (same["action"], same["applied"]) == ("unchanged", False) and site.current_version("alpha", "listeners") == 1
    dry = listeners.publish(site, "alpha", [], actor="release", apply=False)
    assert (dry["action"], dry["applied"]) == ("updated", False) and site.current_version("alpha", "listeners") == 1
    assert listeners.publish(site, "alpha", [], actor="release", apply=True)["version"] == 2


def test_the_index_holds_its_version_until_the_live_version_moves():
    site = store()
    s3 = site._s3
    gets = []
    original = s3.get_object
    s3.get_object = lambda **kwargs: (gets.append(1), original(**kwargs))[1]
    index = listeners.ListenerIndex(site, "alpha")
    assert index.document() == {}   # nothing written: nobody listens
    listeners.publish(site, "alpha", [definition("a", {"kind": "Item", "change": "stage_entered"})], actor="release", apply=True)
    gets.clear()
    assert index.document()["changes"] and index.document()["changes"] and len(gets) == 1
    listeners.publish(site, "alpha", [definition("b", {"kind": "Item", "change": "stage_entered"})], actor="release", apply=True)
    gets.clear()
    assert [entry["agent"] for entry in index.document()["changes"]["Item/stage_entered"]] == ["b"] and len(gets) == 1
