import json

from papyrus_content.story_change_kind import PICTURE_ONLY, TEXT_EDITED, TEXT_UNCHANGED, change_kind


def version(body="First paragraph.\n\n::image{src=\"/a.jpg\" alt=\"A dog\" credit=\"Ann\"}\n\nLast paragraph.", front="title: Board refuses\nimage: /cover.jpg", **fields):
    return {"title": "Board refuses", "bodyMarkus": body, "metadata": json.dumps({"frontMatterYaml": front}), **fields}


def test_the_same_words_and_pictures_are_text_unchanged_whatever_the_whitespace():
    assert change_kind(version(), version(body="First   paragraph.\n\n::image{src=\"/a.jpg\" alt=\"A dog\" credit=\"Ann\"}\n\nLast paragraph.\n")) == TEXT_UNCHANGED


def test_a_new_picture_credit_or_alt_text_is_picture_only():
    assert change_kind(version(), version(body="First paragraph.\n\n::image{src=\"/b.jpg\" alt=\"A cat\" credit=\"Bo\"}\n\nLast paragraph.")) == PICTURE_ONLY
    assert change_kind(version(), version(front="title: Board refuses\nimage: /other.jpg\nimageAlt: A new cover")) == PICTURE_ONLY


def test_a_changed_word_title_dek_or_blurb_is_text_edited():
    assert change_kind(version(), version(body="First paragraph, changed.\n\n::image{src=\"/a.jpg\" alt=\"A dog\" credit=\"Ann\"}\n\nLast paragraph.")) == TEXT_EDITED
    assert change_kind(version(), version(title="Board agrees")) == TEXT_EDITED
    assert change_kind(version(), version(front="title: Board refuses\nimage: /cover.jpg\ndek: A new dek")) == TEXT_EDITED
    assert change_kind(version(), version(front="title: Board refuses\nimage: /cover.jpg\nblurb: Now with a blurb")) == TEXT_EDITED


def test_a_first_version_is_new_text():
    assert change_kind(None, version()) == TEXT_EDITED
