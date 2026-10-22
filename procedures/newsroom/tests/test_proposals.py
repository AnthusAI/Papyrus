"""Proposals: filing, the transitions, who may act, and the public files the reader snapshot writes."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.projection.plugins import is_plugin_runtime_key  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.reader_steering import proposals as public  # noqa: E402
from reader_fixtures import ReaderBackend, reader_handler, run_snapshot, subject_for  # noqa: E402

rules = reader_handler.proposal_rules
BODY = "# Name the agents cluster\n\nThe cluster mixes **tool use** with *planning*.\n"


def file_one(backend: ReaderBackend, **overrides) -> str:
    arguments = {"kind": "story_draft", "title": "Agents are eating the board", "body": BODY, **overrides}
    answer = backend.proposal_call("fileProposal", arguments)
    assert answer["status"] == "ok", answer
    return answer["id"]


def move(backend: ReaderBackend, proposal: str, state: str, **extra) -> dict:
    return backend.proposal_call("transitionProposal", {"proposalId": proposal, "state": state, **extra})


def row_of(backend: ReaderBackend, proposal: str) -> dict:
    return backend.table("proposal").get_item(Key={"id": proposal})["Item"]


def decide(backend: ReaderBackend, proposal: str, final: str = "approved", **extra) -> None:
    assert move(backend, proposal, "in_steering")["status"] == "ok"
    assert move(backend, proposal, "editor_review")["status"] == "ok"
    assert move(backend, proposal, final, **extra)["status"] == "ok"


class FilingTests(unittest.TestCase):
    def test_a_filed_proposal_is_a_draft_proposed_by_ai(self) -> None:
        with ReaderBackend() as backend:
            identifier = file_one(backend, summary="One line.", targets=json.dumps([{"type": "concept", "id": "agents"}]), evidence=json.dumps({"signals": 12, "source": "arXiv"}))
            row = row_of(backend, identifier)
            self.assertRegex(identifier, r"prop-[0-9a-f]{32}")
            self.assertEqual((row["state"], row["proposer"], row["kind"]), ("draft", "ai", "story_draft"))
            history = json.loads(row["history"])
            self.assertEqual([(entry["from"], entry["to"], entry["by"]) for entry in history], [(None, "draft", "ai")])
            self.assertEqual(history[0]["actor"], "staff-sub-1")

    def test_every_kind_is_accepted_with_the_targets_it_needs(self) -> None:
        targets = {
            "story_draft": [],
            "new_concept": [],
            "rename": [{"type": "concept", "id": "a"}],
            "merge": [{"type": "concept", "id": "a"}, {"type": "concept", "id": "b"}],
            "split": [{"type": "cluster", "id": "a"}],
            "new_column": [],
            "element_symbol": [{"type": "entity", "id": "openai"}],
        }
        self.assertEqual(set(targets), set(rules.KINDS))
        with ReaderBackend() as backend:
            for kind, wanted in targets.items():
                with self.subTest(kind=kind):
                    self.assertEqual(backend.proposal_call("fileProposal", {"kind": kind, "title": kind, "body": BODY, "targets": json.dumps(wanted)})["status"], "ok")

    def test_bad_filings_are_refused_and_write_nothing(self) -> None:
        cases = [
            ({"kind": "poem"}, "invalid_kind"),
            ({"title": "  "}, "invalid_title"),
            ({"title": "x" * 201}, "invalid_title"),
            ({"body": ""}, "invalid_body"),
            ({"summary": "x" * 301}, "invalid_summary"),
            ({"kind": "merge", "targets": json.dumps([{"type": "concept", "id": "a"}])}, "invalid_targets"),
            ({"kind": "rename"}, "invalid_targets"),
            ({"targets": json.dumps([{"type": "planet", "id": "a"}])}, "invalid_targets"),
            ({"kind": "merge", "targets": json.dumps([{"type": "concept", "id": "a"}, {"type": "concept", "id": "a"}])}, "invalid_targets"),
            ({"targets": "not json"}, "invalid_targets"),
            ({"evidence": json.dumps({"signals": "many"})}, "invalid_evidence"),
        ]
        with ReaderBackend() as backend:
            for overrides, error in cases:
                with self.subTest(error=error, overrides=overrides):
                    answer = backend.proposal_call("fileProposal", {"kind": "story_draft", "title": "T", "body": BODY, **overrides})
                    self.assertEqual((answer["status"], answer["error"]), ("refused", error))
            self.assertEqual(backend.proposals(), [])

    def test_only_editors_and_admins_may_file_or_decide(self) -> None:
        with ReaderBackend() as backend:
            for groups in ((), ("reader",), ("viewer",)):
                answer = backend.proposal_call("fileProposal", {"kind": "story_draft", "title": "T", "body": BODY}, groups=groups)
                self.assertEqual(answer["error"], "not_staff")
            self.assertEqual(backend.proposal_call("fileProposal", {"kind": "story_draft", "title": "T", "body": BODY}, groups=("admin",))["status"], "ok")
            identifier = file_one(backend)
            outsider = backend.proposal_call("transitionProposal", {"proposalId": identifier, "state": "in_steering"}, groups=("reader",))
            self.assertEqual(outsider["error"], "not_staff")
            self.assertEqual(row_of(backend, identifier)["state"], "draft")


class TransitionTests(unittest.TestCase):
    def test_the_whole_road_to_approval_is_recorded_in_the_history(self) -> None:
        with ReaderBackend() as backend:
            identifier = file_one(backend)
            decide(backend, identifier, "approved", reason="Good evidence.")
            row = row_of(backend, identifier)
            history = json.loads(row["history"])
            self.assertEqual(row["state"], "approved")
            self.assertEqual([entry["to"] for entry in history], ["draft", "in_steering", "editor_review", "approved"])
            self.assertEqual(history[-1]["reason"], "Good evidence.")
            self.assertEqual(history[-1]["actor"], "staff-sub-1")

    def test_every_allowed_move_and_no_other_is_accepted(self) -> None:
        allowed = {(a, b) for a, targets in rules.TRANSITIONS.items() for b in targets}
        self.assertEqual(allowed, {("draft", "in_steering"), ("draft", "declined"), ("in_steering", "editor_review"), ("editor_review", "approved"), ("editor_review", "declined"), ("editor_review", "overridden_by_editor")})
        for before in rules.STATES:
            for after in rules.STATES:
                with self.subTest(before=before, after=after):
                    plan = rules.transition_plan({"state": before, "history": "[]"}, after, "Because.", actor_sub="s", now_iso="2026-10-22T00:00:00Z", result="declined" if after == "overridden_by_editor" else None)
                    self.assertEqual(not isinstance(plan, rules.Outcome), (before, after) in allowed, plan)

    def test_a_refused_move_changes_nothing(self) -> None:
        with ReaderBackend() as backend:
            identifier = file_one(backend)
            before = row_of(backend, identifier)
            answer = move(backend, identifier, "approved")
            self.assertEqual((answer["status"], answer["error"]), ("refused", "transition_not_allowed"))
            self.assertEqual(row_of(backend, identifier), before)
            self.assertEqual(move(backend, identifier, "limbo")["error"], "invalid_state")
            self.assertEqual(move(backend, "prop-" + "0" * 32, "in_steering")["error"], "not_found")
            self.assertEqual(move(backend, "nonsense", "in_steering")["error"], "invalid_proposal")

    def test_decided_proposals_are_final(self) -> None:
        with ReaderBackend() as backend:
            identifier = file_one(backend)
            decide(backend, identifier, "declined")
            for state in rules.STATES:
                self.assertEqual(move(backend, identifier, state)["error"], "transition_not_allowed")

    def test_an_override_needs_a_public_reason_and_the_editors_result(self) -> None:
        with ReaderBackend() as backend:
            identifier = file_one(backend)
            move(backend, identifier, "in_steering")
            move(backend, identifier, "editor_review")
            self.assertEqual(move(backend, identifier, "overridden_by_editor", result="declined")["error"], "reason_required")
            self.assertEqual(move(backend, identifier, "overridden_by_editor", reason="   ", result="declined")["error"], "reason_required")
            self.assertEqual(move(backend, identifier, "overridden_by_editor", reason="Coordinated votes.")["error"], "result_required")
            self.assertEqual(move(backend, identifier, "overridden_by_editor", reason="Coordinated votes.", result="maybe")["error"], "result_required")
            self.assertEqual(row_of(backend, identifier)["state"], "editor_review")
            self.assertEqual(move(backend, identifier, "overridden_by_editor", reason="Coordinated votes.", result="declined")["status"], "ok")
            self.assertEqual(json.loads(row_of(backend, identifier)["history"])[-1]["result"], "declined")

    def test_only_an_override_carries_a_result_and_a_reason_has_a_limit(self) -> None:
        with ReaderBackend() as backend:
            identifier = file_one(backend)
            self.assertEqual(move(backend, identifier, "in_steering", result="approved")["error"], "result_not_allowed")
            self.assertEqual(move(backend, identifier, "in_steering", reason="x" * 501)["error"], "invalid_reason")

    def test_a_move_made_on_a_stale_view_is_refused(self) -> None:
        with ReaderBackend() as backend:
            identifier = file_one(backend)
            stale = backend.store.get_proposal(identifier)
            move(backend, identifier, "in_steering")
            plan = rules.transition_plan(stale, "declined", "Not now.", actor_sub="s", now_iso="2026-10-22T00:00:00Z")
            self.assertFalse(backend.store.change_proposal(identifier, plan, stale["state"], "2026-10-22T00:00:00Z"))
            self.assertEqual(row_of(backend, identifier)["state"], "in_steering")


class VoteCountsTests(unittest.TestCase):
    def test_missing_counts_are_zero(self) -> None:
        counts = public.VoteCounts.from_items_file({"items": {}})
        self.assertEqual(counts.votes("prop-1"), {"up": 0, "down": 0, "net": 0})
        self.assertEqual(public.VoteCounts().votes("prop-1"), {"up": 0, "down": 0, "net": 0})
        self.assertEqual(public.VoteCounts.from_items_file(None).comments("prop-1"), 0)

    def test_counts_are_read_for_the_proposal_subject_and_net_defaults_to_up_minus_down(self) -> None:
        payload = {"items": {public.proposal_subject_key("prop-1"): {"up": 7, "down": 2, "comments": 3}, public.proposal_subject_key("prop-2"): {"up": 1, "down": 4, "net": -3}}}
        counts = public.VoteCounts.from_items_file(payload)
        self.assertEqual(counts.votes("prop-1"), {"up": 7, "down": 2, "net": 5})
        self.assertEqual(counts.votes("prop-2"), {"up": 1, "down": 4, "net": -3})
        self.assertEqual(counts.comments("prop-1"), 3)

    def test_a_weighted_net_stays_fractional_and_up_and_down_stay_whole(self) -> None:
        counts = public.VoteCounts({public.proposal_subject_key("prop-1"): {"up": 4, "down": 2, "net": 1.6667, "score": 1.2, "flags": 1}})
        votes = counts.votes("prop-1")
        self.assertEqual(votes, {"up": 4, "down": 2, "net": 1.6667})
        self.assertIsInstance(votes["up"], int)
        row = {"id": "prop-1", "kind": "rename", "title": "T", "body": "b", "state": "editor_review", "proposer": "ai", "createdAt": "2026-10-22T00:00:00Z", "history": "[]"}
        self.assertEqual(public.public_proposal(row, counts)["communityResult"]["net"], 1.6667)
        stored = {**row, "communityResult": json.dumps({"up": 4, "down": 2, "net": -0.3333, "at": "t"})}
        self.assertEqual(public.public_proposal(stored, counts)["communityResult"]["net"], -0.3333)

    def test_a_snapshot_from_before_downvotes_has_only_up(self) -> None:
        counts = public.VoteCounts({public.proposal_subject_key("prop-1"): {"up": 5}})
        self.assertEqual(counts.votes("prop-1"), {"up": 5, "down": 0, "net": 5})


class PublicFilesTests(unittest.TestCase):
    def snapshot(self, backend: ReaderBackend, writer: LocalDirectoryWriter, **kwargs):
        return run_snapshot(backend, writer, **kwargs)

    def read(self, writer: LocalDirectoryWriter, key: str) -> dict:
        body = writer.get(key)
        self.assertIsNotNone(body, f"{key} was not written; the store holds {sorted(entry.key for entry in writer.list())}")
        return json.loads(body)

    def test_a_draft_is_public_and_labelled_and_names_no_one(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            identifier = file_one(backend, summary="One line.", targets=json.dumps([{"type": "concept", "id": "agents"}]), evidence=json.dumps({"signals": 12, "source": "arXiv"}))
            writer = LocalDirectoryWriter(Path(directory))
            report = self.snapshot(backend, writer)
            index = self.read(writer, "_data/proposals/index.json")
            self.assertEqual(report.proposals, 1)
            entry = index["proposals"][0]
            self.assertEqual((entry["id"], entry["state"], entry["label"], entry["proposedBy"], entry["group"]), (identifier, "draft", "Draft · Proposed by AI", "AI", "stories"))
            self.assertEqual(entry["votes"], {"up": 0, "down": 0, "net": 0})
            self.assertEqual(entry["evidence"], {"signals": 12, "source": "arXiv"})
            self.assertEqual(entry["targets"], [{"type": "concept", "id": "agents"}])
            self.assertIsNone(entry["decision"])
            self.assertIsNone(entry["communityResult"])
            detail = self.read(writer, f"_data/proposals/{identifier}.json")["proposal"]
            self.assertEqual(detail["body"], BODY)
            self.assertEqual([(step["from"], step["to"], step["by"]) for step in detail["history"]], [(None, "draft", "AI")])
            everything = "".join(entry.key + (writer.get(entry.key) or b"").decode() for entry in writer.list())
            for private in ("staff-sub-1", '"proposer"', "actor"):
                self.assertNotIn(private, everything.replace("proposedBy", ""))

    def test_votes_cast_on_a_proposal_reach_its_public_files(self) -> None:
        with ReaderBackend(subject_types=("item", "proposal")) as backend, tempfile.TemporaryDirectory() as directory:
            identifier = file_one(backend)
            for name, handle, value in (("alice", "quiet-fox", 1), ("bob", "loud-owl", 1), ("carol", "plain-cat", -1)):
                subject = subject_for(name)
                backend.call(subject, "handle", {"handle": handle})
                answer = backend.call(subject, "vote", {"subject": {"type": "proposal", "id": identifier}, "value": value})
                self.assertEqual(answer["statusCode"], 200, answer)
            backend.age_everyone()
            writer = LocalDirectoryWriter(Path(directory))
            self.snapshot(backend, writer, subject_types=("item", "proposal"))
            votes = self.read(writer, "_data/proposals/index.json")["proposals"][0]["votes"]
            self.assertEqual(votes, {"up": 2, "down": 1, "net": 1.0})

    def test_groups_follow_the_kind(self) -> None:
        self.assertEqual([public.group_of(kind) for kind in rules.KINDS], ["stories", "concepts", "map_changes", "map_changes", "map_changes", "map_changes", "map_changes"])

    def test_in_steering_shows_the_live_votes_and_a_reader_proposer_reads_reader(self) -> None:
        row = {"id": "prop-1", "kind": "rename", "title": "T", "body": "b", "state": "in_steering", "proposer": "ss1_secret-subject", "createdAt": "2026-10-22T00:00:00Z", "history": "[]"}
        counts = public.VoteCounts({public.proposal_subject_key("prop-1"): {"up": 4, "down": 1}})
        entry = public.public_proposal(row, counts)
        self.assertEqual((entry["label"], entry["votes"]), ("In steering · Proposed by Reader", {"up": 4, "down": 1, "net": 3}))
        self.assertNotIn("ss1_secret-subject", json.dumps(entry))

    def test_the_community_result_is_fixed_on_reaching_editor_review_and_shown_beside_the_decision(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            identifier = file_one(backend, kind="merge", targets=json.dumps([{"type": "concept", "id": "a"}, {"type": "concept", "id": "b"}]))
            move(backend, identifier, "in_steering")
            move(backend, identifier, "editor_review")
            writer = LocalDirectoryWriter(Path(directory))
            self.snapshot(backend, writer)
            first = self.read(writer, "_data/proposals/index.json")["proposals"][0]
            self.assertEqual(first["state"], "editor_review")
            fixed = json.loads(row_of(backend, identifier)["communityResult"])
            self.assertEqual({key: fixed[key] for key in ("up", "down", "net")}, {"up": 0, "down": 0, "net": 0})
            self.assertEqual(first["communityResult"]["at"], fixed["at"])
            move(backend, identifier, "overridden_by_editor", reason="Coordinated votes from new accounts.", result="declined")
            backend.now += 120
            self.snapshot(backend, writer)
            decided = self.read(writer, f"_data/proposals/{identifier}.json")["proposal"]
            self.assertEqual(decided["label"], "Overridden by editor · Proposed by AI")
            self.assertEqual(decided["decision"]["state"], "overridden_by_editor")
            self.assertEqual((decided["decision"]["result"], decided["decision"]["reason"], decided["decision"]["by"]), ("declined", "Coordinated votes from new accounts.", "Editor"))
            self.assertEqual(decided["communityResult"]["at"], fixed["at"], "the community result stays what it was when review began")
            self.assertEqual(json.loads(row_of(backend, identifier)["communityResult"]), fixed)
            self.assertEqual([step["by"] for step in decided["history"]], ["AI", "Staff", "Staff", "Editor"])
            self.assertEqual(decided["history"][-1]["result"], "declined")

    def test_an_approval_publishes_the_decision_line(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            identifier = file_one(backend)
            decide(backend, identifier, "approved", reason="Reads well.")
            writer = LocalDirectoryWriter(Path(directory))
            self.snapshot(backend, writer)
            entry = self.read(writer, "_data/proposals/index.json")["proposals"][0]
            self.assertEqual((entry["label"], entry["decision"]["result"], entry["decision"]["reason"]), ("Approved · Proposed by AI", "approved", "Reads well."))

    def test_the_index_lists_newest_first_and_unchanged_files_are_not_rewritten(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            first = file_one(backend, title="First")
            backend.now += 60
            second = file_one(backend, title="Second")
            writer = LocalDirectoryWriter(Path(directory))
            report = self.snapshot(backend, writer)
            index = self.read(writer, "_data/proposals/index.json")
            self.assertEqual([entry["id"] for entry in index["proposals"]], [second, first])
            self.assertEqual(sum(1 for key in report.written if "/proposals/" in key or key.startswith("_data/proposals/")), 3)
            before = {entry.key: writer.get(entry.key) for entry in writer.list() if "/proposals/" in "/" + entry.key}
            backend.now += 3600
            again = self.snapshot(backend, writer)
            after = {entry.key: writer.get(entry.key) for entry in writer.list() if "/proposals/" in "/" + entry.key}
            self.assertEqual(after, before, "an unchanged snapshot leaves every proposal file byte for byte as it was, old generatedAt included")
            self.assertEqual([key for key in again.written if key.startswith("_data/proposals/")], [], "only the freshness stamp changed")
            move(backend, first, "in_steering")
            changed = self.snapshot(backend, writer)
            self.assertIn(f"_data/proposals/{first}.json", changed.written)
            self.assertNotIn(f"_data/proposals/{second}.json", changed.written)

    def test_the_files_sit_under_the_base_path_and_are_never_orphans(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            identifier = file_one(backend)
            writer = LocalDirectoryWriter(Path(directory))
            self.snapshot(backend, writer, base_path="posts")
            self.assertIsNotNone(writer.get("posts/_data/proposals/index.json"))
            self.assertIsNotNone(writer.get(f"posts/_data/proposals/{identifier}.json"))
            self.assertTrue(is_plugin_runtime_key("posts/_data/proposals/index.json"))
            self.assertTrue(is_plugin_runtime_key(f"_data/proposals/{identifier}.json"))

    def test_a_site_without_proposals_writes_no_proposal_files(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            writer = LocalDirectoryWriter(Path(directory))
            report = self.snapshot(backend, writer)
            self.assertEqual(report.proposals, 0)
            self.assertIsNone(writer.get("_data/proposals/index.json"))


class ParityTests(unittest.TestCase):
    def test_the_public_module_and_the_function_agree_on_kinds_and_states(self) -> None:
        self.assertEqual(
            {public.DRAFT, public.IN_STEERING, public.EDITOR_REVIEW, public.APPROVED, public.DECLINED, public.OVERRIDDEN_BY_EDITOR},
            set(rules.STATES),
        )
        self.assertEqual(set(public.STATE_LABELS), set(rules.STATES))
        self.assertTrue(set(public.GROUPS) <= set(rules.KINDS))


if __name__ == "__main__":
    unittest.main()
