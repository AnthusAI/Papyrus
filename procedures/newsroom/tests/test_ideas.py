"""The idea pipeline v0: digest grouping, synthesis validation, dedupe, private storage, cost and the review seam."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from datetime import timedelta
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ideas_fixtures import CORPUS, NOW, FakeClient, FakeModel, entity, idea, reference, relevance, story  # noqa: E402
from papyrus import cli as papyrus_cli  # noqa: E402
from papyrus_content.ideas import commands, dedupe, digest as digest_module, synthesis  # noqa: E402
from papyrus_content.ideas.context import load_context  # noqa: E402
from papyrus_content.ideas.pipeline import RunRefused, synthesize  # noqa: E402
from papyrus_content import review_requests  # noqa: E402
from papyrus_content.ideas.review import load_feedback, merge_feedback, request_human_review  # noqa: E402
from papyrus_content.ideas.store import JsonStore, ProposalStore, StoreRefused  # noqa: E402


def make_digest(references, relations=None, **options):
    client = FakeClient(references=references, relations=relations or {})
    return digest_module.make_digest(client, publication="example-site", corpus_ids=[CORPUS], now=NOW, **options), client


def five_references():
    return [reference(n) for n in range(1, 6)]


class DigestTests(unittest.TestCase):
    def test_groups_references_by_section_and_label_largest_group_first(self) -> None:
        rows = [reference(1), reference(2), reference(3), reference(4, corpus="knowledge-corpus-other")]
        relations = {rows[0]["lineageId"]: [relevance(rows[0])], rows[1]["lineageId"]: [relevance(rows[1])], rows[3]["lineageId"]: [relevance(rows[3], "review")]}
        client = FakeClient(references=rows, relations=relations, corpora=(CORPUS, "knowledge-corpus-other"))
        result = digest_module.make_digest(client, publication="example-site", corpus_ids=[CORPUS, "knowledge-corpus-other"], now=NOW)
        self.assertEqual([(g["section"], g["label"], g["count"]) for g in result["groups"]],
                         [("example-site", "include", 2), ("example-site", "unlabelled", 1), ("other", "review", 1)])
        self.assertEqual(result["counts"]["bySection"], {"example-site": 3, "other": 1})

    def test_entries_carry_title_source_why_and_entities(self) -> None:
        row = reference(1)
        result, _ = make_digest([row], {row["lineageId"]: [relevance(row, score=0.76), entity(row, "agents")]})
        entry = result["references"][0]
        self.assertEqual((entry["title"], entry["source"], entry["status"]), ("Reference 1", "example1.org", "accepted"))
        self.assertEqual(entry["entities"], ["agents"])
        self.assertEqual(entry["relevance"]["score"], 0.76)
        self.assertIn("Accepted because reason 1", entry["whyIncluded"])
        self.assertIn("labelled it include", entry["whyIncluded"])

    def test_only_accepted_current_references_inside_the_window_by_default(self) -> None:
        rows = [reference(1), reference(2, days_ago=9), reference(3, status="pending"), reference(4, status="rejected"), reference(5, state="superseded")]
        result, _ = make_digest(rows, since="7d")
        self.assertEqual([entry["title"] for entry in result["references"]], ["Reference 1"])

    def test_pending_is_included_only_when_asked_and_stays_labelled(self) -> None:
        rows = [reference(1), reference(2, status="pending")]
        result, _ = make_digest(rows, statuses=["accepted", "pending"])
        self.assertEqual(result["counts"]["byStatus"], {"accepted": 1, "pending": 1})
        pending = next(entry for entry in result["references"] if entry["status"] == "pending")
        self.assertIn("Not yet reviewed by an editor", pending["whyIncluded"])

    def test_the_same_references_give_the_same_digest(self) -> None:
        first, _ = make_digest(five_references())
        second, _ = make_digest(list(reversed(five_references())))
        self.assertEqual(first["digestId"], second["digestId"])
        self.assertEqual(first["references"], second["references"])
        self.assertEqual(first["groups"], second["groups"])

    def test_the_window_and_status_options_are_checked(self) -> None:
        self.assertEqual(digest_module.parse_window("36h").total_seconds(), 36 * 3600)
        for bad in ("week", "0d", "7"):
            with self.assertRaises(ValueError):
                digest_module.parse_window(bad)
        with self.assertRaises(ValueError):
            digest_module.parse_statuses("accepted,archived")

    def test_the_reference_limit_keeps_the_newest(self) -> None:
        rows = [reference(n, days_ago=n) for n in range(1, 6)]
        result, _ = make_digest(rows, maximum_references=2)
        self.assertEqual([entry["title"] for entry in result["references"]], ["Reference 1", "Reference 2"])
        self.assertEqual(result["counts"]["considered"], 5)

    def test_excerpts_are_fetched_only_when_asked(self) -> None:
        fetched = []
        page = "<html><meta name='description' content='Meta line.'><p>" + "A long enough paragraph about the topic. " * 3 + "</p></html>"
        result, _ = make_digest([reference(1)], excerpts=True, fetch=lambda url: fetched.append(url) or page)
        self.assertIn("Meta line.", result["references"][0]["summary"])
        make_digest([reference(1)], fetch=lambda url: fetched.append(url) or page)
        self.assertEqual(len(fetched), 1)


class ValidationTests(unittest.TestCase):
    HANDLES = {"R1": "id-1", "R2": "id-2", "R3": "id-3"}

    def check(self, *ideas, sections=("Analysis",), maximum=5):
        return synthesis.validate_ideas(list(ideas), self.HANDLES, list(sections), maximum)

    def test_a_synthesis_of_two_existing_references_is_kept_with_real_ids(self) -> None:
        valid, invalid = self.check(idea("Two things", ["R1", "R2"]))
        self.assertEqual((len(valid), invalid), (1, []))
        self.assertEqual(valid[0]["citedReferenceIds"], ["id-1", "id-2"])
        self.assertEqual(valid[0]["claims"][0]["referenceIds"], ["id-1", "id-2"])

    def test_fewer_than_two_distinct_citations_is_dropped(self) -> None:
        for handles in (["R1"], ["R1", "R1"], []):
            valid, invalid = self.check(idea("One source", handles))
            self.assertEqual((valid, invalid[0]["reason"]), ([], "fewer_than_two_citations"))

    def test_citing_a_reference_that_is_not_in_the_digest_is_dropped(self) -> None:
        valid, invalid = self.check(idea("Made up", ["R1", "R9"]))
        self.assertEqual((valid, invalid[0]["reason"]), ([], "cites_unknown_references:R9"))

    def test_every_claim_must_cite_references_the_idea_lists(self) -> None:
        bad = idea("Stray claim", ["R1", "R2"])
        bad["claims"].append({"claim": "Something from R3.", "references": ["R3"]})
        uncited = idea("Bare claim", ["R1", "R2"])
        uncited["claims"] = [{"claim": "Unsupported.", "references": []}]
        for item in (bad, uncited):
            valid, invalid = self.check(item)
            self.assertEqual((valid, invalid[0]["reason"]), ([], "claim_cites_a_reference_the_idea_does_not_list"))

    def test_the_section_must_be_one_the_site_has_and_is_normalised(self) -> None:
        valid, _ = self.check(idea("Cased", ["R1", "R2"], section="analysis"))
        self.assertEqual(valid[0]["section"], "Analysis")
        valid, invalid = self.check(idea("Elsewhere", ["R1", "R2"], section="Sports"))
        self.assertEqual((valid, invalid[0]["reason"]), ([], "unknown_section"))

    def test_banned_words_and_missing_fields_are_dropped(self) -> None:
        valid, invalid = self.check(idea("From the news desk", ["R1", "R2"]), idea("", ["R1", "R2"]), idea("No note", ["R1", "R2"], note=""), "nonsense")
        self.assertEqual(valid, [])
        self.assertEqual([row["reason"] for row in invalid], ["banned_word", "missing_title_angle_or_novelty_note", "missing_title_angle_or_novelty_note", "not_an_object"])

    def test_extra_ideas_over_the_maximum_are_reported(self) -> None:
        valid, invalid = self.check(idea("One", ["R1", "R2"]), idea("Two", ["R2", "R3"]), maximum=1)
        self.assertEqual(([v["title"] for v in valid], invalid), (["One"], [{"title": "Two", "reason": "over_the_maximum"}]))


class DedupeTests(unittest.TestCase):
    STORY = dedupe.Document("story", "s1", "Prompt injection breaks AI agents", "A study shows agents obey instructions hidden in web pages.")

    def test_a_reworded_copy_of_an_existing_story_is_a_near_duplicate(self) -> None:
        candidate = {"title": "Why prompt injection still breaks AI agents", "angle": "Agents obey instructions hidden in web pages, a study shows."}
        kept, dropped = dedupe.split_duplicates([candidate], [self.STORY, dedupe.Document("story", "s2", "Rotating cloud keys", "Key rotation basics.")])
        self.assertEqual(kept, [])
        self.assertEqual((dropped[0]["reason"], dropped[0]["similarTo"]["id"]), ("near_duplicate", "s1"))

    def test_a_different_idea_is_kept(self) -> None:
        candidate = {"title": "Supply chain trust for model weights", "angle": "Who signs a checkpoint, and what a signature proves."}
        kept, dropped = dedupe.split_duplicates([candidate], [self.STORY])
        self.assertEqual((len(kept), dropped), (1, []))

    def test_ideas_in_one_run_count_against_each_other(self) -> None:
        first = {"title": "Rotating cloud keys safely", "angle": "Key rotation for cloud accounts."}
        second = {"title": "Safely rotating cloud keys", "angle": "Cloud account key rotation."}
        kept, dropped = dedupe.split_duplicates([first, second], [])
        self.assertEqual(([k["title"] for k in kept], dropped[0]["similarTo"]["kind"]), (["Rotating cloud keys safely"], "idea"))

    def test_an_unrelated_empty_comparison_keeps_everything(self) -> None:
        self.assertEqual(dedupe.split_duplicates([{"title": "Anything", "angle": "Whatever."}], [])[1], [])


def run_pipeline(client, model, *, root, digest=None, **options):
    digest = digest or digest_module.make_digest(client, publication="example-site", corpus_ids=[CORPUS], now=NOW)
    context = load_context(client, now=NOW)
    options.setdefault("now", NOW)
    return synthesize(digest=digest, context=context, json_store=JsonStore(Path(root)), transport=model, **options), digest


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "ideas"

    def client(self, **extra):
        return FakeClient(references=five_references(), stories=[story("Prompt injection breaks AI agents", deck="A study shows agents obey hidden instructions in web pages.")],
                          sections=("Analysis", "News"), **extra)

    def handles(self, client):
        digest = digest_module.make_digest(client, publication="example-site", corpus_ids=[CORPUS], now=NOW)
        return list(synthesis.handles_for(digest))

    def test_a_run_creates_private_draft_ideas_that_cite_their_references(self) -> None:
        client = self.client()
        model = FakeModel([idea("Agents and keys", ["R1", "R2"]), idea("Weights and trust", ["R3", "R4", "R5"], section="News")])
        run, digest = run_pipeline(client, model, root=self.root)
        self.assertEqual((run["proposed"], run["ideasCreated"], run["duplicates"], run["invalid"]), (2, 2, [], []))
        first = run["ideas"][0]
        self.assertEqual((first["kind"], first["state"], first["proposer"], first["proposedBy"], first["private"]), ("story_draft", "draft", "ai", "AI", True))
        ids = {entry["id"] for entry in digest["references"]}
        self.assertTrue(set(first["citedReferenceIds"]) <= ids and len(first["citedReferenceIds"]) >= 2)
        self.assertEqual([c["id"] for c in first["citations"]], first["citedReferenceIds"])
        self.assertIn("## Cited references", first["body"])
        saved = sorted(path.name for path in (self.root / "ideas").glob("*.json"))
        self.assertEqual(len(saved), 2)

    def test_the_model_sees_the_mission_sections_stories_and_handles_not_ids(self) -> None:
        client = self.client()
        model = FakeModel([])
        run_pipeline(client, model, root=self.root)
        seen = model.model_input
        self.assertEqual(seen["mission"], "Explain how AI systems fail.")
        self.assertEqual(seen["allowed_sections"], ["Analysis", "News"])
        self.assertEqual(seen["recent_and_in_flight_stories"][0]["title"], "Prompt injection breaks AI agents")
        self.assertEqual([r["handle"] for r in seen["references"]], ["R1", "R2", "R3", "R4", "R5"])
        self.assertNotIn("reference-knowledge", json.dumps(seen))

    def test_near_duplicates_of_a_story_and_of_an_earlier_draft_are_dropped_and_recorded(self) -> None:
        client = self.client()
        first, _ = run_pipeline(client, FakeModel([idea("Weights and trust", ["R3", "R4"], angle="Who signs a model checkpoint and what a signature proves.")]), root=self.root)
        self.assertEqual(first["ideasCreated"], 1)
        model = FakeModel([
            idea("Prompt injection still breaks AI agents", ["R1", "R2"], angle="Agents obey instructions hidden in web pages, a study shows."),
            idea("Weights and trust", ["R3", "R4"], angle="Who signs a model checkpoint and what a signature proves."),
            idea("A new angle on rotating cloud keys", ["R1", "R5"], angle="Rotating cloud access keys after an incident."),
        ])
        second, _ = run_pipeline(client, model, root=self.root)
        self.assertEqual((second["proposed"], second["ideasCreated"], len(second["duplicates"])), (3, 1, 2))
        self.assertEqual({d["similarTo"]["kind"] for d in second["duplicates"]}, {"story", "draft"})
        self.assertEqual(second["ideas"][0]["title"], "A new angle on rotating cloud keys")

    def test_a_declined_idea_in_the_feedback_is_not_proposed_again(self) -> None:
        client = self.client()
        feedback = [{"title": "Rotating cloud keys safely", "verdict": "decline", "note": "Key rotation for cloud accounts: too basic."}]
        model = FakeModel([idea("Safely rotating cloud keys", ["R1", "R2"], angle="Key rotation for cloud accounts.")])
        run, _ = run_pipeline(client, model, root=self.root, feedback=feedback)
        self.assertEqual((run["ideasCreated"], run["duplicates"][0]["similarTo"]["kind"]), (0, "declined"))
        self.assertEqual(model.model_input["reviewer_feedback"], feedback)

    def test_fewer_than_two_references_makes_no_model_call(self) -> None:
        client = FakeClient(references=[reference(1)], sections=("Analysis",))
        model = FakeModel([idea("x", ["R1", "R2"])])
        run, _ = run_pipeline(client, model, root=self.root)
        self.assertEqual((model.requests, run["ideasCreated"], run["usage"]), ([], 0, None))
        self.assertIn("needs at least 2", run["noCall"])

    def test_the_run_records_tokens_and_cost(self) -> None:
        model = FakeModel([idea("A", ["R1", "R2"])], input_tokens=100_000, cached=20_000, output_tokens=10_000)
        run, _ = run_pipeline(self.client(), model, root=self.root)
        expected = (80_000 * 0.10 + 20_000 * 0.01 + 10_000 * 0.50) / 1_000_000
        self.assertEqual(run["usage"]["costUsd"], round(expected, 6))
        self.assertEqual((run["usage"]["inputTokens"], run["usage"]["outputTokens"], run["usage"]["model"]), (100_000, 10_000, "gpt-6-luna"))
        self.assertIn("LiteLLM", run["usage"]["priceBasis"])
        saved = json.loads((self.root / "runs" / f"{run['runId']}.json").read_text())
        self.assertEqual(saved["usage"]["costUsd"], run["usage"]["costUsd"])
        self.assertEqual(saved["inputs"]["references"], 5)

    def test_a_run_estimated_over_the_cost_cap_stops_before_the_call(self) -> None:
        model = FakeModel([])
        with self.assertRaises(RunRefused):
            run_pipeline(self.client(), model, root=self.root, maximum_cost_usd=0.000001)
        self.assertEqual(model.requests, [])

    def test_without_a_review_client_the_run_only_records_that_review_is_pending(self) -> None:
        run, _ = run_pipeline(self.client(), FakeModel([idea("A", ["R1", "R2"])]), root=self.root)
        self.assertEqual((run["review"]["status"], run["review"]["requested"], run["review"]["ideas"]), ("pending", False, 1))
        self.assertEqual(run["review"]["ideaIds"], [run["ideas"][0]["ideaId"]])

    def test_a_run_raises_one_soft_review_for_its_batch(self) -> None:
        client = self.client()
        run, _ = run_pipeline(client, FakeModel([idea("Cloud key rotation", ["R1", "R2"], angle="Rotating access keys after an incident."),
                                                idea("Model checkpoint signing", ["R3", "R4"], angle="What a signature on a model file proves.")]),
                              root=self.root, review_client=client)
        (request,) = client.reviews.values()
        read = review_requests.read_review(request)
        self.assertEqual((read["mode"], read["reason"], read["raisedBy"], read["state"]), ("soft_review", "2 new story ideas to review", "idea-pipeline", "open"))
        self.assertEqual(read["subject"], {"type": "batch", "id": run["runId"]})
        self.assertEqual([link["id"] for link in read["links"]], [idea_["ideaId"] for idea_ in run["ideas"]])
        self.assertEqual((run["review"]["status"], run["review"]["requested"], run["review"]["linkedAs"], run["review"]["requestId"]), ("requested", True, "idea", request["id"]))
        self.assertAlmostEqual((review_requests.parse_time(read["deadline"]) - review_requests.parse_time(read["raisedAt"])).days, 7, delta=0)
        request_human_review(client, run, run["ideas"])
        self.assertEqual(len(client.reviews), 1)

    def test_proposal_ideas_are_linked_by_proposal_id(self) -> None:
        client = self.client()
        run, _ = run_pipeline(client, FakeModel([idea("A", ["R1", "R2"])]), root=self.root, review_client=client, proposal_store=ProposalStore(client))
        (request,) = client.reviews.values()
        self.assertEqual([link["id"] for link in review_requests.read_review(request)["links"]], [run["ideas"][0]["proposalId"]])
        self.assertEqual(run["review"]["linkedAs"], "proposal")

    def test_no_ideas_raise_no_review(self) -> None:
        client = self.client()
        run, _ = run_pipeline(client, FakeModel([]), root=self.root, review_client=client)
        self.assertEqual((client.reviews, run["review"]["status"]), ({}, "none"))

    def test_a_site_without_review_requests_keeps_its_ideas_and_notes_why(self) -> None:
        client = self.client()
        client.reject_review_writes = True
        run, _ = run_pipeline(client, FakeModel([idea("A", ["R1", "R2"])]), root=self.root, review_client=client)
        self.assertEqual((run["ideasCreated"], run["review"]["status"], run["review"]["requested"]), (1, "not_raised", False))
        self.assertIn("createReviewRequest", run["review"]["error"])
        self.assertEqual(len(list((self.root / "ideas").glob("*.json"))), 1)

    def answered_batch(self, client, decision="reject", **answer):
        first, _ = run_pipeline(client, FakeModel([idea("Rotating cloud keys safely", ["R1", "R2"], angle="Key rotation for cloud accounts.")]), root=self.root, review_client=client)
        review_requests.answer_review(client, client.reviews and next(iter(client.reviews)), decision=decision, by="editor", **answer)
        return first

    def test_a_rejected_batch_steers_the_next_run_and_is_marked_applied(self) -> None:
        client = self.client()
        first = self.answered_batch(client, feedback="Too basic; we want incident-driven pieces.", steer="not_this_kind")
        model = FakeModel([idea("Safely rotating cloud keys", ["R1", "R2"], angle="Key rotation for cloud accounts."), idea("Model checkpoint signing", ["R3", "R4"], angle="What a signature on a model file proves.")])
        second, _ = run_pipeline(client, model, root=self.root, review_client=client, now=NOW + timedelta(days=1))
        shown = model.model_input["reviewer_feedback"]
        self.assertEqual([(e["title"], e["verdict"]) for e in shown], [("Rotating cloud keys safely", "decline")])
        self.assertIn("Too basic", shown[0]["note"])
        self.assertIn("not_this_kind", shown[0]["note"])
        self.assertEqual([i["title"] for i in second["ideas"]], ["Model checkpoint signing"])
        self.assertIn(second["duplicates"][0]["similarTo"]["kind"], {"declined", "draft"})
        original = review_requests.get_review(client, second["steering"]["requestIds"][0], sweep=False)
        self.assertEqual(original["appliedIn"]["runId"], second["runId"])
        self.assertEqual((second["steering"]["entries"], second["steering"]["requestIds"], second["steering"]["notApplied"]), (1, [original["id"]], []))
        self.assertEqual(original["subject"]["id"], first["runId"])
        third = FakeModel([])
        later, _ = run_pipeline(client, third, root=self.root, review_client=client)
        self.assertEqual((later["steering"]["entries"], third.model_input["reviewer_feedback"]), (0, []))

    def test_an_approval_with_a_note_comes_back_as_a_revise_entry(self) -> None:
        client = self.client()
        self.answered_batch(client, decision="approve", feedback="Good; keep them shorter.")
        model = FakeModel([])
        run_pipeline(client, model, root=self.root, review_client=client)
        self.assertEqual([(e["verdict"], e["note"]) for e in model.model_input["reviewer_feedback"]], [("accept", "Good; keep them shorter.")])

    def test_steering_is_not_marked_applied_when_no_model_call_is_made(self) -> None:
        client = self.client()
        self.answered_batch(client, feedback="Narrower please.")
        small = FakeClient(references=[reference(1)], sections=("Analysis",))
        small.reviews = client.reviews
        run, _ = run_pipeline(small, FakeModel([]), root=self.root, review_client=small)
        self.assertEqual(run["steering"]["entries"], 1)
        self.assertIsNone(review_requests.get_review(small, run["steering"]["requestIds"][0], sweep=False)["appliedIn"])

    def test_a_site_without_review_requests_gets_no_steering_and_runs_on(self) -> None:
        client = self.client()
        with mock.patch.object(review_requests, "steering_for", side_effect=RuntimeError("no such model")):
            run, _ = run_pipeline(client, FakeModel([idea("A", ["R1", "R2"])]), root=self.root, review_client=client)
        self.assertEqual((run["steering"]["entries"], run["ideasCreated"]), (0, 1))
        self.assertIn("no such model", run["steering"]["error"])

    def test_manual_feedback_overrides_steering_for_the_same_title(self) -> None:
        steering = [{"title": "Same idea", "verdict": "decline", "note": "from steering"}, {"title": "Other", "verdict": "revise", "note": "x"}]
        manual = [{"title": "same idea", "verdict": "accept", "note": "manual"}]
        self.assertEqual(merge_feedback(steering, manual), [steering[1], manual[0]])

    def test_feedback_files_are_checked(self) -> None:
        path = Path(self.directory.name) / "feedback.json"
        path.write_text(json.dumps([{"title": "T", "verdict": "revise", "note": "Narrower."}]))
        self.assertEqual(load_feedback(str(path)), [{"title": "T", "verdict": "revise", "note": "Narrower."}])
        path.write_text(json.dumps([{"title": "T", "verdict": "maybe"}]))
        with self.assertRaises(ValueError):
            load_feedback(str(path))
        self.assertEqual(load_feedback(None), [])


class PrivacyTests(unittest.TestCase):
    def test_the_json_store_refuses_a_public_data_directory(self) -> None:
        for path in ("/tmp/site/_data/proposals", "/tmp/site/public/ideas", "/tmp/site/static-root"):
            with self.assertRaises(StoreRefused):
                JsonStore(Path(path))

    def test_a_default_run_writes_only_under_its_own_directory_and_never_asks_a_site_to_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient(references=five_references(), sections=("Analysis",))
            run_pipeline(client, FakeModel([idea("A", ["R1", "R2"])]), root=Path(directory) / "ideas")
            written = {str(path.relative_to(directory)).split(os.sep)[1] for path in Path(directory).rglob("*.json")}
            self.assertEqual(written, {"ideas", "runs"})
            self.assertFalse(list(Path(directory).rglob("proposals*")))
        kinds = {call[1] for call in client.calls if call[0] == "graphql"}
        self.assertNotIn("mutation FileProposal", kinds)
        self.assertFalse([call for call in client.calls if "publish" in str(call).lower()])

    def test_a_proposal_run_files_each_idea_as_a_draft_story_proposal_and_publishes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient(references=five_references(), sections=("Analysis",))
            run, _ = run_pipeline(client, FakeModel([idea("Cloud key rotation", ["R1", "R2"], angle="Rotating access keys after an incident."), idea("Model checkpoint signing", ["R3", "R4"], angle="What a signature on a model file proves.")]), root=Path(directory) / "ideas", proposal_store=ProposalStore(client))
        filed = [row for row in client.proposals if "kind" in row]
        self.assertEqual([row["kind"] for row in filed], ["story_draft", "story_draft"])
        self.assertEqual(run["store"], "proposals")
        self.assertTrue(all(idea_["proposalId"].startswith("prop-") for idea_ in run["ideas"]))
        self.assertNotIn("publish", json.dumps(client.calls))
        evidence = json.loads(filed[0]["evidence"])
        self.assertEqual(evidence["signals"], 2)
        self.assertIn(run["digestId"], evidence["source"])

    def test_an_iam_run_reads_story_drafts_through_the_operator_query_and_dedupes_against_them(self) -> None:
        earlier = {"id": "prop-" + "b" * 32, "kind": "story_draft", "title": "Cloud key rotation", "summary": "Rotating access keys after an incident.", "state": "draft",
                   "targets": "[]", "createdAt": "2026-10-20T00:00:00Z"}

        class OperatorOnly(FakeClient):
            def graphql(self, query, variables=None):
                if "listProposals" in query:
                    raise RuntimeError("Not Authorized to access listProposals on type Query")
                if "listStoryDrafts" in query:
                    self.calls.append(("operator-read", "listStoryDrafts"))
                    return {"listStoryDrafts": {"status": "ok", "error": None, "message": None, "drafts": [earlier]}}
                return super().graphql(query, variables)

        with tempfile.TemporaryDirectory() as directory, mock.patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "iam"}):
            client = OperatorOnly(references=five_references(), sections=("Analysis",))
            store = ProposalStore(client)
            run, _ = run_pipeline(client, FakeModel([
                idea("Cloud key rotation", ["R1", "R2"], angle="Rotating access keys after an incident."),
                idea("Model checkpoint signing", ["R3", "R4"], angle="What a signature on a model file proves."),
            ]), root=Path(directory) / "ideas", proposal_store=store)
        self.assertEqual([row["title"] for row in client.proposals if "kind" in row], ["Model checkpoint signing"])
        self.assertEqual([entry["reason"] for entry in run["duplicates"]], ["near_duplicate"])
        self.assertIn(("operator-read", "listStoryDrafts"), client.calls)
        with mock.patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "user"}), self.assertRaises(RuntimeError):
            ProposalStore(OperatorOnly()).story_drafts()


class CommandTests(unittest.TestCase):
    def run_cli(self, argv, client, model=None):
        out, err = io.StringIO(), io.StringIO()
        environment = {"OPENAI_API_KEY": "test-key"}
        with mock.patch.object(commands, "create_authoring_client", return_value=(client, {})), \
             mock.patch.object(commands.synthesis, "openai_transport", return_value=model), \
             mock.patch("papyrus_content.cli.load_dotenv"), mock.patch.dict(os.environ, environment), \
             redirect_stdout(out), redirect_stderr(err):
            code = papyrus_cli.main(["--allow-cross-root", "ideas", *argv])
        return code, out.getvalue() + err.getvalue()

    def test_digest_then_synthesize_by_digest_id_with_a_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient(references=[reference(n, days_ago=0.1) for n in range(1, 4)], sections=("Analysis",))
            code, output = self.run_cli(["digest", "--publication", "example-site", "--since", "7d", "--out", directory, "--json"], client)
            self.assertEqual(code, 0, output)
            digest_id = json.loads(output)["digest"]["digestId"]
            model = FakeModel([idea("A story", ["R1", "R2"])])
            report = Path(directory) / "report.md"
            code, output = self.run_cli(["synthesize", "--publication", "example-site", "--digest", digest_id, "--out", directory, "--report", str(report)], client, model)
            self.assertEqual(code, 0, output)
            self.assertIn("created 1", output)
            self.assertIn("review\trequested\trequested true", output)
            self.assertIn("steering\tentries 0", output)
            text = report.read_text()
            self.assertIn("Proposed by AI", text)
            self.assertNotIn("desk", text.lower())

    def test_an_unknown_publication_lists_the_real_keys_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code, output = self.run_cli(["digest", "--publication", "nope", "--out", directory], FakeClient())
        self.assertEqual(code, 2)
        self.assertIn("example-site", output)
        self.assertNotIn("Traceback", output)

    def test_the_output_directory_cannot_be_a_public_one(self) -> None:
        code, output = self.run_cli(["digest", "--publication", "example-site", "--out", "/tmp/site/_data/ideas"], FakeClient())
        self.assertEqual(code, 2)
        self.assertIn("private", output)


if __name__ == "__main__":
    unittest.main()
