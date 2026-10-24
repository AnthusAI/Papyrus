"""Trend stories: snapshot loading, signals, the citation check, the figure spec, filing as a draft Proposal, dedupe and the CLI.

The model is always a fake; nothing here reaches the network."""

from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ideas_fixtures import AS_OF, NOW, FakeClient, FakeTrendModel, history_entry, sentence, snapshot_files, trend_draft  # noqa: E402
from papyrus import cli as papyrus_cli  # noqa: E402
from papyrus_content import review_requests  # noqa: E402
from papyrus_content.ideas import commands, trends  # noqa: E402
from papyrus_content.ideas.store import JsonStore, ProposalStore  # noqa: E402

PUBLISHED = "Open licences spread through model hubs"


def write(directory: str, name: str, document) -> str:
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    return str(path)


def snapshot_from_entry(directory: str):
    return trends.load_snapshot(write(directory, "history/2026-10-19.json", history_entry()))


class ListingClient(FakeClient):
    """Answers ``listProposals`` with earlier Proposals, as an editor session would see them."""

    def __init__(self, *args, listed=(), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.listed = list(listed)

    def graphql(self, query, variables=None):
        if "listProposals" in query:
            return {"listProposals": {"items": self.listed, "nextToken": None}}
        return super().graphql(query, variables)


class SnapshotTests(unittest.TestCase):
    def test_a_weekly_archive_entry_is_a_whole_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = snapshot_from_entry(directory)
        self.assertEqual(snapshot["asOf"], AS_OF)
        self.assertEqual(len(snapshot["clusters"]), 2)
        self.assertEqual(snapshot["entityFile"]("platform--hugging-face")["neighbours"][0]["weight"], 5)

    def test_a_published_directory_is_read_file_by_file_with_the_archive_for_the_previous_week(self) -> None:
        files = snapshot_files()
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "index.json", files["index"])
            write(directory, "clusters.json", files["clusters"])
            write(directory, "entities/platform--hugging-face.json", files["entities"]["platform--hugging-face"])
            write(directory, "history/index.json", {"entries": [{"asOf": "2026-10-12", "file": "2026-10-12.json"}, {"asOf": AS_OF, "file": "2026-10-19.json"}]})
            write(directory, "history/2026-10-12.json", {"clusters": [{"uid": "cl-fb1252e1da52", "itemCount": 17}]})
            snapshot = trends.load_snapshot(directory)
            by_id = {signal["id"]: signal for signal in trends.build_signals(snapshot)}
        self.assertEqual(snapshot["previous"], {"asOf": "2026-10-12", "counts": {"cl-fb1252e1da52": 17}})
        cluster = by_id["cluster:cl-fb1252e1da52"]
        self.assertEqual((cluster["itemCountInPreviousArchive"], cluster["previousArchiveWeek"]), (17, "2026-10-12"))
        self.assertEqual(by_id["entity:platform--hugging-face"]["neighbours"][0]["name"], "Apache-2.0")
        self.assertNotIn("neighbours", by_id["entity:licence--apache-2-0"])  # an entity file that cannot be read is only missing colour

    def test_an_address_is_fetched_not_opened_as_a_path(self) -> None:
        files = snapshot_files()
        seen = []

        def fetch(location):
            seen.append(location)
            return {"index.json": files["index"], "clusters.json": files["clusters"]}.get(location.rsplit("/", 1)[1]) or (_ for _ in ()).throw(OSError("missing"))

        snapshot = trends.load_snapshot("https://site.example/_data/knowledge/", fetch)
        self.assertEqual(seen[:2], ["https://site.example/_data/knowledge/index.json", "https://site.example/_data/knowledge/clusters.json"])
        self.assertEqual(snapshot["asOf"], AS_OF)
        self.assertIsNone(snapshot["previous"])

    def test_something_that_is_not_a_snapshot_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            trends.load_snapshot(write(directory, "x.json", {"hello": "world"}))


