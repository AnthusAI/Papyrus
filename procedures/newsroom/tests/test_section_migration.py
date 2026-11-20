"""Stored sections become section ids or nothing: the shared rules, the plan, the guard on applying it, and the writers that used to store a placeholder."""

from __future__ import annotations

import json

import pytest

from papyrus_content import section_migration
from papyrus_content.content_item_lifecycle import SYSTEM_ITEM_TYPES, build_new_content_item_version, is_story_item_type
from papyrus_content.copywriting import _draft_item_for_copywriting
from papyrus_content.ideas.context import sections_for
from papyrus_content.ideas.items import section_id_of
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.section_ids import is_type_shaped, match_section

SECTIONS = [
    {"id": "aws", "title": "AWS", "shortTitle": "Platform Exposure", "enabled": True},
    {"id": "wire", "title": "The Wire", "shortTitle": "Outside News", "enabled": True},
    {"id": "guides", "title": "Before You File", "shortTitle": "Guides", "enabled": True},
    {"id": "t#gaming", "title": "Gaming", "shortTitle": "Game AI", "enabled": True},
]


def row(slug, section, item_type="article", **extra):
    return {"id": f"item-{slug}", "sourceItemId": f"item-{slug}", "type": item_type, "slug": slug, "section": section, "status": "published", "versionState": "current", "sectionStatus": f"{section or ''}#published", **extra}


def settings_for(urls):
    return standard_settings_from_mapping({"site": {"name": "Example"}, "urls": {"style": "directory", **urls}})


# ------------------------------------------------------------------ the shared rules


@pytest.mark.parametrize(
    "value, kind, expected",
    [("articles", "article", True), ("Article", "article", True), ("unsectioned", "article", True), ("posts", "post", True), ("wiki", "wiki_page", True),
     ("aws", "article", False), ("platform", "article", False), ("", "article", False), (None, "article", False)],
)
def test_type_shaped_values(value, kind, expected):
    assert is_type_shaped(value, kind) is expected


def test_a_stored_value_means_the_section_the_editorial_checks_would_find():
    assert match_section(SECTIONS, "aws")["id"] == "aws"
    assert match_section(SECTIONS, "AWS")["id"] == "aws"
    assert match_section(SECTIONS, "the-wire")["id"] == "wire"            # slug of the title
    assert match_section(SECTIONS, "Before You File")["id"] == "guides"   # title
    assert match_section(SECTIONS, "gaming")["id"] == "t#gaming"          # the local part of a tenant-prefixed id
    assert match_section(SECTIONS, "Papyrus") is None
    with pytest.raises(ValueError, match="ambiguous"):
        match_section([{"id": "a", "title": "Same"}, {"id": "b", "title": "Same"}], "same")


def test_the_idea_pipeline_files_the_section_id_not_the_slug_of_its_title():
    class Client:
        def list_records(self, model):
            return SECTIONS

    assert section_id_of(Client(), "Before You File") == "guides"
    assert section_id_of(Client(), "AWS") == "aws"
    assert section_id_of(Client(), "Something New") == "something-new"   # a site without that section keeps the old behaviour
    assert section_id_of(Client(), "  ") is None


def test_the_ideas_context_does_not_offer_a_type_shaped_value_as_a_section():
    class Client:
        def list_records(self, model):
            return []

    stories = [{"section": "articles"}, {"section": "unsectioned"}, {"section": "agent-security"}, {"section": None}]
    assert sections_for(Client(), stories) == [{"id": "agent-security", "title": "agent-security"}]


def test_every_type_outside_the_system_set_is_a_story_type():
    assert SYSTEM_ITEM_TYPES == ("wiki_page", "doctrine", "page", "sub-task")
    assert all(is_story_item_type(name) for name in ("article", "post", "guide", "case_study", "untyped", "newsletter_issue"))
    assert not any(is_story_item_type(name) for name in (*SYSTEM_ITEM_TYPES, "", None))


def test_a_new_story_with_no_section_stores_no_section():
    version = build_new_content_item_version(lineage_id="content-item-x", title="A title", summary=None, section_key=None, stage="idea", actor_label="AI", now="2026-11-02T00:00:00Z")
    assert version["section"] is None and version["sectionStatus"] == "#draft"
    assert version["slug"].startswith("draft-unsectioned-")               # the draft slug keeps its shape; the section does not
    scoped = build_new_content_item_version(lineage_id="content-item-x", title="A title", summary=None, section_key="aws", stage="idea", actor_label="AI", now="2026-11-02T00:00:00Z")
    assert scoped["section"] == "aws" and scoped["sectionStatus"] == "aws#draft"


def test_a_copywriting_draft_of_a_story_with_no_section_stores_no_section():
    assignment = {"itemLineageId": "content-item-x", "title": "A title"}
    draft = _draft_item_for_copywriting(assignment=assignment, metadata={}, packet={"summary": "S", "recommendedAngle": "An angle"}, target_item_type="article", existing_items=[], actor_label="AI", now="2026-11-02T00:00:00Z")
    assert draft["section"] is None and draft["sectionStatus"] == "#draft" and draft["slug"].startswith("draft-unsectioned-")
    scoped = _draft_item_for_copywriting(assignment={**assignment, "sectionKey": "aws"}, metadata={}, packet={"summary": "S", "recommendedAngle": "An angle"}, target_item_type="article", existing_items=[], actor_label="AI", now="2026-11-02T00:00:00Z")
    assert scoped["section"] == "aws" and scoped["sectionStatus"] == "aws#draft"


