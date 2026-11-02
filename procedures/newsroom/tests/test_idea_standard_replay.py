"""The replay of the idea minimum standard (scripts/replay_idea_standard.py, ideas/standard_replay.py): read only, a cost ceiling, a blind sample and a key."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ideas_fixtures import NOW  # noqa: E402
from papyrus_content.ideas import standard_replay  # noqa: E402
from papyrus_content.ideas.standard_replay import ReadOnlyClient, ReplayWriteRefused, replay_site, write_outputs  # noqa: E402
from test_idea_more_than_summary import LinkedClient, REASON, editor_accepted, story  # noqa: E402
from test_monitor_stories import PAGE, SUBJECTS, StoryModel, good_story, world  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


class NoWritesClient(LinkedClient):
    """A backend that fails the test on anything that could change it."""

    def create_record(self, *args, **kwargs):
        raise AssertionError("the replay created a record")

    update_record = upsert = delete_record = create_record

    def graphql(self, query, variables=None):
        if not query.lstrip().startswith("query") and "listStoryDrafts" not in query:
            raise AssertionError(f"the replay sent a mutation: {query[:60]}")
        return super().graphql(query, variables)


class TwoWays(StoryModel):
    """A summary when it is shown nothing the newsroom knows; a story resting on the editors' reason when it is. Each Reference gets its own subject, so the
    ideas are not duplicates of one another."""

    def __call__(self, url, headers, payload):
        self.requests.append(payload)
        model_input = json.loads(payload["input"])
        number = int(re.search(r"example(\d+)\.org", model_input["source"]["url"]).group(1))
        name, thing, place = SUBJECTS[(number - 1) % len(SUBJECTS)]
        if "what_the_newsroom_knows" in model_input:
            answer = story(
                headline=(f"{name} checks {thing} against {place}", "I1"), dek=(f"Editors accepted {name} because checking {thing} bears on sourcing coverage.", "E1"),
                body=[(f"{name} is an open tool that checks {thing} against their {place}.", "I1"), (f"The editors accepted {name} because claim checking matters to their sourcing coverage.", "I1", "E1")])
        else:
            answer = good_story(model_input["source"]["url"], number=number)
        return {"status": "completed", "output_text": json.dumps(answer), "usage": self.usage}


def backend(count=4, reasoned=2):
    rows, base = world(count)
    for row in rows[:reasoned]:
        editor_accepted(row, REASON)
    return NoWritesClient(references=rows, relations=base.relations, incoming=base.incoming, sections=("Analysis", "Tools"))


def run(client, model=None, **options):
    return replay_site(client, site="example-site", corpus_key=None, transport=model or TwoWays(), max_cost_usd=options.pop("max_cost_usd", 5.0), fetch=lambda url: PAGE, now=NOW, **options)


def test_the_read_only_client_passes_reads_and_refuses_everything_else():
    client = backend()
    readonly = ReadOnlyClient(client)
    assert readonly.list_records("NewsroomSection") is not None and readonly.get_record("ReviewRequest", "x") is None
    for name in ("create_record", "update_record", "upsert", "delete_record", "put_item", "anything_else"):
        with pytest.raises(ReplayWriteRefused):
            getattr(readonly, name)
    with pytest.raises(ReplayWriteRefused):
        readonly.graphql("mutation Make { createReviewRequest(input: {}) { id } }")
    with pytest.raises(ReplayWriteRefused):
        readonly.something = 1
    assert readonly.graphql("query ListItems { listItems { items { id } } }") is not None


def test_the_replay_writes_nothing_to_the_backend_and_raises_no_flag():
    client = backend()
    result = run(client)   # NoWritesClient fails the test on any change, even one the read-only wrapper missed
    assert client.reviews == {} and client.filed == []
    assert result["arms"]["more-than-summary"]["nothingToAdd"] == 2


def test_both_arms_see_the_same_references_and_report_what_the_owner_asked_for():
    result = run(backend())
    old, new = result["arms"]["summary"], result["arms"]["more-than-summary"]
    assert (old["candidates"], new["candidates"]) == (4, 4) and old["filed"] == 4 and new["filed"] == 2
    assert old["nothingToAdd"] == 0 and new["nothingToAdd"] == 2
    assert new["connectionsUsed"] == {"acceptReason": 2} and old["connectionsUsed"] == {"none": 4}
    assert old["checkFailures"] == {} and new["checkFailures"] == {}
    assert old["costUsd"] > 0 and new["costUsd"] > 0 and result["costUsd"] == pytest.approx(old["costUsd"] + new["costUsd"])


def test_the_sample_pairs_the_same_reference_blind_and_the_key_says_which_was_which():
    result = run(backend(), pairs=20)
    assert result["pairs"] == 2   # only the two References both arms wrote
    sample, key = result["sample"], result["key"]
    assert "Version A" in sample and "Version B" in sample and "more-than-summary" not in sample and "summary" not in sample.split("Pair 1")[1].lower().replace("summarises", "")
    assert "What the newsroom had on this Reference" in sample and REASON in sample and "[ source | adds | filler ]" in sample
    for entry in key.values():
        assert {entry["A"], entry["B"]} == {"summary", "more-than-summary"}
    assert len({entry["A"] for entry in key.values()} | {"x"}) >= 1


def test_the_order_of_each_pair_is_random_but_the_same_for_the_same_seed():
    first, second = run(backend(8, 8), seed=1), run(backend(8, 8), seed=1)
    other = run(backend(8, 8), seed=2)
    assert first["key"] == second["key"] and first["sample"] == second["sample"]
    assert {entry["A"] for entry in first["key"].values()} == {"summary", "more-than-summary"}   # not always the same arm first
    assert first["key"] != other["key"]


def test_pairs_are_capped_at_the_number_asked_for():
    assert run(backend(8, 8), pairs=3)["pairs"] == 3


def test_a_cost_ceiling_bounds_the_real_cost_of_both_arms_together():
    result = run(backend(8, 8), max_cost_usd=0.0017)
    assert result["costUsd"] <= 0.0017 and result["arms"]["summary"]["stoppedBy"] == "cost"
    assert result["arms"]["summary"]["modelCalls"] < 8


def test_no_ceiling_no_replay():
    with pytest.raises(ValueError):
        run(backend(), max_cost_usd=0)


def test_the_outputs_are_local_files_and_the_sample_is_apart_from_the_key(tmp_path):
    result = run(backend())
    paths = write_outputs(result, tmp_path / "out")
    assert json.loads(paths["key"].read_text()) == result["key"]
    summary = json.loads(paths["result"].read_text())
    assert "sample" not in summary and "key" not in summary and summary["arms"]["summary"]["filed"] == 4
    text = paths["sample"].read_text()
    assert "more-than-summary" not in text and "Version A" in text and all(entry["A"] in ("summary", "more-than-summary") for entry in json.loads(paths["key"].read_text()).values())


def test_the_command_needs_a_ceiling_and_a_key_and_never_prints_the_key(monkeypatch, capsys, tmp_path):
    spec = importlib.util.spec_from_file_location("replay_idea_standard", ROOT / "scripts" / "replay_idea_standard.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    with pytest.raises(SystemExit):
        script.main(["--site", "example-site"])   # --max-cost-usd is required
    monkeypatch.setattr(script, "resolve_openai_api_key", lambda: None)
    assert script.main(["--site", "example-site", "--max-cost-usd", "1"]) == 2
    secret = "sk-test-secret-value"
    monkeypatch.setattr(script, "resolve_openai_api_key", lambda: secret)
    monkeypatch.setattr(script, "create_authoring_client", lambda: (backend(), {}))
    seen = {}
    monkeypatch.setattr(script.synthesis, "openai_transport", lambda key: seen.setdefault("key", key) and TwoWays())
    monkeypatch.setattr(standard_replay.monitor_stories, "fetch_source", lambda url: PAGE)
    assert script.main(["--site", "example-site", "--max-cost-usd", "1", "--output-dir", str(tmp_path / "out")]) == 0
    printed = capsys.readouterr()
    assert secret not in printed.out + printed.err and seen["key"] == secret and (tmp_path / "out" / "key.json").exists()
