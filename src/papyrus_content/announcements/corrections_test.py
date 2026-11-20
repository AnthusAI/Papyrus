"""The checks and the plan of ``papyrus announcements correct`` (PPY-3e0a8a). The command, its refusals and its result are specified in
features_backend/announcements/announcements-correct-cli.feature; these tests hold the parts that need no catalog beyond the fakes."""
import json

import pytest

from papyrus_content.announcements import corrections
from papyrus_content.announcements.deliveries import Deliveries, Plan
from papyrus_content.announcements.eligibility import StoryFacts
from papyrus_content.announcements.records import SENT
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles, RecordsBackend

NOW = "2026-11-17T09:00:00Z"
TITLE = "A look at how slow water shapes stone"


def facts():
    return StoryFacts(lineage_id="slow-water", item_id="slow-water-v3", version_number=3, story_type="article", section=None, published=True, retired=False, stars=4,
                      title=TITLE, dek="", summary="", body="", path="/slow-water", rated_by="ellie")


def supported(claim, cited, info=None):
    return {"verdict": "supported", "quotes": [" ".join(cited.values()).split("\n")[0]], "explanation": "", "attribution_lost": False, "claim_is_only_about_source_limits": False}


def unsupported(claim, cited, info=None):
    return {"verdict": "not_supported", "quotes": [], "explanation": "", "attribution_lost": False, "claim_is_only_about_source_limits": False}


def never():
    raise AssertionError("not needed for this channel")


def sent_delivery(channel="x", mode="automatic", approval="none"):
    backend = RecordsBackend()
    deliveries = Deliveries(backend, MemoryDeliveryFiles(backend))
    plan = Plan(channel=channel, account_id="handle-1", approval=approval, approval_policy="test", text="First words", mode=mode, audience=["list-1"] if channel == "email" else ())
    row = deliveries.create("announcement-1", plan, release_at=NOW, by="announce", now=NOW)
    return deliveries, deliveries.finish(row, SENT, by="worker", note="sent", now=NOW)


def test_an_x_post_passes_every_check_when_the_story_supports_it():
    old = {"channel": "x"}
    checks = corrections.check_words(old, "Slow water shapes stone", story=facts, site_origin=lambda: "https://machines.example", judge=lambda: supported)
    assert [check["name"] for check in checks if check["passed"]] == ["length", "markup", "facts"]


def test_every_problem_is_listed_when_the_checks_fail():
    with pytest.raises(corrections.ChecksFailed) as failed:
        corrections.check_words({"channel": "x"}, "Slow water shapes stone https://elsewhere.example/a", story=facts, site_origin=lambda: "https://machines.example", judge=lambda: unsupported)
    assert "has its own link" in str(failed.value) and "This claim is not in the Story" in str(failed.value)
    assert {check["name"] for check in failed.value.checks if not check["passed"]} == {"markup", "facts"}


def test_empty_words_fail_before_anything_is_looked_up():
    with pytest.raises(corrections.ChecksFailed, match="empty"):
        corrections.check_words({"channel": "x"}, "  ", story=never, site_origin=never, judge=never)


def test_another_channel_has_the_records_own_rule_and_needs_no_story_or_model():
    checks = corrections.check_words({"channel": "email"}, "Words for the list", story=never, site_origin=never, judge=never)
    assert checks == [{"name": "words", "passed": True, "problems": []}]


def test_a_correction_keeps_what_the_old_delivery_was():
    deliveries, old = sent_delivery(channel="email", mode="automatic", approval="soft")
    written = corrections.correct(deliveries, old, "  Corrected words  ", [{"name": "words", "passed": True, "problems": []}], by="ellie", drafted_by="ellie", now=NOW)
    assert (written["generation"], written["supersedes"], written["channel"], written["accountId"], written["mode"], written["approval"], written["approvalPolicy"]) == \
        (2, old["id"], "email", "handle-1", "automatic", "soft", "test")
    assert written["audience"] == ["list-1"] and written["draftedBy"] == "ellie" and json.loads(written["checks"]) == [{"name": "words", "passed": True}]
    assert deliveries.text(written) == "Corrected words"
    assert deliveries.get(old["id"])["supersededBy"] == written["id"]


def test_a_correction_of_a_delivery_that_never_went_writes_nothing():
    backend = RecordsBackend()
    deliveries = Deliveries(backend, MemoryDeliveryFiles(backend))
    row = deliveries.create("announcement-1", Plan(channel="x", account_id="handle-1", approval="none", approval_policy="test", text="First words"), release_at=NOW, by="announce", now=NOW)
    from papyrus_content.announcements.deliveries import NotSent

    with pytest.raises(NotSent, match="edited, not corrected"):
        corrections.correct(deliveries, row, "Corrected", [], by="ellie", drafted_by="ellie", now=NOW)
    assert len(backend.rows("Delivery")) == 1


def test_an_announcement_of_several_stories_cannot_have_its_post_checked():
    class Links:
        def list_by_index(self, *args, **kwargs):
            return [{"objectLineageId": "a", "predicate": "announces"}, {"objectLineageId": "b", "predicate": "announces"}]

    with pytest.raises(corrections.CannotCheck, match="2 Stories"):
        corrections.story_of(Links(), "announcement-1", item_url_style="html")