class SignalTests(unittest.TestCase):
    def test_signals_are_clusters_then_trending_then_new_entities_and_do_not_depend_on_a_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            signals = trends.build_signals(snapshot_from_entry(directory))
        self.assertEqual([signal["id"] for signal in signals], [
            "cluster:cl-fb1252e1da52", "cluster:cl-aaaa00000001", "entity:platform--hugging-face", "entity:licence--apache-2-0", "entity:task--routing", "entity:task--typed-decisions"])
        hugging = signals[2]
        self.assertEqual((hugging["targetType"], hugging["targetId"], hugging["last4"], hugging["prior4"], hugging["percent"]), ("entity", "platform--hugging-face", 15, 10, 50))
        self.assertEqual(hugging["weeks"][-1], AS_OF)
        self.assertEqual(hugging["weeks"][0], "2026-08-31")

    def test_the_model_sees_handles_and_the_weekly_counts_with_their_dates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = snapshot_from_entry(directory)
            signals = trends.build_signals(snapshot)
        view = trends.build_input(snapshot, signals, {"sections": [{"title": "Analysis"}], "stories": []}, 3)["signals"]
        self.assertEqual([entry["handle"] for entry in view], ["S1", "S2", "S3", "S4", "S5", "S6"])
        self.assertEqual(view[2]["items_per_week"]["2026-10-19"], 2)
        self.assertIsNone(view[4]["percent"])  # a small base is stated, so the model is told not to quote a percentage