# ------------------------------------------------------------------ the plan


def test_classification_keeps_maps_clears_and_asks():
    classify = section_migration.classify
    assert classify("aws", "article", SECTIONS)["action"] == "keep"
    assert classify("AWS", "article", SECTIONS) == {"action": "map", "to": "aws", "reason": "matches section 'aws' by title"}
    assert classify("articles", "article", SECTIONS)["action"] == "clear"
    assert classify("unsectioned", "article", SECTIONS)["action"] == "clear"
    assert classify("unsectioned", "brief", SECTIONS)["action"] == "clear"   # the placeholder is cleared whatever the type
    assert classify("platform", "page", SECTIONS)["action"] == "keep"        # a page's folder
    assert classify("wiki", "wiki_page", SECTIONS)["action"] == "keep"       # the wiki sync finds its pages by this section
    assert classify("Papyrus", "article", SECTIONS)["action"] == "decision"
    assert classify("gaming", "article", SECTIONS)["action"] == "decision"   # resolves to a tenant-prefixed id
    assert classify(None, "article", SECTIONS)["action"] == "keep"


def test_a_change_is_blocked_while_the_configuration_still_needs_the_old_value_and_safe_once_it_does_not():
    rows = [row("first", "articles"), row("second", "AWS"), row("third", "articles", versionState="superseded", status="draft")]
    old = settings_for({"sections": {"articles": {"base": "articles"}, "aws": {"base": "aws", "aliases": ["AWS"]}}})
    new = settings_for({"types": {"article": {"base": "articles"}}, "sections": {"aws": {"base": "aws", "aliases": ["AWS"]}}})
    blocked = section_migration.plan_for(site="x", items=rows, published=[], sections=SECTIONS, settings=old)
    assert not blocked["ok"] and blocked["blocked"] == 1
    assert [change["id"] for change in blocked["changes"] if change["safe"] is False] == ["item-first"]
    safe = section_migration.plan_for(site="x", items=rows, published=rows[:2], sections=SECTIONS, settings=new)
    assert safe["ok"] and safe["blocked"] == 0
    assert {(change["model"], change["id"], change["to"]) for change in safe["changes"]} == {
        ("Item", "item-first", None), ("Item", "item-second", "aws"), ("PublishedItem", "item-first", None), ("PublishedItem", "item-second", "aws")}
    assert safe["leftAsHistory"] == [{"type": "article", "section": "articles", "versions": 1}]   # superseded versions are history
    assert {entry["id"]: entry["to"] for entry in safe["published"]} == {"item-first": None, "item-second": "aws"}
    assert all(change["sectionStatusTo"] in ("#published", "aws#published") for change in safe["changes"])


def test_a_decision_changes_nothing_and_is_listed():
    plan = section_migration.plan_for(site="x", items=[row("odd", "Papyrus")], published=[], sections=SECTIONS)
    assert plan["changes"] == [] and [(entry["section"], entry["action"]) for entry in plan["decisions"]] == [("Papyrus", "decision")]
    assert "needs a decision (nothing changes): article/Papyrus x1" in section_migration.render(plan)


def test_a_row_that_gains_a_page_is_not_a_page_that_moved():
    settings = settings_for({"sections": {"wire": {"base": "wire"}}})
    plan = section_migration.plan_for(site="x", items=[row("draft-one", "the-wire", status="draft")], published=[], sections=SECTIONS, settings=settings)
    assert plan["ok"] and plan["changes"][0]["gainsPage"] is True


def test_the_plan_is_a_dry_run_and_applying_it_needs_a_checked_plan_with_nothing_blocked(tmp_path, capsys):
    scans = tmp_path / "scans"
    scans.mkdir()
    (scans / "x.Item.json").write_text(json.dumps([row("first", "articles")]))
    (scans / "x.PublishedItem.json").write_text(json.dumps([row("first", "articles")]))
    (scans / "x.NewsroomSection.json").write_text(json.dumps(SECTIONS))
    static = tmp_path / "web"
    static.mkdir()
    (static / "projection.json").write_text(json.dumps({"site": {"name": "X"}, "urls": {"style": "directory", "types": {"article": {"base": "articles"}}}}))
    out = tmp_path / "plan.json"
    assert section_migration.main(["plan", "--site", "x", "--scan-dir", str(scans), "--static", str(static), "--plan-out", str(out)]) == 0
    assert "dry run: nothing is written" in capsys.readouterr().out
    saved = json.loads(out.read_text())

    class Recorder:
        def __init__(self):
            self.updates = []

        def update_record(self, model, payload):
            self.updates.append((model, payload))

    client = Recorder()
    assert section_migration.apply_plan(saved, client) == 2
    assert client.updates[0] == ("Item", {"id": "item-first", "section": None, "sectionStatus": "#published"})
    with pytest.raises(SystemExit, match="blocked"):
        section_migration.apply_plan({**saved, "ok": False, "blocked": 1}, Recorder())
    with pytest.raises(SystemExit, match="not checked"):
        section_migration.apply_plan({**saved, "checkedAgainstConfiguration": False}, Recorder())
    assert section_migration.main(["apply", "--plan", str(out), "--confirm-site", "x"]) == 0   # without --yes it only says what it would do
    assert "pass --yes to write" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="not 'y'"):
        section_migration.main(["apply", "--plan", str(out), "--confirm-site", "y", "--yes"])
