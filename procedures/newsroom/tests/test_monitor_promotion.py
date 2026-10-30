"""Promoting a monitor record (a delivered Hub model) to a draft item, and the weekly suggestions."""

from __future__ import annotations

import json
from datetime import date

import pytest
import yaml

from papyrus_content import cli as cli_module
from papyrus_content import references_commands
from papyrus_content.knowledge_snapshot.commands_test import hub_model
from papyrus_content.knowledge_snapshot.monitor_records import MonitorRecord, record_of
from papyrus_content.monitor_promotion import body, front_matter, promote_record, promoted_reference_ids, promotion_item_id, suggest, validate_section
from procedures.newsroom.tests.fake_client import FakeAuthoringClient

ACTOR = "papyrus-cli"


class Backend(FakeAuthoringClient):
    """The in-memory backend; a monitor record is read from its Reference alone."""


def delivered(model_id="org/tuned", created="2026-10-14T08:00:00Z", **overrides) -> Backend:
    client = Backend()
    holder = type("Holder", (), {"rows": {}})()
    hub_model(holder, model_id, created, bases=[("org/base", "finetune")], likes=40, downloads=1200, **overrides)
    for model, rows in holder.rows.items():
        for row_id, row in rows.items():
            client.tables.setdefault(model, {})[row_id] = row
    return client


def record_in(client: Backend) -> MonitorRecord:
    [row] = client.list_records("Reference")
    record, missing = record_of(row)
    assert not missing
    return record


def test_a_record_becomes_a_draft_article_with_its_source_link_facts_and_entities():
    client = delivered()
    record = record_in(client)
    outcome = promote_record(client, record, section="models", actor=ACTOR, now="2026-10-19T12:00:00Z")
    assert outcome == {"itemId": "item-models-org-tuned", "slug": "org-tuned", "section": "models", "created": True, "linked": ["lineage-org--tuned"]}
    item = client.get_record("Item", "item-models-org-tuned")
    assert (item["status"], item["type"], item["section"], item["title"]) == ("draft", "article", "models", "org/tuned")
    assert client.get_record("PublishedItem", "published-item-models-org-tuned") is None  # nothing is published
    front = yaml.safe_load(json.loads(item["metadata"])["frontMatterYaml"]) if isinstance(item["metadata"], str) else yaml.safe_load(item["metadata"]["frontMatterYaml"])
    assert front["sources"] == [{"title": "org/tuned", "url": "https://huggingface.co/org/tuned", "provenance": "from the Hugging Face Hub"}]
    assert front["monitorRecord"]["referenceId"] == "reference-org--tuned" and front["monitorRecord"]["released"] == "2026-10-14"
    assert front["monitorRecord"]["baseModels"] == [{"modelId": "org/base", "relation": "finetune"}]
    assert {"kind": "maker", "name": "org"} in front["entities"] and {"kind": "licence", "name": "apache-2.0"} in front["entities"]
    assert "date" not in front  # publishing stamps the date; the release date is a fact in monitorRecord
    assert "[org/tuned](https://huggingface.co/org/tuned)" in item["bodyMarkus"] and "draft stub" in item["bodyMarkus"]


def test_promoting_twice_never_overwrites_the_editors_text():
    client = delivered()
    record = record_in(client)
    promote_record(client, record, section="models", actor=ACTOR)
    client.update_record("Item", {"id": "item-models-org-tuned", "bodyMarkus": "The editor wrote this.\n"})
    again = promote_record(client, record, section="models", actor=ACTOR)
    assert again["created"] is False and client.get_record("Item", "item-models-org-tuned")["bodyMarkus"] == "The editor wrote this.\n"


@pytest.mark.parametrize("section", [None, True, "", "Models", "a b", "a--b"])
def test_a_section_is_a_lowercase_key(section):
    with pytest.raises(ValueError, match="--section"):
        validate_section(section)


