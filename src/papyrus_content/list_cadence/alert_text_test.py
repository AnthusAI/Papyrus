"""The words of an every-item alert and the rule that carries a Story to a list. Placeholders only."""
from __future__ import annotations

from types import SimpleNamespace

from papyrus_content.list_cadence.alert_text import alert_body, alert_drafter, alert_facts, first_paragraph, rule_matches


def test_rule_matching_or_within_a_field_and_across_fields() -> None:
    match = lambda rule, **item: rule_matches(rule, **{"section": "rulings", "tags": ["breaking"], "item_type": "article", **item})  # noqa: E731
    assert match(None) and match({}) and match({"sections": []})
    assert match({"sections": ["rulings", "notes"]}) and not match({"sections": ["notes"]})
    assert match({"sections": ["Rulings"]}), "names compare without regard to case"
    assert match({"tags": ["breaking", "other"]}) and not match({"tags": ["other"]})
    assert match({"types": ["article"]}) and not match({"types": ["video"]})
    assert not match({"sections": ["rulings"], "tags": ["other"]}), "every field present must match"
    assert not match({"sections": ["rulings"]}, section=None)


def test_the_first_paragraph_skips_structure_and_clips_long_text() -> None:
    assert first_paragraph("# Title\n\nFirst real paragraph.\nOn two lines.\n\nSecond.") == "First real paragraph. On two lines."
    assert first_paragraph("> quote\n\n- list\n\n| a | b |\n") == ""
    assert first_paragraph("") == "" and first_paragraph(None) == ""
    clipped = first_paragraph(("Sentence number one is here. " * 40).strip())
    assert clipped.endswith(".") and len(clipped) <= 600
    assert first_paragraph("x" * 700) == ""


def test_the_body_is_the_title_link_the_dek_the_paragraph_and_a_read_it_link() -> None:
    body = alert_body("news.example.test", "A *big* ruling", "https://news.example.test/a", "What it means.", "The court decided today.")
    assert body.splitlines()[0] == "## [A \\*big\\* ruling](https://news.example.test/a)"
    assert "What it means." in body and "The court decided today." in body and "[Read it on news.example.test](https://news.example.test/a)" in body


def test_the_facts_are_read_back_from_the_words() -> None:
    body = alert_body("x.test", "A *big* ruling", "https://x.test/a", "What it means.", "")
    assert alert_facts({}, body) == {"title": "A *big* ruling", "url": "https://x.test/a", "summary": "What it means."}
    assert alert_facts({}, alert_body("x.test", "T", "https://x.test/t", "", "")) == {"title": "T", "url": "https://x.test/t"}


def test_the_drafter_links_the_story_on_the_sites_address_and_names_the_host() -> None:
    story = SimpleNamespace(title="Slow water", dek="A dek.", body="Prose here.\n\n- a list\n", path="/news/slow-water/")
    draft = alert_drafter(lambda lineage: story, lambda: "https://news.example.test/")
    text = draft([("stories", {})], [SimpleNamespace(story=SimpleNamespace(lineage_id="slow-water"))], ())
    assert text.startswith("## [Slow water](https://news.example.test/news/slow-water/)") and "Prose here." in text and "a list" not in text
    assert "[Read it on news.example.test]" in text
