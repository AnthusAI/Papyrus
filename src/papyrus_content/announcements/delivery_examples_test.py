from papyrus_content.announcements import delivery_examples as de
from papyrus_content.announcements.records import ATTEMPT_SENT, SENT


def row(**changes):
    return {"state": SENT, "attempts": [{"outcome": ATTEMPT_SENT, "version": 2}], "versions": [{"number": 1, "owner": "machine"}, {"number": 2, "owner": "human"}], **changes}


def test_final_version_is_the_one_that_went_out():
    assert de.final_version(row()) == 2


def test_a_preferred_version_is_final_over_what_went_out():
    assert de.final_version(row(preferredVersion=3)) == 3


def test_nothing_is_final_before_the_send():
    assert de.final_version(row(state="ready", attempts=[])) is None


def test_machine_version_is_the_newest_machine_one_at_or_before_the_final():
    versions = [{"number": 1, "owner": "machine"}, {"number": 2, "owner": "human"}, {"number": 3, "owner": "machine"}, {"number": 4, "owner": "human"}]
    assert de.machine_version({"versions": versions}, 4) == 3
    assert de.machine_version({"versions": versions}, 2) == 1


def test_a_person_changed_a_version_only_when_a_block_is_theirs():
    assert de.person_changed({"blocks": [{"owner": "machine", "pinned": False}, {"owner": "human", "pinned": True}]})
    assert not de.person_changed({"blocks": [{"owner": "machine", "pinned": False}]})
    assert not de.person_changed(None)


def test_scope_keys():
    assert de.scope_key(de.CHANNEL, "x", "story_published") == "channel:x"
    assert de.scope_key(de.KIND, "x", "story_published") == "kind:x:story_published"
    assert de.scope_key(de.PUBLICATION, "x", "story_published") == "publication"
    assert de.scope_key(de.THIS_ONE, "x", "story_published") is None
