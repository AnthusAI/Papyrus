"""The evidence behind the checklist step ``illustration`` (features_backend/stories/story-illustration.feature has the end to end scenarios)."""

import pytest

from papyrus_content.story_illustration import alt_problem, DONE, NOT_APPLICABLE, NOT_DONE, UNKNOWN, cover_evidence, normalize_path

POLICY = {"requiredTypes": ["article"], "requireDark": False, "unreadable": False}


def inputs(front_matter=None, body="", media=("assets/a/cover.png",), item_type="article", **policy):
    return {"type": item_type, "frontMatter": front_matter or {}, "body": body, "mediaPaths": list(media), "policy": {**POLICY, **policy}}


STOCK = {"image": "/assets/a/cover.png", "coverImage": {"srcPath": "assets/a/cover.png", "pickedBy": "Ryan", "pickedAt": "2026-11-11"}}
STOCK_BODY = '::image{src="assets/a/cover.png" alt="A room" credit="Image: A. Photographer, CC BY 4.0"}'
FIGURE_BODY = '::image{\n  src="assets/a/cover.png"\n  credit="Drafted by AI. Approved by Sierra."\n}'


@pytest.mark.parametrize("raw,expected", [("/assets/a/b.png", "assets/a/b.png"), ("media/assets/a/b.png", "assets/a/b.png"), (None, ""), (" assets/a/b.png ", "assets/a/b.png")])
def test_paths_are_compared_as_stored(raw, expected):
    assert normalize_path(raw) == expected


def test_a_stock_cover_a_person_picked_is_proof():
    state, text = cover_evidence(inputs(STOCK, STOCK_BODY))
    assert state == DONE and "picked by Ryan" in text


def test_a_stock_cover_with_no_credit_line_is_not_done():
    state, text = cover_evidence(inputs(STOCK, BARE_BODY))
    assert state == NOT_DONE and "credit" in text


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
    assert cover_evidence(inputs(STOCK, STOCK_BODY, requireDark=True))[0] == DONE


def test_an_unreadable_dark_setting_is_unknown_for_a_light_only_figure_and_not_for_a_photograph():
    assert cover_evidence(inputs(GENERATED, BARE_BODY, unreadable=True))[0] == UNKNOWN
    assert cover_evidence(inputs(STOCK, STOCK_BODY, unreadable=True))[0] == DONE


def test_only_the_listed_types_and_stories_with_no_type_need_a_cover():
    assert cover_evidence(inputs(item_type="post"))[0] == NOT_APPLICABLE
    assert cover_evidence(inputs(item_type="post", requiredTypes=["post"]))[0] == NOT_DONE
    assert cover_evidence(inputs(item_type="untyped"))[0] == NOT_DONE
    assert cover_evidence(None)[0] == UNKNOWN


BRIEF = "A locked filing cabinet. No devils, horns, flames or pitchforks."


def with_media_alt(alt, brief=BRIEF, body=BARE_BODY):
    return {**inputs(GENERATED, body), "mediaAlts": {"assets/a/cover.png": {"alt": alt, "brief": brief}}}


def test_alt_text_copied_from_the_brief_is_not_a_description_of_the_picture():
    assert alt_problem("", BRIEF) and alt_problem("  ", BRIEF)
    assert alt_problem(BRIEF.upper(), BRIEF)
    assert alt_problem(f"Cover. {BRIEF} Wide.", BRIEF)
    assert alt_problem("A steel cabinet with a padlock in a grey room.", BRIEF) == ""


def test_a_cover_whose_directive_alt_is_the_brief_is_not_done():
    body = f'::image{{src="assets/a/cover.png" alt="{BRIEF}"}}'
    state, text = cover_evidence(with_media_alt("A steel cabinet.", body=body))
    assert state == NOT_DONE and "copied from the generation brief" in text


def test_a_cover_whose_media_record_alt_is_the_brief_or_empty_is_not_done():
    assert cover_evidence(with_media_alt(BRIEF))[0] == NOT_DONE
    no_directive_alt = '::image{src="assets/a/cover.png"}'
    assert cover_evidence(with_media_alt("", body=no_directive_alt))[0] == NOT_DONE
    assert cover_evidence(with_media_alt("A steel cabinet."))[0] == DONE
    assert cover_evidence(with_media_alt(""))[0] == DONE   # the directive's alt is what the page shows


def test_a_directive_with_an_empty_alt_is_not_done():
    assert cover_evidence(inputs({"image": "/assets/a/cover.png"}, '::image{src="assets/a/cover.png" alt=""}'))[0] == NOT_DONE
