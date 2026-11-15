"""Language variants of a translation's pictures: applied, carried through a re-translation, taken out, and the words advice."""
from __future__ import annotations

import yaml

from papyrus_content.localize.image_variants import ImageVariant, apply_variant, carry_forward, images_with_text, read_variants, remove_variant, revert_body

FM = "title: T\nimage: /assets/a/hz.png\nimageDark: /assets/a/hz.dark.png\nimageAlt: A\n"
BODY = 'Hi\n\n::image{src="assets/a/hz.png" srcDark="assets/a/hz.dark.png" layout="full" alt="x" caption="c"}\n\n::image{src="assets/a/other.png" alt="o"}\n'
VARIANT = ImageVariant("assets/a/hz.png", "assets/a--es/hz-es.png", "es", src_dark="assets/a--es/hz-es.dark.png")


def test_a_variant_repoints_the_figure_and_the_cover_and_is_recorded():
    front, body, places = apply_variant(FM, BODY, VARIANT, {"alt": 'Un "mapa"'})
    loaded = yaml.safe_load(front)
    assert places == 2 and loaded["image"] == "/assets/a--es/hz-es.png" and loaded["imageDark"] == "/assets/a--es/hz-es.dark.png"
    assert 'src="assets/a--es/hz-es.png" srcDark="assets/a--es/hz-es.dark.png" layout="full" alt=\'Un "mapa"\' caption="c"' in body
    assert 'src="assets/a/other.png"' in body
    assert loaded["imageVariants"] == [{"from": "assets/a/hz.png", "fromDark": "assets/a/hz.dark.png", "src": "assets/a--es/hz-es.png",
                                        "srcDark": "assets/a--es/hz-es.dark.png", "language": "es"}]


def test_a_variant_with_no_dark_picture_turns_the_dark_pairing_off():
    light_only = ImageVariant("assets/a/hz.png", "assets/a--es/hz-es.png", "es")
    front, body, _ = apply_variant(FM, BODY, light_only)
    assert 'srcDark="none"' in body and "imageDark" not in yaml.safe_load(front)


def test_nothing_changes_when_the_translation_shows_no_such_picture():
    assert apply_variant(FM, BODY, ImageVariant("assets/a/none.png", "x.png", "es")) == (FM, BODY, 0)


def test_a_retranslation_keeps_the_variant_and_reverting_gives_the_originals_text_back():
    front, body, _ = apply_variant(FM, BODY, VARIANT)
    assert revert_body(body, read_variants(front)).replace(" ", "") == BODY.replace(" ", "")
    fresh_front, fresh_body = carry_forward(FM, BODY, read_variants(front))
    assert (fresh_front, fresh_body) == (front, body) or (yaml.safe_load(fresh_front) == yaml.safe_load(front) and fresh_body == body)


def test_taking_a_variant_out_restores_the_original_and_drops_the_record():
    front, body, _ = apply_variant(FM, BODY, VARIANT)
    restored_front, restored_body = remove_variant(front, body, read_variants(front)[0])
    assert yaml.safe_load(restored_front) == yaml.safe_load(FM) and restored_body.count("assets/a/hz.png") == 1


def test_pictures_that_hold_words_are_reported_only_when_their_record_says_so():
    facts = {"assets/a/hz.png": {"embeddedText": True, "textLabels": 3}, "assets/a/other.png": {"embeddedText": False, "textLabels": 0}}
    assert images_with_text(BODY, FM, facts) == [{"src": "assets/a/hz.png", "where": "cover", "labels": 3, "localized": False}]
    assert images_with_text(BODY, FM, facts, [VARIANT])[0]["localized"] is True
    assert images_with_text(BODY, FM, {}) == []


def test_listings_read_the_translations_own_pictures_so_a_variant_needs_no_serving_change():
    """Cards, the social preview, the Markdown copy and the feeds read the translation's own front matter and body; the variant is just what they name."""
    from papyrus_content.projection.stored import projection_metadata

    front, body, _ = apply_variant("title: T\nimage: assets/a/hz.png\n", BODY, VARIANT)
    shown = projection_metadata(front, body)["frontMatter"]
    assert shown["image"] == "assets/a--es/hz-es.png" and shown["imageDark"] == "assets/a--es/hz-es.dark.png"
    original = projection_metadata("title: T\nimage: assets/a/hz.png\n", BODY)["frontMatter"]
    assert original["image"] == "assets/a/hz.png" and original["imageDark"] == "assets/a/hz.dark.png"