class CitationCheckTests(unittest.TestCase):
    def check(self, *drafts, maximum=3):
        with tempfile.TemporaryDirectory() as directory:
            signals = trends.build_signals(snapshot_from_entry(directory))
        by_id = {signal["id"]: signal for signal in signals}
        return trends.validate_drafts(list(drafts), trends.handles_for(signals), by_id, ["Analysis", "News"], maximum)

    def reasons(self, draft):
        valid, invalid = self.check(draft)
        self.assertEqual(valid, [])
        return [problem["reason"] for problem in invalid[0]["citationCheck"]["problems"]]

    def test_a_draft_whose_every_sentence_cites_a_real_signal_passes(self) -> None:
        valid, invalid = self.check(trend_draft())
        self.assertEqual(invalid, [])
        self.assertEqual(valid[0]["citationCheck"]["status"], "passed")
        self.assertEqual(valid[0]["citedSignalIds"], ["entity:platform--hugging-face", "entity:licence--apache-2-0"])

    def test_the_one_signal_two_sentence_draft_the_live_model_returned_fails_and_the_run_record_keeps_its_text(self) -> None:
        # The shape observed against gpt-6-luna on 2026-10-24: one signal, two single-sentence paragraphs.
        draft = trend_draft(
            "Routing's recent run paused in the week of 2026-10-19", cites=("S3", "S3"),
            body=[{"sentences": [sentence("The weekly count peaked at 7 on 2026-10-05.", "S3")]}, {"sentences": [sentence("The signal records 15 items.", "S3")]}],
        )
        valid, invalid = self.check(draft)
        self.assertEqual(valid, [])
        reasons = [problem["reason"] for problem in invalid[0]["citationCheck"]["problems"]]
        self.assertIn("fewer_than_three_body_sentences", reasons)
        self.assertIn("fewer_than_two_signals_cited", reasons)
        self.assertEqual(invalid[0]["draft"], draft)  # title, dek, body and citations, so a person can see why

    def test_the_prompt_states_the_minimums_the_check_enforces(self) -> None:
        for phrase in ("at least three body sentences", "at least two different signals", "Return maximum_drafts drafts"):
            self.assertIn(phrase, trends.SYSTEM_PROMPT)

    def test_an_uncited_sentence_blocks_the_draft_and_the_check_says_which(self) -> None:
        draft = trend_draft()
        draft["paragraphs"][0]["sentences"].append(sentence("Hugging Face is the main model hub."))
        valid, invalid = self.check(draft)
        self.assertEqual(valid, [])
        self.assertEqual(invalid[0]["reason"], "citation_check_failed")
        problem = invalid[0]["citationCheck"]["problems"][0]
        self.assertEqual((problem["where"], problem["reason"]), ("paragraph 1 sentence 3", "no_citation"))
        self.assertEqual(invalid[0]["title"], "Hugging Face and Apache-2.0 climb together")

    def test_a_citation_that_is_not_a_signal_in_the_snapshot_blocks_the_draft(self) -> None:
        draft = trend_draft()
        draft["paragraphs"][1]["sentences"][0] = sentence("The two are mentioned together in 5 items.", "S3", "S99")
        self.assertEqual(self.reasons(draft), ["unknown_signal:S99"])

    def test_a_number_that_the_cited_signals_do_not_hold_blocks_the_draft(self) -> None:
        draft = trend_draft()
        draft["paragraphs"][0]["sentences"][0] = sentence("Hugging Face appeared in 40 items over the last four weeks.", "S3")
        self.assertEqual(self.reasons(draft), ["number_not_in_cited_signals:40"])

    def test_a_number_held_by_another_signal_does_not_count_for_this_sentence(self) -> None:
        draft = trend_draft()
        draft["paragraphs"][0]["sentences"][0] = sentence("Hugging Face appeared in 12 items over the last four weeks.", "S3")  # 12 is Apache's
        self.assertEqual(self.reasons(draft), ["number_not_in_cited_signals:12"])

    def test_a_date_must_be_one_of_the_signal_dates_and_a_week_label_does_not_ground_small_numbers(self) -> None:
        draft = trend_draft()
        draft["paragraphs"][0]["sentences"][0] = sentence("Hugging Face led in the week of 2026-10-26.", "S3")
        self.assertEqual(self.reasons(draft), ["number_not_in_cited_signals:2026-10-26"])
        draft["paragraphs"][0]["sentences"][0] = sentence("Hugging Face led in the week of 2026-10-12 with 3 items.", "S3")
        valid, invalid = self.check(draft)
        self.assertEqual(len(valid), 1)
        draft["paragraphs"][0]["sentences"][0] = sentence("Hugging Face had 10 items in a week.", "S3")  # 10 is the prior-four total
        self.assertEqual(self.check(draft)[0][0]["citationCheck"]["status"], "passed")

    def test_an_entry_that_hides_two_sentences_blocks_the_draft(self) -> None:
        draft = trend_draft()
        draft["paragraphs"][0]["sentences"][0] = sentence("Hugging Face rose. Nobody cited a source for this.", "S3")
        self.assertEqual(self.reasons(draft), ["several_sentences_in_one_entry"])

    def test_the_headline_and_the_dek_are_claims_too(self) -> None:
        draft = trend_draft()
        draft["headline"] = sentence("Hugging Face is taking over")
        draft["dek"] = sentence("It doubled in 99 weeks.", "S3")
        self.assertEqual(self.reasons(draft), ["no_citation", "number_not_in_cited_signals:99"])

    def test_a_draft_needs_two_signals_three_body_sentences_a_known_section_and_a_figure_from_cited_signals(self) -> None:
        one_signal = trend_draft(cites=("S3", "S3"), body=[{"sentences": [sentence("Hugging Face appeared in 15 items.", "S3")] * 3}])
        self.assertIn("fewer_than_two_signals_cited", self.reasons(one_signal))
        short = trend_draft(body=[{"sentences": [sentence("Hugging Face appeared in 15 items.", "S3"), sentence("Apache-2.0 appeared in 12 items.", "S4")]}])
        self.assertIn("fewer_than_three_body_sentences", self.reasons(short))
        self.assertEqual(self.reasons(trend_draft(section="Gossip")), ["unknown_section"])
        self.assertEqual(self.reasons(trend_draft(figure=("S5",))), ["figure_signals_must_be_one_to_three_cited_signals"])
        self.assertEqual(self.reasons(trend_draft(figure=())), ["figure_signals_must_be_one_to_three_cited_signals"])
        caption = trend_draft()
        caption["figure_caption"] = "Hugging Face peaked at 99 items in one week."
        self.assertEqual(self.reasons(caption), ["number_not_in_cited_signals:99"])

    def test_the_banned_word_and_malformed_drafts_are_caught(self) -> None:
        draft = trend_draft()
        draft["dek"] = sentence("A desk would want this.", "S3")
        self.assertEqual(self.reasons(draft), ["banned_word"])
        valid, invalid = self.check("not a draft", {"headline": "no structure"})
        self.assertEqual((valid, [row["citationCheck"]["status"] for row in invalid]), ([], ["failed", "failed"]))

    def test_drafts_over_the_maximum_are_dropped_and_said_so(self) -> None:
        valid, invalid = self.check(trend_draft("One"), trend_draft("Two"), maximum=1)
        self.assertEqual(([d["headline"]["text"] for d in valid], [(i["title"], i["reason"]) for i in invalid]), (["One"], [("Two", "over_the_maximum")]))


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "ideas"
        self.snapshot = snapshot_from_entry(self.directory.name)

    def run_trends(self, drafts, client=None, *, proposals=True, dry_run=False, **options):
        client = client or FakeClient(sections=("Analysis", "News"), stories=[])
        model = FakeTrendModel(drafts)
        run = trends.draft_trends(
            snapshot=self.snapshot, site="example-site", context={"sections": [{"title": "Analysis"}, {"title": "News"}], "stories": options.pop("stories", []), "mission": "Explain.", "policy": "Be careful."},
            json_store=JsonStore(self.root), transport=model, proposal_store=ProposalStore(client) if proposals else None, review_client=client, dry_run=dry_run, now=NOW, **options)
        return run, client, model

    def filed(self, client):
        return [row for row in client.proposals if "kind" in row]

    def test_a_passing_draft_is_filed_as_an_ai_story_draft_proposal_with_targets_and_a_figure_spec(self) -> None:
        run, client, model = self.run_trends([trend_draft()])
        self.assertEqual((run["ideasCreated"], run["invalid"], run["store"]), (1, [], "proposals"))
        (row,) = self.filed(client)
        self.assertEqual(row["kind"], "story_draft")
        self.assertEqual(row["title"], "Hugging Face and Apache-2.0 climb together")
        self.assertEqual(json.loads(row["targets"]), [{"type": "entity", "id": "platform--hugging-face"}, {"type": "entity", "id": "licence--apache-2-0"}])
        evidence = json.loads(row["evidence"])
        self.assertEqual(evidence["signals"], 2)
        self.assertIn("knowledge snapshot 2026-10-19", evidence["source"])
        figure = evidence["figure"]
        self.assertEqual(
            figure,
            {"type": "line", "title": "Items per week", "caption": "Hugging Face peaked at 7 items in one week.", "unit": "items per week", "source": "knowledge snapshot 2026-10-19",
             "x": ["2026-08-31", "2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"],
             "series": [{"signal": "entity:platform--hugging-face", "label": "Hugging Face", "values": [1, 2, 3, 4, 7, 3, 3, 2]}]},
        )
        self.assertIn("[1]", row["body"])
        self.assertIn("## Signals cited", row["body"])
        self.assertIn("`entity:platform--hugging-face`", row["body"])
        self.assertEqual(model.requests[0]["model"], "gpt-6-luna")

    def test_the_draft_is_proposed_by_ai_and_nothing_is_transitioned_or_published(self) -> None:
        run, client, _ = self.run_trends([trend_draft()])
        record = run["drafts"][0]
        self.assertEqual((record["proposer"], record["proposedBy"], record["state"], record["kind"]), ("ai", "AI", "draft", "story_draft"))
        calls = json.dumps(client.calls)
        self.assertNotIn("transitionProposal", calls)
        self.assertNotIn("publish", calls.lower())
        self.assertEqual(sorted(path.parent.name for path in self.root.rglob("*.json")), ["ideas", "runs"])

    def test_every_sentence_of_a_kept_draft_is_recorded_with_the_signals_it_rests_on(self) -> None:
        run, _, _ = self.run_trends([trend_draft()])
        sentences = run["drafts"][0]["sentences"]
        self.assertEqual(sentences[0]["role"], "headline")
        self.assertTrue(all(entry["signalIds"] for entry in sentences))
        self.assertEqual(run["drafts"][0]["citationCheck"]["status"], "passed")

    def test_a_draft_that_fails_the_check_is_not_filed_and_the_run_record_says_why(self) -> None:
        bad = trend_draft("Unsupported headline")
        bad["paragraphs"][0]["sentences"].append(sentence("Everyone agrees this matters."))
        run, client, _ = self.run_trends([bad])
        self.assertEqual((run["ideasCreated"], self.filed(client)), (0, []))
        self.assertEqual(run["invalid"][0]["citationCheck"]["problems"][0]["reason"], "no_citation")
        saved = json.loads(next(self.root.joinpath("runs").glob("*.json")).read_text())
        self.assertEqual(saved["invalid"][0]["title"], "Unsupported headline")
        self.assertEqual(run["review"]["status"], "none")

    def test_one_soft_review_request_covers_the_whole_run(self) -> None:
        second = trend_draft("Two clusters on the map", cites=("S1", "S2"), figure=("S1",), body=[{"sentences": [
            sentence("Decision models held 21 items.", "S1"), sentence("Open-weights language models held 22 items.", "S2"), sentence("Both clusters are named on the map.", "S1", "S2")]}])
        second["figure_caption"] = "Decision models reached 4 items in the latest week."
        run, client, _ = self.run_trends([trend_draft("One"), second])
        self.assertEqual(run["review"]["status"], "requested")
        (request,) = review_requests.list_reviews(client, sweep=False)
        self.assertEqual((request["mode"], request["subject"]), ("soft_review", {"type": "batch", "id": run["runId"]}))
        self.assertIn("2 new trend story drafts", request["reason"])
        self.assertEqual(run["review"]["linkedAs"], "proposal")

    def test_a_dry_run_writes_files_stores_and_requests_nothing_but_still_shows_the_check(self) -> None:
        bad = trend_draft("Unsupported")
        bad["dek"] = sentence("No source.")
        run, client, _ = self.run_trends([trend_draft(), bad], dry_run=True)
        self.assertEqual((len(run["drafts"]), len(run["invalid"]), run["ideasCreated"], run["store"]), (1, 1, 0, "dry-run"))
        self.assertEqual(run["review"]["status"], "skipped")
        self.assertEqual(self.filed(client), [])
        self.assertFalse(self.root.exists())
        self.assertFalse([call for call in client.calls if call[0] == "list_records" and call[1] == "ReviewRequest"])

    def test_a_proposal_with_the_same_targets_is_not_filed_again_unless_it_was_declined(self) -> None:
        targets = json.dumps([{"type": "entity", "id": "licence--apache-2-0"}, {"type": "entity", "id": "platform--hugging-face"}])
        earlier = {"id": "prop-" + "b" * 32, "kind": "story_draft", "title": "Different words entirely", "summary": "x", "state": "draft", "targets": targets, "createdAt": "2026-10-20T00:00:00Z"}
        run, client, _ = self.run_trends([trend_draft()], ListingClient(sections=("Analysis",), listed=[earlier]))
        self.assertEqual((run["ideasCreated"], run["duplicates"][0]["reason"]), (0, "same_targets"))
        self.assertEqual(run["duplicates"][0]["sameTargetsAs"], {"kind": "proposal", "id": earlier["id"]})
        declined = {**earlier, "state": "declined"}
        run, _, _ = self.run_trends([trend_draft()], ListingClient(sections=("Analysis",), listed=[declined]))
        self.assertEqual(run["ideasCreated"], 1)

    def test_a_trend_draft_kept_in_the_json_store_blocks_the_same_targets_next_run(self) -> None:
        first, _, _ = self.run_trends([trend_draft()], proposals=False)
        self.assertEqual((first["ideasCreated"], first["store"]), (1, "json"))
        second, _, _ = self.run_trends([trend_draft("Another title for the same pair")], proposals=False)
        self.assertEqual((second["ideasCreated"], second["duplicates"][0]["reason"]), (0, "same_targets"))

    def test_a_draft_that_restates_a_published_story_is_a_near_duplicate(self) -> None:
        story = {"id": "s1", "title": "Hugging Face and Apache-2.0 climb together", "summary": "Both rose in the four weeks to 2026-10-19.", "state": "published", "date": "2026-10-10"}
        run, _, _ = self.run_trends([trend_draft()], stories=[story])
        self.assertEqual((run["ideasCreated"], run["duplicates"][0]["reason"]), (0, "near_duplicate"))

    def test_under_iam_proposals_cannot_be_read_so_dedupe_against_them_is_skipped_and_said_so(self) -> None:
        class Denied(FakeClient):
            def graphql(self, query, variables=None):
                if "listProposals" in query:
                    raise RuntimeError("Not Authorized to access listProposals on type Query")
                return super().graphql(query, variables)

        with mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "iam"}):
            run, client, _ = self.run_trends([trend_draft()], Denied(sections=("Analysis",)))
        self.assertEqual(run["ideasCreated"], 1)
        self.assertIn("cannot be read with IAM", run["proposalDedupe"])
        self.assertEqual(len(self.filed(client)), 1)

    def test_too_few_signals_means_no_model_call(self) -> None:
        self.snapshot = {**self.snapshot, "clusters": [], "index": {**self.snapshot["index"], "entities": self.snapshot["index"]["entities"][:1], "trending": ["platform--hugging-face"]}}
        run, _, model = self.run_trends([trend_draft()])
        self.assertEqual((model.requests, run["ideasCreated"]), ([], 0))
        self.assertIn("at least 2", run["noCall"])

    def test_a_run_over_the_cost_cap_stops_before_the_call(self) -> None:
        with self.assertRaises(trends.RunRefused):
            self.run_trends([trend_draft()], maximum_cost_usd=0.0)

    def test_the_report_lists_kept_drafts_and_the_failures_with_their_sentences(self) -> None:
        bad = trend_draft("Unsupported")
        bad["dek"] = sentence("No source.")
        run, _, _ = self.run_trends([trend_draft(), bad])
        text = trends.render_report(run)
        self.assertIn("Proposed by AI", text)
        self.assertIn("Failed the citation check", text)
        self.assertIn("dek: no_citation", text)
        self.assertNotIn("desk", text.lower())


