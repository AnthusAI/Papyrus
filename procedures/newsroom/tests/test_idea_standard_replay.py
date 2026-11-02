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
from test_idea_more_than_summary import LinkedClient, REASON, editor_accepted  # noqa: E402
from test_monitor_stories import PAGE, VERDICT_ADDS, StoryModel, is_point_check, world  # noqa: E402

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


class Writer(StoryModel):
    """Each Reference gets its own subject, so the ideas are not duplicates of one another; the story rests on the editors' reason, and the point check says it
    adds something unless the Reference is in ``restating``."""

    def __init__(self, restating=(), **kwargs) -> None:
        super().__init__(**kwargs)
        self.restating = set(restating)
        self.last_source = None

    def __call__(self, url, headers, payload):
        if is_point_check(payload):
            source = json.loads(payload["input"]).get("source") or {}
            self.verdict = RESTATES if any(f"example{number}.org" in source.get("url", "") for number in self.restating) else VERDICT_ADDS
        return super().__call__(url, headers, payload)


RESTATES = {"verdict": "restates", "claim": "", "repeats_itself": False, "exposes_process": False, "reason": "It repeats the page."}


def backend(count=4, reasoned=2):
    rows, base = world(count)
    for row in rows[:reasoned]:
        editor_accepted(row, REASON)
    return NoWritesClient(references=rows, relations=base.relations, incoming=base.incoming, sections=("Analysis", "Tools"))


def run(client, model=None, **options):
    return replay_site(client, site="example-site", corpus_key=None, transport=model or Writer(), max_cost_usd=options.pop("max_cost_usd", 5.0), fetch=lambda url: PAGE, now=NOW, **options)


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
    assert result["run"]["nothingToAdd"] == 2


def test_the_replay_runs_the_standard_once_and_reports_what_the_owner_asked_for():
    result = run(backend())
    one = result["run"]
    assert (one["candidates"], one["filed"], one["nothingToAdd"]) == (4, 2, 2) and one["minimumStandard"] == "more-than-summary"
    assert one["connectionsUsed"] == {"acceptReason": 2} and one["checkFailures"] == {} and one["pointChecks"] == 2 and one["pointCheckFailed"] == 0
    assert one["costUsd"] > 0 and result["costUsd"] == pytest.approx(one["costUsd"]) and "arms" not in result and "key" not in result


def test_the_replay_tries_every_reference_whatever_an_earlier_run_rejected():
    result = run(backend(4, 4), model=Writer(restating=[1, 2]))
    assert result["run"]["filed"] == 2 and result["run"]["pointCheckFailed"] == 2 and result["run"]["checkFailures"] == {"no_point_beyond_source": 2}
    assert "## Rejected" in result["sampleText"] and "point_check_failed (no_point_beyond_source)" in result["sampleText"]


def test_the_sample_shows_the_drafts_with_the_connections_and_the_point_checks_verdict():
    result = run(backend(), sample=20)
    assert result["sample"] == 2
    text = result["sampleText"]
    assert "What the newsroom had on this Reference" in text and REASON in text and "[ source | adds | filler ]" in text and "The point check said adds" in text
    assert "Version A" not in text and "key" not in result


def test_the_sample_is_the_same_for_the_same_seed_and_capped_at_the_number_asked_for():
    first, second = run(backend(8, 8), seed=1, sample=3), run(backend(8, 8), seed=1, sample=3)
    other = run(backend(8, 8), seed=2, sample=3)
    assert first["sampleText"] == second["sampleText"] and first["sample"] == 3 and first["sampleText"].count("[ source | adds | filler ]") > 0
    assert first["sampleText"] != other["sampleText"]
    assert run(backend(8, 8), sample=3)["sampleText"].count("\n## ") == 3


def test_a_cost_ceiling_bounds_the_real_cost():
    result = run(backend(8, 8), max_cost_usd=0.0017)
    assert result["costUsd"] <= 0.0017 and result["run"]["stoppedBy"] == "cost"
    assert result["run"]["modelCalls"] < 16


def test_no_ceiling_no_replay():
    with pytest.raises(ValueError):
        run(backend(), max_cost_usd=0)


def test_the_outputs_are_local_files(tmp_path):
    result = run(backend(4, 4), model=Writer(restating=[1]))
    paths = write_outputs(result, tmp_path / "out")
    summary = json.loads(paths["result"].read_text())
    assert "sampleText" not in summary and summary["run"]["filed"] == 3
    assert "Pair" not in paths["sample"].read_text() and "## Rejected" in paths["sample"].read_text()
    checks = json.loads(paths["pointChecks"].read_text())
    assert len(checks) == 4 and sorted(row["failures"] != [] for row in checks) == [False, False, False, True]
    assert set(path.name for path in (tmp_path / "out").iterdir()) == {"result.json", "sample.md", "point-checks.json"}


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
    monkeypatch.setattr(script.synthesis, "openai_transport", lambda key: seen.setdefault("key", key) and Writer())
    monkeypatch.setattr(standard_replay.monitor_stories, "fetch_source", lambda url: PAGE)
    assert script.main(["--site", "example-site", "--max-cost-usd", "1", "--output-dir", str(tmp_path / "out")]) == 0
    printed = capsys.readouterr()
    assert secret not in printed.out + printed.err and seen["key"] == secret and (tmp_path / "out" / "point-checks.json").exists() and not (tmp_path / "out" / "key.json").exists()
