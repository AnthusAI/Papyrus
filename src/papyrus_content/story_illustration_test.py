"""The evidence behind the checklist step ``illustration`` (features_backend/story-illustration.feature has the end to end scenarios)."""

import pytest

from papyrus_content.story_illustration import DONE, NOT_APPLICABLE, NOT_DONE, UNKNOWN, cover_evidence, normalize_path

POLICY = {"requiredTypes": ["article"], "requireDark": False, "unreadable": False}


def inputs(front_matter=None, body="", media=("assets/a/cover.png",), item_type="article", **policy):
    return {"type": item_type, "frontMatter": front_matter or {}, "body": body, "mediaPaths": list(media), "policy": {**POLICY, **policy}}


STOCK = {"image": "/assets/a/cover.png", "coverImage": {"srcPath": "assets/a/cover.png", "pickedBy": "Ryan", "pickedAt": "2026-11-11"}}
FIGURE_BODY = '::image{\n  src="assets/a/cover.png"\n  credit="Drafted by AI. Approved by Sierra."\n}'


@pytest.mark.parametrize("raw,expected", [("/assets/a/b.png", "assets/a/b.png"), ("media/assets/a/b.png", "assets/a/b.png"), (None, ""), (" assets/a/b.png ", "assets/a/b.png")])
def test_paths_are_compared_as_stored(raw, expected):
    assert normalize_path(raw) == expected


def test_a_stock_cover_a_person_picked_is_proof():
    state, text = cover_evidence(inputs(STOCK))
    assert state == DONE and "picked by Ryan" in text


def test_a_stock_cover_record_for_another_picture_names_nobody():
    front = {**STOCK, "image": "/assets/a/other.png"}
    state, text = cover_evidence(inputs(front, media=("assets/a/other.png",)))
    assert state == DONE and "Ryan" not in text


GENERATED = {"image": "/assets/a/cover.png", "coverImage": {"srcPath": "assets/a/cover.png", "approvedBy": "Sierra", "approvedAt": "2026-11-12"}}
BARE_BODY = '::image{src="assets/a/cover.png" alt="A room"}'


def test_a_generated_cover_with_no_approval_and_no_credit_is_proof_by_default():
    state, text = cover_evidence(inputs({"image": "/assets/a/cover.png"}, BARE_BODY))
    assert state == DONE and "approved" not in text


def test_an_approval_in_metadata_is_named_in_the_evidence_and_the_credit_line_is_never_read():
    state, text = cover_evidence(inputs(GENERATED, BARE_BODY))
    assert state == DONE and "approved by Sierra" in text
    assert cover_evidence(inputs({"image": "/assets/a/cover.png"}, FIGURE_BODY))[0] == DONE


def test_the_opt_in_requires_a_recorded_approval_and_the_line():
    optin = {"requireApprovalCredit": True}
    state, text = cover_evidence(inputs({"image": "/assets/a/cover.png"}, FIGURE_BODY, **optin))
    assert state == NOT_DONE and "approvedBy" in text
    state, text = cover_evidence(inputs(GENERATED, BARE_BODY, **optin))
    assert state == NOT_DONE and "Approved by Sierra" in text
    assert cover_evidence(inputs(GENERATED, FIGURE_BODY, **optin))[0] == DONE
    nameless = {**GENERATED, "coverImage": {"srcPath": "assets/a/cover.png", "approvedBy": " "}}
    assert cover_evidence(inputs(nameless, FIGURE_BODY, **optin))[0] == NOT_DONE


def test_a_third_party_cover_keeps_its_credit_and_needs_no_approval_line():
    body = '::image{src="assets/a/cover.png" credit="Image: A. Photographer, CC BY 4.0"}'
    assert cover_evidence(inputs(STOCK, body))[0] == DONE
    assert cover_evidence(inputs({"image": "/assets/a/cover.png"}, body))[0] == DONE


def test_the_cover_must_be_a_stored_asset_of_the_version():
    assert cover_evidence(inputs(STOCK, media=()))[0] == NOT_DONE
    assert cover_evidence(inputs({**STOCK, "image": "https://example.test/a.png"}))[0] == NOT_DONE
    assert cover_evidence(inputs({}))[0] == NOT_DONE


def test_the_dark_picture_is_required_only_for_a_figure_where_the_site_says_so():
    light_only = inputs({"image": "/assets/a/cover.png"}, BARE_BODY, requireDark=True)
    assert cover_evidence(light_only)[0] == NOT_DONE
    both = inputs({**GENERATED, "imageDark": "/assets/a/cover.dark.png"}, BARE_BODY, media=("assets/a/cover.png", "assets/a/cover.dark.png"), requireDark=True)
    assert cover_evidence(both)[0] == DONE
    dark_not_stored = inputs({**GENERATED, "imageDark": "/assets/a/cover.dark.png"}, BARE_BODY)
    assert cover_evidence(dark_not_stored)[0] == NOT_DONE   # a dark picture that is named must be stored, required or not
    assert cover_evidence(inputs(STOCK, requireDark=True))[0] == DONE


def test_an_unreadable_dark_setting_is_unknown_for_a_light_only_figure_and_not_for_a_photograph():
    assert cover_evidence(inputs(GENERATED, BARE_BODY, unreadable=True))[0] == UNKNOWN
    assert cover_evidence(inputs(STOCK, unreadable=True))[0] == DONE


def test_only_the_listed_types_and_stories_with_no_type_need_a_cover():
    assert cover_evidence(inputs(item_type="post"))[0] == NOT_APPLICABLE
    assert cover_evidence(inputs(item_type="post", requiredTypes=["post"]))[0] == NOT_DONE
    assert cover_evidence(inputs(item_type="untyped"))[0] == NOT_DONE
    assert cover_evidence(None)[0] == UNKNOWN
