"""The public wiki: sync accepted entities and beats into draft pages, publish with a review stamp, project the pages.

One test per scenario of PPY-5629f3 (sync), PPY-f927a1 (stamp), PPY-a227f5 (suggest an edit) and PPY-db2d69 (topic pages).
The clock never matters: dates are given.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

from papyrus_content.knowledge_snapshot import commands as snapshot_commands
from papyrus_content.knowledge_wiki import commands as wiki_commands
from papyrus_content.knowledge_wiki.sync import front_matter_of
from papyrus_content.projection.engine import ProjectionContext, project_all
from papyrus_content.projection.source import PublishedContentSource
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from papyrus_content.projection.writers import LocalDirectoryWriter
from papyrus_content.publishing import ItemFields, PublishError, published_item_id_for, publish_item, save_item
from papyrus_content.wiki_stamp import WIKI_PAGE_ITEM_TYPE
from procedures.newsroom.tests import knowledge_fixtures as data
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.standard_frontend_support import static_directory

NOW = "2026-10-19T12:00:00Z"
DAY = "2026-10-22"
ACME = "maker--acme-loom"
SPOOL = "tool--beta-spool"
ACME_SLUG = "maker-acme-loom"
SPOOL_SLUG = "tool-beta-spool"
SETTINGS = {
    "site": {"name": "Example", "productionUrl": "https://example.org", "description": "An example."},
    "urls": {"style": "directory", "sections": {"posts": {}, "wiki": {"label": "Wiki"}, "topics": {"label": "Topics"}}},
    "listings": {"types": ["article", "wiki_page"]},
    "forms": {
        "suggest-edit": {
            "title": "Suggest an edit",
            "endpoint": "https://forms.example.org/",
            "submitLabel": "Send suggestion",
            "fields": [
                {"name": "message", "label": "What should change?", "type": "textarea", "required": True},
                {"name": "email", "label": "Your email (optional)", "type": "email"},
            ],
        }
    },
    "wiki": {"suggestForm": "suggest-edit"},
    "components": {"itemPagesDependOn": ["posts"]},
}


class WikiClient(FakeAuthoringClient):
    def _relations_by(self, field, state):
        return copy.deepcopy([row for row in self.tables.get("SemanticRelation", {}).values() if row.get(field) == state])

    def list_semantic_relations_by_object_state(self, state):
        return self._relations_by("objectStateKey", state)

    def list_semantic_relations_by_subject_state(self, state):
        return self._relations_by("subjectStateKey", state)


def publish_article(client, slug, *, entities=(), tags=()):
    front = {"title": slug.title(), "date": "2026-10-12", "entities": [{"kind": kind, "name": name} for kind, name in entities], "tags": list(tags)}
    fields = ItemFields(
        type="article", slug=slug, section="posts", front_matter_yaml=yaml.safe_dump(front, sort_keys=False),
        body_markus=f"Body of {slug}.\n", aliases=[], id=f"item-posts-{slug}",
    )
    save_item(client, fields, actor="t", now=NOW)
    publish_item(client, fields.id, actor="t", now=NOW)


@pytest.fixture
def client(monkeypatch):
    fake = WikiClient()
    publish_article(fake, "alpha", entities=[("maker", "Acme Loom"), ("tool", "Beta Spool")], tags=["weaving"])
    publish_article(fake, "beta", entities=[("maker", "Acme Loom")], tags=["weaving"])
    publish_article(fake, "gamma", tags=["Looms"])
    for module in (snapshot_commands, wiki_commands):
        monkeypatch.setattr(module, "create_authoring_client", lambda *args, **kwargs: (fake, {}))
    snapshot_commands.knowledge_publish_run(["--apply"])
    return fake


def run(function, *flags):
    function(list(flags))


def describe(client, key, text, reviewed=True, actor="human"):
    if reviewed:
        run(snapshot_commands.knowledge_entities_describe, "--key", key, "--text", text, "--actor", actor, "--actor-name", "Ada Reader" if actor == "human" else "Wiki agent")
    else:
        next(row for row in client.tables["SemanticNode"].values() if row["nodeKey"] == key)["description"] = text


def pages(client, section="wiki"):
    return {row["slug"]: row for row in client.tables.get("Item", {}).values() if row.get("type") == WIKI_PAGE_ITEM_TYPE and row.get("section") == section}


def sync(client, *flags, capsys=None):
    run(wiki_commands.knowledge_wiki_sync, *flags)
    return capsys.readouterr().out if capsys else ""


def publish(client, *flags):
    run(wiki_commands.knowledge_wiki_publish, *flags, "--no-trigger", "--on", DAY)


# ------------------------------------------------------------------ PPY-5629f3: sync

def test_a_new_accepted_entity_gets_a_draft_page_that_is_not_public(client, capsys):
    describe(client, ACME, "Acme Loom makes small looms.")
    before = len(client.write_calls())
    out = sync(client, capsys=capsys)
    assert "mode\tdry-run" in out and "create\tentity\twiki/maker-acme-loom" in out and "pass --apply to write" in out
    assert len(client.write_calls()) == before and pages(client) == {}

    sync(client, "--apply")
    page = pages(client)[ACME_SLUG]
    assert (page["status"], page["type"], page["section"], page["versionState"]) == ("draft", "wiki_page", "wiki", "current")
    assert client.get_record("PublishedItem", published_item_id_for(page["lineageId"])) is None
    front = front_matter_of(page)
    assert front["entityKey"] == ACME and front["kind"] == "maker" and front["title"] == "Acme Loom"
    assert "review" not in front
    body = page["bodyMarkus"]
    assert body.startswith("# Acme Loom\n\nAcme Loom makes small looms.\n")
    for part in ("trend", "neighbourhood", "related"):
        assert f'::include{{kind="block" name="knowledge-entity" key="{ACME}" part="{part}"}}' in body


def test_the_page_front_matter_carries_aliases_beat_and_related_keys(client, capsys, tmp_path):
    node = next(row for row in client.tables["SemanticNode"].values() if row["nodeKey"] == ACME)
    node["aliases"] = ["Acme", "Loom Co"]
    spool = next(row for row in client.tables["SemanticNode"].values() if row["nodeKey"] == SPOOL)
    from papyrus_content.categories_steering import semantic_relation_record

    relation = semantic_relation_record(
        {
            "predicate": "built_on", "subjectKind": "semanticNode", "subjectId": node["id"], "subjectLineageId": node["lineageId"], "subjectVersionNumber": 1,
            "objectKind": "semanticNode", "objectId": spool["id"], "objectLineageId": spool["lineageId"], "objectVersionNumber": 1,
            "rank": 1, "classifierId": "t", "metadata": {"confirmed": True},
        }
    )
    row = relation["expected"]
    client.tables.setdefault("SemanticRelation", {})[row["id"]] = row
    config = tmp_path / "beats.json"
    config.write_text(json.dumps({"topics": {"weaving": {"label": "Weaving", "path": "/topics/weaving/"}}}), encoding="utf-8")
    sync(client, "--apply", "--beats-config", str(config))
    front = front_matter_of(pages(client)[ACME_SLUG])
    assert front["entityAliases"] == ["Acme", "Loom Co"] and front["beat"] == "weaving" and front["related"] == [SPOOL]
    assert front_matter_of(pages(client)[SPOOL_SLUG])["related"] == [ACME]


def test_an_entity_without_a_description_gets_a_factual_line_and_no_generated_prose(client):
    node = next(row for row in client.tables["SemanticNode"].values() if row["nodeKey"] == ACME)
    node["aliases"] = ["Acme"]
    sync(client, "--apply")
    page = pages(client)[ACME_SLUG]
    assert page["bodyMarkus"].startswith("# Acme Loom\n\nAcme Loom is listed here as a maker. Also known as: Acme.\n")
    assert "description" not in front_matter_of(page)


def test_a_draft_description_nobody_accepted_stays_out_of_the_page_and_is_reported(client, capsys):
    describe(client, ACME, "Generated and unreviewed text.", reviewed=False)
    out = sync(client, "--apply", capsys=capsys)
    page = pages(client)[ACME_SLUG]
    assert "Generated and unreviewed" not in page["bodyMarkus"] and "is listed here as a maker" in page["bodyMarkus"]
    assert "description" not in front_matter_of(page)
    assert "warning\tmaker--acme-loom: the description is a draft nobody has accepted" in out


def test_a_description_the_ai_editor_wrote_is_used_and_labelled_by_the_page_stamp(client):
    describe(client, ACME, "Written by the AI editor.", actor="ai")
    sync(client, "--apply")
    assert "Written by the AI editor." in pages(client)[ACME_SLUG]["bodyMarkus"]


def test_sync_never_publishes_and_a_second_run_changes_nothing(client, capsys):
    describe(client, ACME, "Acme Loom makes small looms.")
    sync(client, "--apply")
    assert client.tables.get("PublishedItem", {}).keys() == {published_item_id_for(f"item-posts-{slug}") for slug in ("alpha", "beta", "gamma")}
    assert {row["status"] for row in pages(client).values()} == {"draft"}
    before = len(client.write_calls())
    out = sync(client, "--apply", capsys=capsys)
    assert len(client.write_calls()) == before and "unchanged" not in out.split("plan")[0] and "entity:unchanged\t2" in out


def test_the_wiki_commands_take_the_operator_lane_and_say_which_backend(client, tmp_path, monkeypatch, capsys):
    outputs = tmp_path / "amplify_outputs.json"
    outputs.write_text('{"data": {"url": "https://example123.appsync-api.us-east-1.amazonaws.com/graphql"}}', encoding="utf-8")
    monkeypatch.delenv("PAPYRUS_GRAPHQL_AUTH", raising=False)
    monkeypatch.delenv("PAPYRUS_GRAPHQL_ENDPOINT", raising=False)
    run(wiki_commands.knowledge_wiki_sync, "--auth", "iam", "--amplify-outputs", str(outputs))
    assert "knowledge\tauth\tiam\texample123.appsync-api.us-east-1.amazonaws.com" in capsys.readouterr().err
    monkeypatch.delenv("PAPYRUS_GRAPHQL_AUTH")
    monkeypatch.delenv("PAPYRUS_GRAPHQL_ENDPOINT")


def test_a_generated_or_rejected_entity_gets_no_page_and_a_removed_one_is_reported(client, capsys):
    sync(client, "--apply")
    assert set(pages(client)) == {ACME_SLUG, SPOOL_SLUG}
    spool = next(row for row in client.tables["SemanticNode"].values() if row["nodeKey"] == SPOOL)
    spool["status"] = "rejected"
    out = sync(client, "--apply", capsys=capsys)
    assert "warning\twiki/tool-beta-spool: no longer generated" in out
    assert set(pages(client)) == {ACME_SLUG, SPOOL_SLUG}


def test_the_editors_pin_and_annotations_survive_a_sync_and_feed_the_trend_block(client):
    sync(client, "--apply")
    page = pages(client)[ACME_SLUG]
    front = front_matter_of(page)
    front.update({"pin": True, "annotations": [{"date": "2026-09-24", "label": "Launch"}]})
    save_item(
        client,
        ItemFields(type="wiki_page", slug=ACME_SLUG, section="wiki", front_matter_yaml=yaml.safe_dump(front, sort_keys=False), body_markus=page["bodyMarkus"], aliases=[], id=page["id"]),
        actor="t", now=NOW,
    )
    describe(client, ACME, "Acme Loom makes small looms.")
    sync(client, "--apply")
    refreshed = pages(client)[ACME_SLUG]
    assert front_matter_of(refreshed)["pin"] is True and front_matter_of(refreshed)["annotations"][0]["label"] == "Launch"
    assert 'part="trend" annotate="2026-09-24" annotateLabel="Launch"' in refreshed["bodyMarkus"]


def test_publish_stamps_the_page_and_puts_it_live(client):
    describe(client, ACME, "Acme Loom makes small looms.")
    sync(client, "--apply")
    publish(client, pages(client)[ACME_SLUG]["id"], "--actor", "ai", "--apply")
    live = client.get_record("PublishedItem", published_item_id_for(pages(client)[ACME_SLUG]["lineageId"]))
    assert live is not None and live["type"] == "wiki_page"
    front = front_matter_of(pages(client)[ACME_SLUG])
    assert front["review"] == {"actor": "ai", "name": None, "on": DAY} and front["updated"] == DAY
    assert pages(client)[ACME_SLUG]["status"] == "published" and pages(client)[SPOOL_SLUG]["status"] == "draft"


def test_a_changed_description_on_a_published_page_becomes_a_pending_revision(client, capsys):
    describe(client, ACME, "Acme Loom makes small looms.")
    sync(client, "--apply")
    publish(client, "--all-drafts", "--actor", "ai", "--apply")
    page = pages(client)[ACME_SLUG]
    live_before = copy.deepcopy(client.get_record("PublishedItem", published_item_id_for(page["lineageId"])))
    assert "small looms" in live_before["bodyMarkus"]

    describe(client, ACME, "Acme Loom makes large looms.")
    out = sync(client, "--apply", capsys=capsys)
    assert "revise\tentity\twiki/maker-acme-loom\tpending revision beside the live page" in out
    assert client.get_record("PublishedItem", published_item_id_for(page["lineageId"])) == live_before
    versions = sorted((row for row in client.tables["Item"].values() if row.get("lineageId") == page["lineageId"]), key=lambda row: row["versionNumber"])
    assert [(row["versionNumber"], row["status"], row["versionState"]) for row in versions] == [(1, "published", "superseded"), (2, "draft", "current")]
    assert "large looms" in versions[1]["bodyMarkus"] and "large looms" not in versions[0]["bodyMarkus"]
    assert "review" not in front_matter_of(versions[1])

    with pytest.raises(PublishError, match="review stamp"):
        publish_item(client, versions[1]["id"], actor="t", now=NOW)
    assert "small looms" in client.get_record("PublishedItem", published_item_id_for(page["lineageId"]))["bodyMarkus"]

    sync(client, "--apply")
    assert len([row for row in client.tables["Item"].values() if row.get("lineageId") == page["lineageId"]]) == 2
    publish(client, "--all-drafts", "--actor", "human", "--actor-name", "Ada Reader", "--apply")
    live = client.get_record("PublishedItem", published_item_id_for(page["lineageId"]))
    assert "large looms" in live["bodyMarkus"] and live["versionNumber"] == 2
    assert front_matter_of(next(row for row in client.tables["Item"].values() if row["id"] == versions[1]["id"]))["review"]["name"] == "Ada Reader"


# ------------------------------------------------------------------ PPY-f927a1: stamps

def test_publishing_refuses_a_wiki_page_without_a_review_stamp(client):
    fields = ItemFields(type="wiki_page", slug="loose", section="wiki", front_matter_yaml="title: Loose\n", body_markus="Text.\n", aliases=[], id="item-wiki-loose")
    save_item(client, fields, actor="t", now=NOW)
    with pytest.raises(PublishError) as raised:
        publish_item(client, "item-wiki-loose", actor="t", now=NOW)
    assert raised.value.code == "wiki-stamp" and "no review stamp" in raised.value.message
    assert client.get_record("PublishedItem", published_item_id_for("item-wiki-loose")) is None
    for bad in ("review: {actor: robot, name: null, on: 2026-10-22}\n", "review: {actor: human, name: a@b.example, on: 2026-10-22}\n", "review: {actor: ai, name: null, on: yesterday}\n"):
        save_item(client, ItemFields(type="wiki_page", slug="loose", section="wiki", front_matter_yaml="title: Loose\n" + bad, body_markus="Text.\n", aliases=[], id="item-wiki-loose"), actor="t", now=NOW)
        with pytest.raises(PublishError, match="wiki-stamp|review"):
            publish_item(client, "item-wiki-loose", actor="t", now=NOW)


def test_the_publish_command_needs_an_actor_and_never_publishes_on_a_dry_run(client, capsys):
    sync(client, "--apply")
    with pytest.raises(ValueError, match="--actor must be one of ai, human"):
        publish(client, "--all-drafts")
    publish(client, "--all-drafts", "--actor", "ai")
    assert "would publish" in capsys.readouterr().out
    assert all("PublishedItem" != call[1] or call[0] == "get" for call in client.calls[-5:]) and {row["status"] for row in pages(client).values()} == {"draft"}
    with pytest.raises(ValueError, match="one wiki page"):
        publish(client, "--actor", "ai")


def test_a_human_review_is_stamped_with_the_name_or_as_an_editor(client):
    sync(client, "--apply")
    publish(client, pages(client)[ACME_SLUG]["id"], "--actor", "human", "--actor-name", "Ada Reader", "--apply")
    publish(client, SPOOL_SLUG, "--actor", "human", "--apply")
    assert front_matter_of(pages(client)[ACME_SLUG])["review"] == {"actor": "human", "name": "Ada Reader", "on": DAY}
    assert front_matter_of(pages(client)[SPOOL_SLUG])["review"] == {"actor": "human", "name": None, "on": DAY}


# ------------------------------------------------------------------ projection

class WikiSite:
    def __init__(self, client, settings=None, snapshot=True):
        self.work = Path(tempfile.mkdtemp(prefix="wiki-site-"))
        self.static = static_directory(self.work, settings or SETTINGS)
        self.out = self.work / "out"
        if snapshot:
            entity = copy.deepcopy(data.ACME)
            entity.update({"key": ACME, "name": "Acme Loom", "href": f"/wiki/{ACME_SLUG}/"})
            index = copy.deepcopy(data.INDEX)
            index["entities"][0].update({"key": ACME, "name": "Acme Loom", "href": f"/wiki/{ACME_SLUG}/"})
            index["trending"] = [ACME]
            data.write(self.out / "_data" / "knowledge", index=index, entities=(entity,))
        projector = StandardMarkusProjector.from_static_directory(self.static, environ={"PAPYRUS_SITE_PUBLIC_URL": ""})
        self.context = ProjectionContext(source=PublishedContentSource(client), projector=projector, writer=LocalDirectoryWriter(self.out), keep_state=False)

    def project(self):
        report = project_all(self.context)
        assert report.ok, report.errors
        return self

    def text(self, key):
        return (self.out / key).read_text(encoding="utf-8")

    def keys(self):
        return {path.relative_to(self.out).as_posix() for path in self.out.rglob("*") if path.is_file()}

    def cleanup(self):
        shutil.rmtree(self.work, ignore_errors=True)


@pytest.fixture
def made_site(client):
    created = []

    def make(**kwargs):
        created.append(WikiSite(client, **kwargs))
        return created[-1]

    yield make
    for site in created:
        site.cleanup()


def main_of(html: str) -> str:
    return re.search(r"<main.*?</main>", html, re.S).group(0)


def test_a_published_page_appears_in_the_listing_sitemap_llms_and_markdown_twin(client, made_site):
    describe(client, ACME, "Acme Loom makes small looms.")
    sync(client, "--apply")
    site = made_site().project()
    assert f"wiki/{ACME_SLUG}/index.html" not in site.keys() and ACME_SLUG not in site.text("sitemap.xml")

    publish(client, "--all-drafts", "--actor", "ai", "--apply")
    site = made_site().project()
    assert f"wiki/{ACME_SLUG}/index.html" in site.keys() and f"wiki/{ACME_SLUG}/index.md" in site.keys()
    assert ACME_SLUG in site.text("wiki/index.html") and SPOOL_SLUG in site.text("wiki/index.html")
    assert f"/wiki/{ACME_SLUG}/" in site.text("sitemap.xml")
    assert f"/wiki/{ACME_SLUG}/index.md" in site.text("llms.txt")
    page = main_of(site.text(f"wiki/{ACME_SLUG}/index.html"))
    assert "Acme Loom makes small looms." in page and "papyrus-knowledge-entity-trend" in page and "papyrus-knowledge-neighbourhood" in page
    twin = site.text(f"wiki/{ACME_SLUG}/index.md")
    for part in ("trend", "neighbourhood", "related"):
        assert f'::include{{kind="block" name="knowledge-entity" key="{ACME}" part="{part}"}}' in twin
    assert "papyrus-knowledge" not in twin and "<svg" not in twin
    assert f"## Related coverage" in twin


def test_a_page_shows_draft_and_edited_by_ai_above_its_text(client, made_site):
    sync(client, "--apply")
    publish(client, "--all-drafts", "--actor", "ai", "--apply")
    site = made_site().project()
    page = main_of(site.text(f"wiki/{ACME_SLUG}/index.html"))
    assert "Draft, not yet reviewed. Edited by AI on 2026-10-22" in page and 'data-state="ai"' in page
    assert page.index("Edited by AI") < page.index("papyrus-knowledge-entity-trend") and "Reviewed by" not in page
    assert "> Draft, not yet reviewed. Edited by AI on 2026-10-22" in site.text(f"wiki/{ACME_SLUG}/index.md")
    assert "desk" not in site.text(f"wiki/{ACME_SLUG}/index.html").lower().replace("desktop", "")


def test_a_page_a_person_reviewed_shows_reviewed_by_with_the_date(client, made_site):
    sync(client, "--apply")
    publish(client, ACME_SLUG, "--actor", "human", "--actor-name", "Ada Reader", "--apply")
    publish(client, SPOOL_SLUG, "--actor", "human", "--apply")
    site = made_site().project()
    assert "Reviewed by Ada Reader on 2026-10-22" in site.text(f"wiki/{ACME_SLUG}/index.html") and 'data-state="human"' in site.text(f"wiki/{ACME_SLUG}/index.html")
    assert "Reviewed by an editor on 2026-10-22" in site.text(f"wiki/{SPOOL_SLUG}/index.html")


def test_a_published_page_without_a_valid_stamp_says_it_is_a_draft(client, made_site):
    sync(client, "--apply")
    page = pages(client)[ACME_SLUG]
    client.tables["PublishedItem"][published_item_id_for(page["lineageId"])] = {
        "id": published_item_id_for(page["lineageId"]), "sourceItemId": page["id"], "itemLineageId": page["lineageId"], "versionNumber": 1, "type": "wiki_page",
        "status": "published", "slug": page["slug"], "section": "wiki", "title": "Acme Loom", "bodyMarkus": page["bodyMarkus"], "bodyIr": page["bodyIr"],
        "aliases": [], "publishedAt": NOW, "metadata": page["metadata"],
    }
    site = made_site().project()
    assert "Draft, not yet reviewed" in site.text(f"wiki/{ACME_SLUG}/index.html") and 'data-state="draft"' in site.text(f"wiki/{ACME_SLUG}/index.html")


def test_a_superseded_page_shows_the_notice_and_links_the_replacement(client, made_site):
    sync(client, "--apply")
    page = pages(client)[ACME_SLUG]
    front = front_matter_of(page)
    front["superseded_by"] = f"/wiki/{SPOOL_SLUG}/"
    save_item(client, ItemFields(type="wiki_page", slug=ACME_SLUG, section="wiki", front_matter_yaml=yaml.safe_dump(front, sort_keys=False), body_markus=page["bodyMarkus"], aliases=[], id=page["id"]), actor="t", now=NOW)
    publish(client, "--all-drafts", "--actor", "ai", "--apply")
    site = made_site().project()
    html = main_of(site.text(f"wiki/{ACME_SLUG}/index.html"))
    assert "This page has been superseded" in html and f'<a href="/wiki/{SPOOL_SLUG}/">the replacement page</a>' in html
    assert f"Superseded: this page has been replaced. See /wiki/{SPOOL_SLUG}/" in site.text(f"wiki/{ACME_SLUG}/index.md")
    assert "superseded" not in main_of(site.text(f"wiki/{SPOOL_SLUG}/index.html"))
    with pytest.raises(PublishError):
        front["superseded_by"] = "wiki/relative"
        save_item(client, ItemFields(type="wiki_page", slug=ACME_SLUG, section="wiki", front_matter_yaml=yaml.safe_dump({**front, "review": {"actor": "ai", "name": None, "on": DAY}}, sort_keys=False), body_markus=page["bodyMarkus"], aliases=[], id=page["id"]), actor="t", now=NOW)
        publish_item(client, page["id"], actor="t", now=NOW)


# ------------------------------------------------------------------ PPY-a227f5: suggest an edit

def test_a_wiki_page_offers_a_suggest_an_edit_form_that_names_the_page_and_changes_nothing(client, made_site):
    sync(client, "--apply")
    publish(client, "--all-drafts", "--actor", "ai", "--apply")
    site = made_site().project()
    html = site.text(f"wiki/{ACME_SLUG}/index.html")
    footer = re.search(r'<footer class="papyrus-wiki-footer">.*?</footer>', html, re.S).group(0)
    assert "Updated <time datetime=\"2026-10-22\">2026-10-22</time>" in footer
    assert f'href="/_data/knowledge/entities/{ACME}.json"' in footer
    assert "Suggest an edit" in footer and 'data-papyrus-form="suggest-edit"' in footer
    assert 'data-endpoint="https://forms.example.org/?form=suggest-edit"' in footer and 'name="message"' in footer
    assert "papyrus-form-v1.js" in html
    script = (site.out / "_plugins" / "papyrus-form-v1.js").read_text(encoding="utf-8")
    assert "body.page = location.pathname" in script and "reset()" in script
    assert "innerHTML" not in script and "location.reload" not in script
    assert f"wiki/{ACME_SLUG}/index.html" in site.keys()
    before = site.text(f"wiki/{ACME_SLUG}/index.html")
    site.project()
    assert site.text(f"wiki/{ACME_SLUG}/index.html") == before


def test_the_data_link_is_only_offered_when_the_snapshot_has_the_entity(client, made_site):
    sync(client, "--apply")
    publish(client, "--all-drafts", "--actor", "ai", "--apply")
    site = made_site().project()
    assert "entities/tool--beta-spool.json" not in site.text(f"wiki/{SPOOL_SLUG}/index.html") and "Updated" in site.text(f"wiki/{SPOOL_SLUG}/index.html")
    bare = made_site(snapshot=False).project()
    assert "Data for this page" not in bare.text(f"wiki/{ACME_SLUG}/index.html")


def test_without_an_endpoint_the_form_says_it_is_not_open_and_cannot_be_submitted(client, made_site):
    settings = copy.deepcopy(SETTINGS)
    del settings["forms"]["suggest-edit"]["endpoint"]
    sync(client, "--apply")
    publish(client, "--all-drafts", "--actor", "ai", "--apply")
    html = made_site(settings=settings).project().text(f"wiki/{ACME_SLUG}/index.html")
    assert "markus-form-closed" in html and "<fieldset disabled>" in html and "data-papyrus-form" not in html


def test_a_site_without_a_suggest_form_still_shows_the_updated_date(client, made_site):
    settings = {key: value for key, value in SETTINGS.items() if key != "wiki"}
    sync(client, "--apply")
    publish(client, "--all-drafts", "--actor", "ai", "--apply")
    html = made_site(settings=settings).project().text(f"wiki/{ACME_SLUG}/index.html")
    assert "Updated <time" in html and "Suggest an edit" not in html


def test_the_suggest_form_must_exist():
    from papyrus_content.projection.standard.config import standard_settings_from_mapping

    with pytest.raises(ValueError, match="wiki.suggestForm names an unknown form"):
        standard_settings_from_mapping({**{key: value for key, value in SETTINGS.items() if key != "forms"}, "wiki": {"suggestForm": "nothing"}})


# ------------------------------------------------------------------ PPY-db2d69: topic pages

def beats_config(tmp_path, topics=None):
    config = tmp_path / "beats.json"
    config.write_text(json.dumps({"topics": topics or {"weaving": {"label": "Weaving", "path": "/topics/weaving/"}}}), encoding="utf-8")
    return str(config)


def test_an_accepted_beat_gets_a_draft_topic_page_that_lists_its_items_once_published(client, made_site, tmp_path, capsys):
    out = sync(client, "--beats-config", beats_config(tmp_path), capsys=capsys)
    assert "create\tbeat\ttopics/weaving" in out
    sync(client, "--apply", "--beats-config", beats_config(tmp_path), "--topic-sections", "posts")
    page = pages(client, "topics")["weaving"]
    assert page["status"] == "draft" and front_matter_of(page)["topicKey"] == "weaving" and front_matter_of(page)["topicKind"] == "beat"
    assert '::include{kind="listing" sections="posts" tags="weaving,Weaving" count="20"}' in page["bodyMarkus"] and "Subtopics" not in page["bodyMarkus"]
    assert client.get_record("PublishedItem", published_item_id_for(page["lineageId"])) is None

    publish(client, "--all-drafts", "--actor", "ai", "--apply")
    site = made_site().project()
    html = main_of(site.text("topics/weaving/index.html"))
    assert "Weaving" in html and "Edited by AI" in html
    assert "/posts/alpha/" in html and "/posts/beta/" in html and "/posts/gamma/" not in html
    assert "topics/weaving/" in site.text("sitemap.xml") and "topics/index.html" in site.keys()


def category(key, name, *, parent=None, description=None, status="accepted"):
    return {
        "id": f"category-{key}", "categorySetId": "set-1", "categoryKey": key, "displayName": name, "parentCategoryKey": parent, "description": description,
        "status": status, "versionState": "current",
    }


def seed_categories(client, children=2):
    rows = [category("weaving", "Weaving", description="Cloth made on looms.")]
    rows += [category(f"sub-{index}", f"Sub {index}", parent="weaving", description=f"About sub {index}.") for index in range(children)]
    rows.append(category("draft-sub", "Draft sub", parent="weaving", status="proposed"))
    client.tables["Category"] = {row["id"]: row for row in rows}
    for index in range(children):
        publish_article(client, f"sub-item-{index}", tags=[f"sub-{index}"])


def test_a_small_beat_shows_no_subtopic_list_and_gets_no_subtopic_pages(client, tmp_path):
    seed_categories(client)
    sync(client, "--apply", "--beats-category-set", "set-1")
    topics = pages(client, "topics")
    assert set(topics) == {"weaving"}
    assert "Cloth made on looms." in topics["weaving"]["bodyMarkus"] and "Subtopics" not in topics["weaving"]["bodyMarkus"]


def test_a_large_beat_lists_its_accepted_subtopics_and_each_gets_a_page(client, made_site):
    seed_categories(client)
    sync(client, "--apply", "--beats-category-set", "set-1", "--subtopic-min-items", "2", "--topic-sections", "posts")
    topics = pages(client, "topics")
    assert set(topics) == {"weaving", "weaving-sub-0", "weaving-sub-1"}
    body = topics["weaving"]["bodyMarkus"]
    assert "## Subtopics" in body and "- [Sub 0](/topics/weaving-sub-0/)" in body and "Draft sub" not in body
    front = front_matter_of(topics["weaving-sub-0"])
    assert (front["topicKind"], front["parentTopic"]) == ("subtopic", "weaving") and "About sub 0." in topics["weaving-sub-0"]["bodyMarkus"]
    publish(client, "--all-drafts", "--actor", "ai", "--apply")
    html = made_site().project().text("topics/weaving/index.html")
    assert 'href="/topics/weaving-sub-1/"' in html


def test_the_topic_sync_is_off_without_a_beat_source_and_can_be_turned_off(client, tmp_path):
    sync(client, "--apply")
    assert pages(client, "topics") == {}
    sync(client, "--apply", "--beats-config", beats_config(tmp_path), "--no-topics")
    assert pages(client, "topics") == {}


# ------------------------------------------------------------------ configuration and wiring

def test_a_listing_in_a_topic_page_needs_the_item_pages_to_depend_on_what_it_lists(client, made_site, tmp_path):
    sync(client, "--apply", "--beats-config", beats_config(tmp_path), "--topic-sections", "posts")
    publish(client, "--all-drafts", "--actor", "ai", "--apply")
    settings = {key: value for key, value in SETTINGS.items() if key != "components"}
    with pytest.raises(ValueError, match="itemPagesDependOn must name those sections"):
        made_site(settings=settings).project()


def test_the_wiki_settings_are_checked():
    from papyrus_content.projection.standard.config import standard_settings_from_mapping

    base = {key: value for key, value in SETTINGS.items() if key != "wiki"}
    assert standard_settings_from_mapping(base).wiki.types == ("wiki_page",)
    assert standard_settings_from_mapping({**base, "wiki": {"types": ["wiki_page", "page"], "dataLink": False}}).wiki.data_link is False
    with pytest.raises(ValueError, match="Unknown wiki settings"):
        standard_settings_from_mapping({**base, "wiki": {"colour": "red"}})


def test_the_operator_command_routes_wiki_sync_and_publish(monkeypatch):
    from papyrus import cli

    calls = []
    monkeypatch.setattr(cli, "_delegate_content", lambda group, command, flags: calls.append((group, command, flags)))
    assert cli._map_knowledge("wiki", ["sync", "--apply"]) == 0 and cli._map_knowledge("wiki", ["publish", "--all-drafts", "--actor", "ai"]) == 0
    assert calls == [("knowledge", "wiki-sync", ["--apply"]), ("knowledge", "wiki-publish", ["--all-drafts", "--actor", "ai"])]
    with pytest.raises(ValueError, match="sync or publish"):
        cli._map_knowledge("wiki", [])
    from papyrus_content.cli import is_ported_command

    assert is_ported_command("knowledge", "wiki-sync") and is_ported_command("knowledge", "wiki-publish")


def test_markus_accepts_the_include_directive_so_a_page_can_be_saved(client):
    from papyrus_content.markus_renderer.derive import derive_body

    assert derive_body("title: x\n", '# X\n\n::include{kind="listing" tags="a" count="3"}\n').ok


def test_only_a_wiki_page_may_list_other_pages_from_inside_an_item(client, made_site, tmp_path):
    publish_article(client, "sneaky", tags=["weaving"])
    sneaky = ItemFields(
        type="article", slug="sneaky2", section="posts", front_matter_yaml="title: Sneaky\n",
        body_markus='# Sneaky\n\n::include{kind="listing" tags="weaving"}\n', aliases=[], id="item-posts-sneaky2",
    )
    save_item(client, sneaky, actor="t", now=NOW)
    publish_item(client, sneaky.id, actor="t", now=NOW)
    with pytest.raises(ValueError, match="::include is not available here"):
        made_site().project()
