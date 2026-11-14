"""Concepts an editor invented get a plain public address (``containment``), never one with their kind in it (``editor-concept-containment``).

The address is the page's key, so it is also the key in the knowledge snapshot. A page somebody else already has at the address is left alone and the sync
says so; an older page that has the kind in its address is reported, not moved.
"""

from __future__ import annotations

from papyrus_content.knowledge_wiki.sync import front_matter_of
from papyrus_content.publishing import ItemFields, item_id_for, save_item
from papyrus_content.wiki_stamp import WIKI_PAGE_ITEM_TYPE
from procedures.newsroom.tests.test_knowledge_wiki import (  # noqa: F401 - client is a fixture
    ACME_SLUG,
    NOW,
    SPOOL_SLUG,
    client,
    pages,
    sync,
)

CONCEPT_KINDS = ("--public-kinds", "maker,tool,editor_concept")


def add_concept(client, name="Containment", slug="containment", **extra):
    row = {
        "id": f"semantic-node-editor_concept--{slug}-v1", "lineageId": f"semantic-node-editor_concept--{slug}", "versionNumber": 1, "versionState": "current",
        "nodeKey": f"editor_concept--{slug}", "nodeKind": "editor_concept", "displayName": name, "status": "accepted", "aliases": [], **extra,
    }
    client.tables["SemanticNode"][row["id"]] = row
    return row


def test_a_concept_an_editor_invented_gets_a_plain_address_without_its_kind(client, capsys):
    add_concept(client)
    add_concept(client, "Confinement problem", "confinement-problem")
    out = sync(client, "--apply", *CONCEPT_KINDS, capsys=capsys)
    written = pages(client)
    assert "containment" in written and "confinement-problem" in written
    assert not [slug for slug in written if slug.startswith("editor-concept")]
    front = front_matter_of(written["containment"])
    assert (front["entityKey"], front["kind"], front["title"]) == ("containment", "editor-concept", "Containment")
    assert 'key="containment" part="trend"' in written["containment"]["bodyMarkus"]
    assert "create\tentity\twiki/containment" in out


def test_the_other_kinds_keep_their_kind_in_the_address(client):
    add_concept(client)
    sync(client, "--apply", *CONCEPT_KINDS)
    assert ACME_SLUG in pages(client) and SPOOL_SLUG in pages(client)


def test_a_page_somebody_else_already_has_at_the_address_is_left_alone_and_the_sync_says_so(client, capsys):
    add_concept(client)
    hand = ItemFields(
        type=WIKI_PAGE_ITEM_TYPE, slug="containment", section="wiki", front_matter_yaml="title: Containment, by hand\n",
        body_markus="Written by a person.\n", aliases=[], id=item_id_for("wiki", "containment"),
    )
    save_item(client, hand, actor="t", now=NOW)
    out = sync(client, "--apply", *CONCEPT_KINDS, capsys=capsys)
    page = pages(client)["containment"]
    assert page["bodyMarkus"] == "Written by a person.\n" and front_matter_of(page) == {"title": "Containment, by hand"}
    assert "wiki/containment: containment was not written because a page that is not containment's already has this address" in out
    assert "Move or rename one of the two pages" in out
    assert not [slug for slug in pages(client) if slug.startswith("editor-concept")]


def test_an_older_page_for_the_concept_with_the_kind_in_its_address_is_reported_not_moved(client, capsys):
    add_concept(client)
    old = ItemFields(
        type=WIKI_PAGE_ITEM_TYPE, slug="editor-concept-containment", section="wiki",
        front_matter_yaml="title: Containment\nentityKey: editor-concept--containment\nkind: editor_concept\n",
        body_markus="# Containment\n", aliases=[], id=item_id_for("wiki", "editor-concept-containment"),
    )
    save_item(client, old, actor="t", now=NOW)
    out = sync(client, "--apply", *CONCEPT_KINDS, capsys=capsys)
    assert {"containment", "editor-concept-containment"} <= set(pages(client))
    assert pages(client)["editor-concept-containment"]["bodyMarkus"] == "# Containment\n"
    assert "an older page for this concept sits at editor-concept-containment" in out
    assert "add its old address to the new page's aliases" in out


def test_a_description_a_person_accepted_is_used_and_one_nobody_accepted_is_not(client, capsys):
    from papyrus_content.knowledge_snapshot import commands as snapshot_commands

    add_concept(client, description="Keeping a capable system inside its limits.")
    out = sync(client, "--apply", *CONCEPT_KINDS, capsys=capsys)
    assert "containment: the description is a draft nobody has accepted" in out
    assert "Keeping a capable system" not in pages(client)["containment"]["bodyMarkus"]
    snapshot_commands.knowledge_entities_accept_description(["--key", "editor_concept--containment", "--actor", "human", "--actor-name", "Ada Reader"])
    out = sync(client, "--apply", *CONCEPT_KINDS, capsys=capsys)
    assert "draft nobody has accepted" not in out
    assert "Keeping a capable system inside its limits." in pages(client)["containment"]["bodyMarkus"]
