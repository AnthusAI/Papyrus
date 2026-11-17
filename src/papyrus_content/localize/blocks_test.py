import pytest

from papyrus_content.localize.blocks import FRONT_MATTER_FIELDS, PlaceholderError, blocks_of, protect
from papyrus_content.localize.record import _front_matter, _source_fields


def test_the_front_matter_fields_are_blocks_after_the_dek():
    blocks = blocks_of("Body.\n", title="T", deck="D", fields=(("blurb", "B"), ("imageAlt", "A")))
    assert [b.kind for b in blocks] == ["title", "deck", "field:blurb", "field:imageAlt", "prose"]
    assert all(b.translated for b in blocks)


def test_a_story_without_the_fields_has_no_field_blocks():
    assert [b.kind for b in blocks_of("Body.\n", title="T", deck="D")] == ["title", "deck", "prose"]


def test_the_source_fields_are_read_from_the_front_matter_and_written_back_translated():
    import json

    row = {"metadata": json.dumps({"frontMatterYaml": "title: T\ndek: D\nblurb: B\nimageAlt: A\nimage: /a.png\nsources:\n- title: S\n  url: https://x.test\n"})}
    assert _source_fields(row) == (("blurb", "B"), ("imageAlt", "A")) and FRONT_MATTER_FIELDS == ("blurb", "imageAlt")
    out = _front_matter(row, "Tt", "Dd", {"blurb": "Bb", "imageAlt": "Aa"})
    assert "blurb: Bb" in out and "imageAlt: Aa" in out and "image: /a.png" in out and "title: S" in out


SOURCE = "This was [a case about who could see](/articles/the-more-a-security-product-watches/) the footage. [@ftc-ring]"


def test_a_link_comes_back_as_text_and_target_together():
    protected = protect(SOURCE)
    assert protected.text == "This was [a case about who could see]⟦1⟧ the footage. ⟦2⟧"
    assert protected.restore("这是[一宗关于谁能看到的案件]⟦1⟧录像。⟦2⟧") == "这是[一宗关于谁能看到的案件](/articles/the-more-a-security-product-watches/)录像。[@ftc-ring]"


@pytest.mark.parametrize("damaged, why", [
    ("这是⟦1⟧一宗关于谁能看到的案件录像。⟦2⟧", "directly after the closing"),
    ("这是[一宗案件](/articles/the-more-a-security-product-watches/)⟦1⟧录像。⟦2⟧", "directly after"),
    ("这是[一宗案件]⟦1⟧录像。(/articles/the-more-a-security-product-watches/)⟦2⟧", "directly after|yourself"),
    ("这是[一宗案件]⟦1⟧录像。[@ftc-ring] ⟦2⟧", "yourself"),
])
def test_a_translation_that_damages_a_link_is_refused_with_a_reason_the_model_can_act_on(damaged, why):
    with pytest.raises(PlaceholderError, match=why):
        protect(SOURCE).restore(damaged)


def test_what_a_model_is_told_about_a_problem_never_contains_a_link_target():
    protected = protect(SOURCE)
    told = protected.mask("The translation drops the link target “/articles/the-more-a-security-product-watches/” (source: '(/articles/the-more-a-security-product-watches/)')")
    assert "/articles/" not in told and told.count("⟦1⟧") == 2


def test_a_leaf_directive_with_a_blank_line_inside_its_attributes_is_one_block():
    from papyrus_content.localize.blocks import split_body

    directive = '::image{\n  src="a.png"\n \n  alt="A picture."\n  credit="Drafted by AI."\n}'
    assert split_body(f"Before.\n\n{directive}\n\nAfter.\n") == ["Before.", directive, "After."]
    assert [b.kind for b in blocks_of(f"Before.\n\n{directive}\n")] == ["prose", "directive"]


SOURCE_SOFT = ":::note\nOut of office.\nBack on Monday.\n:::"


def test_a_blank_line_where_the_source_has_a_soft_break_is_joined_again():
    from papyrus_content.localize.blocks import keep_soft_breaks

    assert keep_soft_breaks(SOURCE_SOFT, ":::note\nFuera.\n\nVuelve.\n:::") == ":::note\nFuera.\nVuelve.\n:::"
    assert keep_soft_breaks(SOURCE_SOFT, "\n:::note\nFuera.\n\n\nVuelve.\n:::\n") == "\n:::note\nFuera.\nVuelve.\n:::\n"


def test_a_source_without_a_soft_break_leaves_the_translation_alone():
    from papyrus_content.localize.blocks import keep_soft_breaks

    source = ":::note\nOut of office.\n\nBack on Monday.\n:::"
    assert keep_soft_breaks(source, ":::note\nFuera.\n\nVuelve.\n:::") == ":::note\nFuera.\n\nVuelve.\n:::"
    assert keep_soft_breaks("One.", "Uno.") == "Uno."


@pytest.mark.parametrize("target", [
    ":::note\nFuera.\n\nVuelve.\n\nInventado.\n:::",   # an extra paragraph: the lines do not line up
    ":::note\nFuera. Vuelve.\n:::",                    # merged
    "Fuera.\n\nVuelve.",                               # the container lines are gone: the kinds differ
])
def test_a_translation_whose_lines_do_not_line_up_is_never_guessed_at(target):
    from papyrus_content.localize.blocks import keep_soft_breaks

    assert keep_soft_breaks(SOURCE_SOFT, target) == target


def test_blank_lines_of_the_source_must_stay_blank_in_the_translation():
    from papyrus_content.localize.blocks import keep_soft_breaks

    source = "A\nB\n\nC\nD"
    broken = "A2\n\nB2\nC2\n\nD2"   # the same number of lines, broken elsewhere: which line to join is not certain
    assert keep_soft_breaks(source, broken) == broken
    assert keep_soft_breaks(source, "A2\n\nB2\n\nC2\n\nD2") == "A2\nB2\n\nC2\nD2"
