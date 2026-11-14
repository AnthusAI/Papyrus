from __future__ import annotations

from .monitor_match import EntityMatcher, match_records
from .monitor_records import MonitorRecord


def node(name: str, *, kind: str = "concept", status: str = "accepted", aliases=(), **overrides) -> dict:
    key = f"{kind}--{name.lower().replace(' ', '-')}"
    return {"lineageId": f"semantic-node-{key}", "nodeKey": key, "nodeKind": kind, "displayName": name, "aliases": list(aliases), "status": status, **overrides}


def story(title: str, **details) -> MonitorRecord:
    return MonitorRecord("reference-1", "lineage-1", "hn", "https://example.org/1", title, "2026-10-14T09:00:00Z", dict(details))


def found(matcher: EntityMatcher, text: str) -> list[str]:
    return [row["displayName"] for row in matcher.find(text)]


def test_names_and_aliases_match_case_insensitively_on_word_boundaries():
    matcher = EntityMatcher([node("Voice Cloning"), node("OpenAI", aliases=["Open AI Inc"]), node("Rust")])
    assert found(matcher, "VOICE cloning, at last") == ["Voice Cloning"]
    assert found(matcher, "Open AI Inc shipped a thing") == ["OpenAI"]
    assert found(matcher, "Rusty nails and trustworthy voice-cloning") == ["Voice Cloning"]  # Rust is not inside Rusty or trustworthy
    assert found(matcher, "Why Rust?") == ["Rust"]


def test_only_accepted_current_entities_match_and_short_single_words_never_do():
    matcher = EntityMatcher([node("Quantum", status="generated"), node("Gardening", status="rejected"), node("Old", versionState="superseded"), node("Go"), node("Zig")])
    assert found(matcher, "Quantum Gardening Old Go Zig") == ["Zig"]


def test_a_name_of_several_words_needs_all_of_them_in_order():
    matcher = EntityMatcher([node("Some Lab")])
    assert found(matcher, "Lab Some") == [] and found(matcher, "Some other Lab") == []
    assert found(matcher, "From some  lab, with love") == ["Some Lab"]


def test_match_records_uses_title_and_summary_and_skips_hub_records_and_misses():
    hub = MonitorRecord("reference-2", "lineage-2", "huggingface", "https://huggingface.co/o/m", "Voice Cloning", "2026-10-14T09:00:00Z", {"modelId": "o/m"})
    matches = match_records([story("Nothing here"), hub], [node("Voice Cloning")])
    assert matches == {}
    with_summary = story("Nothing here", summary="about voice cloning")
    assert list(match_records([with_summary], [node("Voice Cloning")])) == ["reference-1"]
