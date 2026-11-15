from papyrus_content.localize.blocks import FRONT_MATTER_FIELDS, blocks_of
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
