"""Unit tests for the announcement review policy (PPY-97c0f2); the behaviour is specified in features_backend/announcement-review-*.feature."""
from papyrus_content import story_checklist as checklist
from papyrus_content.agent_policy.document import PolicyError
from papyrus_content.agent_policy.resolve import PolicyState
from papyrus_content.announcements import intake, review_policy
from papyrus_content.announcements.eligibility import StoryFacts
from papyrus_content.announcements.settings import validate
from papyrus_content.images.handlers import Caller


def story(stars, rated_by, lineage="s"):
    return StoryFacts(lineage_id=lineage, item_id=f"{lineage}-v1", version_number=1, story_type="article", section=None, published=True, retired=False, stars=stars,
                      title="t", dek="", summary="", body="", path="/s", rated_by=rated_by)


def state(entry, version=3):
    return PolicyState(version, {"schemaVersion": 1, "site": {}, "agents": {"announce": entry}})


class StepsClient:
    """Just the three calls the checklist makes to write and read one sub-task Item."""

    def __init__(self):
        self.rows = {}

    def create_record(self, model, record):
        self.rows[record["id"]] = record

    def update_record(self, model, record):
        self.rows[record["id"]].update(record)

    def list_by_index(self, index, partition, **_):
        assert index == checklist.INDEX
        return [row for row in self.rows.values() if row.get("parentLineageId") == partition]


def mark(client, lineage, key, state_, actor_kind, story_version):
    row = checklist._apply(checklist._new_row(lineage, key), state_, {"kind": actor_kind, "label": "Someone"}, "2026-11-16T10:00:00Z", note="read it", story_version=story_version)
    checklist._write(client, row)


def test_the_stamp_is_a_person_marking_the_review_step_done_on_the_current_version():
    client = StepsClient()
    mark(client, "slow-water", intake.REVIEW_STEP, "done", "person", 3)
    stamps = intake.ChecklistReviewStamps(client)
    assert stamps.reviewed("slow-water", 3)
    assert not stamps.reviewed("slow-water", 4), "a later version carries no stamp"
    assert not stamps.reviewed("another", 3)


def test_an_agent_or_an_open_step_is_no_stamp():
    client = StepsClient()
    mark(client, "by-agent", intake.REVIEW_STEP, "done", "agent", 3)
    mark(client, "still-open", intake.REVIEW_STEP, "open", "person", 3)
    mark(client, "other-step", "review_search", "done", "person", 3)
    stamps = intake.ChecklistReviewStamps(client)
    assert not (stamps.reviewed("by-agent", 3) or stamps.reviewed("still-open", 3) or stamps.reviewed("other-step", 3))


def test_the_rung_gives_the_approval_and_a_missing_entry_prepares_nothing():
    assert [review_policy.choose(state({"rung": rung}), channel="x", kind="k").approval for rung in ("prepare", "publish_soft", "publish_auto")] == ["hard", "soft", "none"]
    for rung in ("off", "observe", "propose", "draft"):
        assert not review_policy.choose(state({"rung": rung}), channel="x", kind="k").prepares
    assert not review_policy.choose(PolicyState(0, {"schemaVersion": 1, "site": {}, "agents": {}}), channel="x", kind="k").prepares


def test_a_paused_announce_agent_prepares_nothing_and_says_why():
    choice = review_policy.choose(state({"rung": "publish_soft", "paused": True, "pausedReason": "Checking the wording"}), channel="x", kind="k")
    assert not choice.prepares and "Checking the wording" in choice.reason


def test_an_override_names_where_the_value_came_from():
    entry = {"rung": "publish_soft", "overrides": [{"channel": "x", "rung": "publish_auto"}, {"kind": "roundup", "rung": "prepare"}]}
    assert review_policy.choose(state(entry), channel="x", kind="roundup").policy == "override: kind roundup (agent policy version 3)"
    assert review_policy.choose(state(entry), channel="x", kind="post").policy == "override: channel x (agent policy version 3)"
    assert review_policy.choose(state(entry), channel="y", kind="post").policy == "publication policy (agent policy version 3)"


def test_the_floors():
    assert intake.floor_refusal(story(0, "")).code == intake.BELOW_FLOOR
    assert intake.floor_refusal(story(2, "ellie")).code == intake.BELOW_FLOOR
    assert intake.floor_refusal(story(3, "agent:rating")) is None
    assert intake.floor_refusal(story(5, "ellie")) is None
    assert intake.floor_refusal(story(5, "agent:rating")).code == intake.MACHINE_FIVE
    assert intake.floor_refusal(story(5, "")).code == intake.MACHINE_FIVE


def test_the_review_settings_are_values_the_ticket_lists():
    assert review_policy.NEW_PUBLICATION == {"announce": {"rung": "publish_soft"}, "requireReviewedSource": False}
    assert review_policy.MACHINES_ON_MACHINES["announce"]["overrides"] == [{"kind": "roundup", "rung": "prepare"}]
    assert review_policy.MACHINES_ON_MACHINES["requireReviewedSource"] is True


def test_review_is_set_only_for_the_scopes_it_has():
    class Never:
        def set_rung(self, *args, **kwargs):
            raise AssertionError("must be refused first")

    for scope in ({"section": "briefs"}, {"storyType": "post"}):
        try:
            review_policy.set_review(Never(), "t", Caller(kind="person", is_admin=True), "hard", reason="why", scope=scope)
        except PolicyError as error:
            assert error.code == "invalid_input"
        else:
            raise AssertionError("a scope the announce review does not have was accepted")


def test_requiring_a_reviewed_source_is_off_unless_set_and_must_be_a_flag():
    settings = {"mode": "off", "rules": {"minStars": 5, "storyTypes": ["article"], "sections": []}, "prices": {"createPost": 1, "createPostWithUrl": 1, "deletePost": 1, "readPost": 1, "asOf": "2026-11-12"}}
    assert validate(settings, "connected")["rules"]["requireReviewedSource"] is False
    settings["rules"]["requireReviewedSource"] = True
    assert validate(settings, "connected")["rules"]["requireReviewedSource"] is True
    settings["rules"]["requireReviewedSource"] = "yes"
    try:
        validate(settings, "connected")
    except Exception as error:   # noqa: BLE001
        assert "on or off" in str(error)
    else:
        raise AssertionError("a word was accepted")


def test_post_spacing_is_empty_by_default_and_a_whole_number_of_minutes_for_a_named_account():
    from papyrus_content.announcements.settings import DEFAULT_SETTINGS, spacing_minutes, with_defaults

    assert DEFAULT_SETTINGS["spacing"] == {} and spacing_minutes(with_defaults(None), "x", "handle") is None
    base = {**DEFAULT_SETTINGS, "rules": {**DEFAULT_SETTINGS["rules"]}}
    kept = validate({**base, "spacing": {"x#handle": 30}}, "connected")
    assert spacing_minutes(kept, "x", "handle") == 30 and spacing_minutes(kept, "x", "other") is None
    for bad in ({"x#handle": 0}, {"x#handle": "30"}, {"x#handle": True}, {"handle": 30}, {"#handle": 30}, "30"):
        try:
            validate({**base, "spacing": bad}, "connected")
        except Exception as error:   # noqa: BLE001 - the plain sentence is the answer
            assert getattr(error, "code", "") == "spacing_invalid", error
        else:
            raise AssertionError(f"{bad!r} was accepted")
