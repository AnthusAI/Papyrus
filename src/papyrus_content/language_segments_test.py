import pytest

from papyrus_content.language_serving import checked_serving, url_safe_segment
from papyrus_content.projection.standard.editions import translate_path


def test_translate_path_maps_each_segment_and_keeps_the_rest():
    table = {"security": "privacidad-y-seguridad", "articles": "articulos"}
    assert translate_path("security/videos", table) == "privacidad-y-seguridad/videos"
    assert translate_path("articles", table) == "articulos"
    assert translate_path("wiki", table) == "wiki"


@pytest.mark.parametrize("text,ok", [("articulos", True), ("文章", True), ("seguridad-y-alineacion", True), ("a_b", True),
                                      ("Art", False), ("a/b", False), ("a b", False), ("", False), ("-a", False), ("a?b", False), ("a%20b", False), ("a.b", False)])
def test_url_safe_segment(text, ok):
    assert url_safe_segment(text) is ok


def test_decomposed_segment_is_refused():
    import unicodedata
    with pytest.raises(ValueError, match="URL-safe"):
        checked_serving({"primary": "en", "enabled": ["en", "es-419"], "segments": {"es-419": {"articles": unicodedata.normalize("NFD", "artículos")}}})


def test_segments_are_part_of_the_serving_digest():
    base = {"primary": "en", "enabled": ["en", "es-419"]}
    assert checked_serving(base).digest_input() != checked_serving({**base, "segments": {"es-419": {"articles": "articulos"}}}).digest_input()
