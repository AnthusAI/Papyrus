"""The draft starter profiles under docs/examples/image-profiles: each stays valid under the profile validator and resolves for every image type it names."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from papyrus_content.images.handlers import Caller, execute
from papyrus_content.images.profile_fakes import FakeBackend
from papyrus_content.images.profile_handlers import with_client
from papyrus_content.images.visual_style import resolve_visual_style, validate_profile

FOLDER = Path(__file__).resolve().parents[3] / "docs" / "examples" / "image-profiles"
FILES = sorted(FOLDER.glob("*.json"))
MOM_TYPES = {"cover-diagram", "inline-diagram", "cover-photo", "cover-illustration", "inline-illustration", "social-card"}


def load(name: str) -> dict:
    return json.loads((FOLDER / name).read_text(encoding="utf-8"))


def test_the_three_drafts_exist():
    assert [path.name for path in FILES] == ["machines-on-machines.json", "shipped.json", "threat-intelligence.json"]


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_each_draft_is_labelled_and_its_profile_is_valid(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["DRAFT"].startswith("DRAFT for Ryan to correct") and "nothing has been saved" in document["DRAFT"]
    assert len(document["openQuestions"]) >= 3 and all(question[:2] in ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.") for question in document["openQuestions"])
    assert document["profile"]["imageReview"] == "after_the_fact"
    assert validate_profile(document["profile"]) == []
    assert list(document)[:2] == ["DRAFT", "openQuestions"], "the label and the open questions come first"


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_every_type_resolves_and_every_example_slot_names_a_real_type(path):
    profile = json.loads(path.read_text(encoding="utf-8"))["profile"]
    slots = json.loads(path.read_text(encoding="utf-8"))["exampleSlots"]
    types = profile["imageTypes"]
    assert {slot["imageType"] for slot in slots} <= set(types)
    for key, definition in types.items():
        operation = "figure" if definition.get("sources") == ["figure-system"] else "resolve"
        resolved = resolve_visual_style(profile, use=definition.get("use") or types[definition["extends"]]["use"], image_type=key, operation=operation)
        assert resolved["imageType"] == key
    assert all(definition.get("examples") == [] for definition in types.values()), "slots are listed beside the profile; no pictures are attached"


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_a_draft_holds_no_real_addresses_or_account_ids(path):
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text) and not re.search(r"\b\d{12}\b", text)


def test_machines_on_machines_has_the_six_starter_types_with_the_binding_rule():
    document = load("machines-on-machines.json")["profile"]
    assert set(document["imageTypes"]) == MOM_TYPES
    assert document["typePreference"] == {"cover": ["cover-diagram", "cover-photo", "cover-illustration"], "inline": None, "social": ["social-card"]}
    sources = {key: definition.get("sources") for key, definition in document["imageTypes"].items()}
    assert sources["cover-diagram"] == ["figure-system"] and sources["inline-diagram"] == ["figure-system"] and sources["cover-photo"] == ["stock"]
    assert sources["cover-illustration"] == ["stock", "generated"] and sources["inline-illustration"] == ["generated", "stock"]
    constraint = document["constraints"][0]
    assert constraint["appliesTo"] == {"origins": ["generated"]} and "photo" in constraint["prohibits"]["treatments"] and "photorealistic" in constraint["promptAvoid"]
    assert document["imageTypes"]["inline-illustration"]["extends"] == "cover-illustration"
    assert document["imageTypes"]["inline-diagram"]["display"] == {"where": "article body", "smallestWidthPx": 343, "thumbnail": False}


def test_the_machines_on_machines_ban_blocks_generating_a_photograph_but_not_stock():
    document = load("machines-on-machines.json")["profile"]
    illustration = resolve_visual_style(document, use="cover", image_type="cover-illustration", operation="generate")
    assert [item["id"] for item in illustration["constraints"]] == ["mom-no-photoreal-generated"]
    photo = resolve_visual_style(document, use="cover", image_type="cover-photo", operation="search")
    assert photo["effective"]["sources"] == ["stock"]


def test_the_machines_on_machines_draft_can_be_saved_by_an_admin_as_the_first_profile():
    document = load("machines-on-machines.json")["profile"]
    store = FakeBackend("machines-on-machines")
    handlers = with_client(store)
    refused = execute("image_profile_save", {"document": document, "reason": "First profile", "expectedCurrentVersionId": "none"}, Caller(kind="person", subject="Edie Editor"), handlers)
    assert not refused["ok"] and refused["error"]["code"] == "not_authorized" and store.writes == [], "the binding rule needs an admin who is a person"
    saved = execute("image_profile_save", {"document": document, "reason": "First profile", "expectedCurrentVersionId": "none"}, Caller(kind="person", subject="Ada Admin", is_admin=True), handlers)
    assert saved["ok"] and saved["result"]["versionNumber"] == 1
