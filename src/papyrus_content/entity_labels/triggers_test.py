from papyrus_content.entity_labels.fakes import FakeSite
from papyrus_content.entity_labels.keys import CURRENT, HELD, entity_key
from papyrus_content.entity_labels.store import LabelStore
from papyrus_content.entity_labels.triggers import name_concepts_for_story, needs_name


def _site():
    site = FakeSite(primary="en")
    node = site.add_node("pi", "topic--prompt-injection", "prompt injection")
    return site, node


def _label(site, node, language, state):
    LabelStore(site).create({"id": f"concept#pi#{language}", "entityKind": "concept", "entityId": "pi", "entityKey": entity_key("concept", "pi"), "language": language,
                             "role": "preferred", "text": "x", "nameKey": f"k#{language}", "sortKey": f"{language}#preferred#x", "syncState": state})


def test_a_story_in_another_language_names_the_concept_once():
    site, node = _site()
    asked = []
    run = lambda client, n, language, **kw: asked.append((n["nodeKey"], language)) or [{"language": language}]
    assert name_concepts_for_story(site, story_language="es-419", nodes=[node], localize=run) == [{"language": "es-419"}]
    assert asked == [("topic--prompt-injection", "es-419")]


def test_the_primary_language_and_a_missing_language_ask_for_nothing():
    site, node = _site()
    boom = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("asked"))
    assert name_concepts_for_story(site, story_language="en", nodes=[node], localize=boom) == []
    assert name_concepts_for_story(site, story_language=None, nodes=[node], localize=boom) == []


def test_a_current_or_held_label_is_not_asked_for_again_but_a_stale_one_is():
    site, node = _site()
    _label(site, node, "es-419", CURRENT)
    assert not needs_name(site, node, "es-419")
    site.tables["EntityLabel"]["concept#pi#es-419"]["syncState"] = HELD
    assert not needs_name(site, node, "es-419")
    site.tables["EntityLabel"]["concept#pi#es-419"]["syncState"] = "stale"
    assert needs_name(site, node, "es-419")
    assert needs_name(site, node, "zh-Hans")