class CommandTests(unittest.TestCase):
    def run_cli(self, argv, client, model, environment=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(commands, "create_authoring_client", return_value=(client, {})), \
             mock.patch.object(commands.synthesis, "openai_transport", return_value=model), \
             mock.patch("papyrus_content.cli.load_dotenv"), mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", **(environment or {})}), \
             redirect_stdout(out), redirect_stderr(err):
            code = papyrus_cli.main(["--allow-cross-root", "ideas", "trends", *argv])
        return code, out.getvalue() + err.getvalue()

    def test_a_dry_run_prints_the_drafts_and_the_citation_check_without_filing(self) -> None:
        bad = trend_draft("Unsupported")
        bad["dek"] = sentence("No source.")
        with tempfile.TemporaryDirectory() as directory:
            path = write(directory, "snapshot.json", history_entry())
            client = FakeClient(sections=("Analysis",))
            code, output = self.run_cli(["--site", "example-site", "--snapshot", path, "--store", "proposals", "--dry-run", "--out", directory], client, FakeTrendModel([trend_draft(), bad]))
            self.assertEqual(code, 0, output)
            self.assertFalse(Path(directory, "runs").exists())
        self.assertIn("would file 1", output)
        self.assertIn("citation check passed", output)
        self.assertIn("failed\tUnsupported\tcitation_check_failed", output)
        self.assertIn("problem\tdek\tno_citation", output)
        self.assertIn("## Signals cited", output)
        self.assertEqual([row for row in client.proposals if "kind" in row], [])

    def test_a_real_run_files_the_draft_and_reports_the_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write(directory, "snapshot.json", history_entry())
            report = Path(directory) / "report.md"
            client = FakeClient(sections=("Analysis",))
            code, output = self.run_cli(["--site", "example-site", "--snapshot", path, "--store", "proposals", "--max", "2", "--out", directory, "--report", str(report)], client, FakeTrendModel([trend_draft()]))
            self.assertEqual(code, 0, output)
            self.assertTrue(report.read_text().startswith("# Trend story drafts"))
        self.assertIn("filed 1", output)
        self.assertIn("review\trequested\trequested true", output)
        self.assertEqual(len([row for row in client.proposals if "kind" in row]), 1)

    def test_it_needs_a_site_and_a_snapshot(self) -> None:
        code, output = self.run_cli(["--site", "example-site"], FakeClient(), None)
        self.assertEqual(code, 2)
        self.assertIn("--snapshot", output)


if __name__ == "__main__":
    unittest.main()