def test_the_draft_text_is_valid_markus_and_names_its_base_models():
    record = record_in(delivered())
    assert "built on [org/base](https://huggingface.co/org/base) (finetune)" in body(record)
    assert front_matter(record)["deck"].startswith("org/tuned is a text-to-speech model by org, released 2026-10-14.")
    assert promotion_item_id(record, "models") == "item-models-org-tuned"


def run_cli(client, monkeypatch, *flags):
    monkeypatch.setattr(references_commands, "create_authoring_client", lambda *args, **kwargs: (client, {}))
    references_commands.references_promote(list(flags))


def test_the_command_takes_the_reference_id_first_and_a_dry_run_writes_nothing(monkeypatch, capsys):
    client = delivered()
    run_cli(client, monkeypatch, "reference-org--tuned", "--section", "models", "--dry-run")
    out = capsys.readouterr().out
    assert "references\tpromote\treference-org--tuned\torg/tuned\tmodels\titem-models-org-tuned\tdry run" in out
    assert client.get_record("Item", "item-models-org-tuned") is None

    run_cli(client, monkeypatch, "reference-org--tuned", "--section", "models")
    assert "item-models-org-tuned\tdraft\tmodels/org-tuned" in capsys.readouterr().out
    run_cli(client, monkeypatch, "--reference", "lineage-org--tuned", "--section", "models")
    assert "unchanged: already promoted" in capsys.readouterr().out
    assert client.get_record("Reference", "reference-org--tuned")["curationStatus"] == "pending"  # a person still judges the Reference


def test_the_command_needs_a_reference_a_section_and_a_hub_model(monkeypatch):
    client = delivered()
    with pytest.raises(ValueError, match="requires a reference id"):
        run_cli(client, monkeypatch, "--section", "models")
    with pytest.raises(ValueError, match="--section"):
        run_cli(client, monkeypatch, "reference-org--tuned")
    client.tables["Reference"]["reference-org--tuned"]["sourceUri"] = "https://example.test/post"
    with pytest.raises(ValueError, match="not a monitor record"):
        run_cli(client, monkeypatch, "reference-org--tuned", "--section", "models")
    with pytest.raises(ValueError, match="was not found"):
        run_cli(client, monkeypatch, "reference-nope", "--section", "models")


def test_the_papyrus_command_routes_references_promote(monkeypatch):
    seen = []
    monkeypatch.setattr(cli_module, "references_promote", lambda flags: seen.append(flags))
    cli_module.dispatch("references", "promote", ["reference-1", "--section", "models"])
    assert seen == [["reference-1", "--section", "models"]]


def record(name: str, created: str, likes: int, downloads: int = 0) -> MonitorRecord:
    return MonitorRecord(f"reference-{name}", f"lineage-{name}", "huggingface", f"https://huggingface.co/org/{name}", f"org/{name}", created, {"modelId": f"org/{name}", "likes": likes, "downloads": downloads})


def test_suggestions_are_the_recent_records_the_hub_shows_most_interest_in_without_the_promoted_ones():
    records = [
        record("quiet", "2026-10-15T00:00:00Z", 1),
        record("popular", "2026-10-14T00:00:00Z", 300),
        record("tie-b", "2026-10-13T00:00:00Z", 50, 10),
        record("tie-a", "2026-10-13T00:00:00Z", 50, 99),
        record("old", "2026-08-01T00:00:00Z", 9000),
        record("promoted", "2026-10-12T00:00:00Z", 500),
    ]
    picks = suggest(records, limit=3, as_of=date(2026, 10, 19), promoted={"reference-promoted"})
    assert [pick.model_id for pick in picks] == ["org/popular", "org/tie-a", "org/tie-b"]
    assert suggest(records, limit=0, as_of=date(2026, 10, 19)) == []


def test_a_record_an_item_already_carries_counts_as_promoted():
    client = delivered()
    record = record_in(client)
    assert promoted_reference_ids(client, [record]) == set()
    promote_record(client, record, section="models", actor=ACTOR)
    assert promoted_reference_ids(client, [record]) == {record.reference_id}
