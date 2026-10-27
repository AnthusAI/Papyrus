"""Monitor stories: reading the monitored items, ranking by the Cyclotron verdict, drafting one cited story each, the citation check, filing and
idempotence. The model, the pages and the backend are fakes; nothing here reaches the network."""

from __future__ import annotations

import ast
import copy
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ideas_fixtures import CORPUS, NOW, FakeClient, FakeModel, operator_view, reference  # noqa: E402
from papyrus import cli as papyrus_cli  # noqa: E402
from papyrus_content import proposals_commands  # noqa: E402
from papyrus_content.ideas import commands, monitor_stories as stories  # noqa: E402
from papyrus_content.ideas.store import JsonStore, ProposalStore  # noqa: E402

SITE = "example-site"
PAGE = "<html><head><meta name='description' content='Foo is an open tool that checks claims against their sources.'></head><body><p>The tool, released on 2026-10-20, reads a draft, finds each claim and links it to the source page it came from. It is written in Rust and has 42 contributors.</p></body></html>"


def provenance(row, monitor="hn", details=None):
    """The relation that links a monitor's provenance Message to the Reference it delivered."""
    metadata = {"monitorId": monitor, "sourceId": f"{monitor}-1", **({"details": details} if details else {})}
    return {"predicate": "ingestion_rationale", "relationState": "current", "subjectKind": "message", "objectKind": "reference", "objectLineageId": row["lineageId"],
            "importedAt": "2026-10-22T00:00:00Z", "metadata": json.dumps(metadata)}


def decision(row, score=0.9, label="include"):
    return {"predicate": "relevance_decision_is", "relationState": "current", "objectKind": "semanticNode", "objectLineageId": f"semantic-node-relevance-{label}",
            "subjectLineageId": row["lineageId"], "score": score, "confidence": score, "createdAt": "2026-10-22T00:00:00Z",
            "metadata": json.dumps({"label": label, "positiveLabel": "include", "cyclotronId": "example-site-relevance", "decidedAt": "2026-10-22T00:00:00Z"})}


class MonitorClient(FakeClient):
    """A backend with monitored References. ``incoming`` maps a Reference lineage to its provenance relations, ``relations`` to its own (the verdict)."""

    def __init__(self, *args, incoming=None, items=(), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.incoming = incoming or {}
        self.items = list(items)
        self.filed: list[dict] = []

    def list_records(self, model):
        return list(self.items) if model == "Item" else super().list_records(model)

    def list_semantic_relations_by_object_state(self, key):
        self.calls.append(("incoming", key))
        return self.incoming.get(key.split("#")[1], [])

    def graphql(self, query, variables=None):
        if "fileProposal" in query:
            self.filed.append({"id": f"prop-{len(self.filed):032x}", "state": "draft", "createdAt": "2026-10-23T12:00:00Z", **(variables or {})})
            return {"fileProposal": {"status": "ok", "id": self.filed[-1]["id"]}}
        if "listStoryDrafts" in query:
            return {"listStoryDrafts": {"status": "ok", "error": None, "message": None, "drafts": operator_view([{**row, "kind": "story_draft"} for row in self.filed])}}
        return super().graphql(query, variables)


def world(count=4, *, details=None, verdicts=None, monitor="hn", status="pending", **options):
    """``count`` monitored References r1..rN, each judged by ``verdicts[number]`` (a score, a (label, score) pair, or None for no verdict)."""
    rows = [reference(number, status=status, days_ago=number) for number in range(1, count + 1)]
    incoming = {row["lineageId"]: [provenance(row, monitor, (details or {}).get(number))] for number, row in enumerate(rows, start=1)}
    relations = {}
    for number, row in enumerate(rows, start=1):
        verdict = (verdicts or {}).get(number, 0.5)
        if verdict is not None:
            label, score = verdict if isinstance(verdict, tuple) else ("include", verdict)
            relations[row["lineageId"]] = [decision(row, score, label)]
    return rows, MonitorClient(references=rows, incoming=incoming, relations=relations, sections=("Analysis", "Tools"), **options)


SUBJECTS = [("Foo", "claims", "sources"), ("Quill", "quotations", "archives"), ("Marlin", "footnotes", "transcripts"), ("Zephyr", "statistics", "datasets"),
            ("Orchid", "citations", "journals"), ("Basalt", "headlines", "bulletins"), ("Cobalt", "figures", "registries"), ("Juniper", "timelines", "ledgers")]


def good_story(url, headline=None, cites=("I1",), number=1):
    name, thing, place = SUBJECTS[(number - 1) % len(SUBJECTS)]

    def sentence(text):
        return {"text": text, "cites": list(cites)}

    return {
        "headline": sentence(headline or f"{name} checks {thing} against {place}"),
        "dek": sentence(f"{name} links each of the {thing} in a draft to the {place} page it came from."),
        "section": "Tools",
        "paragraphs": [{"sentences": [
            sentence(f"{name} is an open tool that checks {thing} against their {place}."),
            sentence("It was released on 2026-10-20 and has 42 contributors."),
        ]}],
    }


class StoryModel(FakeModel):
    """Answers each request with the story its source URL maps to (the default story otherwise) and records the requests."""

    def __init__(self, by_url=None, default=None, **kwargs) -> None:
        super().__init__([], **kwargs)
        self.by_url = by_url or {}
        self.default = default

    def __call__(self, url, headers, payload):
        self.requests.append(payload)
        source = json.loads(payload["input"])["source"]
        number = int(re.search(r"example(\d+)\.org", source["url"]).group(1))
        story = self.by_url.get(source["url"], self.default or good_story(source["url"], number=number))
        return {"status": "completed", "output_text": json.dumps(story), "usage": self.usage}


def pages(*numbers):
    return lambda url: PAGE if any(f"example{number}.org" in url for number in numbers) else None


def context():
    return {"mission": "Explain how AI systems fail.", "policy": "Prefer primary sources.", "sections": [{"id": "Analysis", "title": "Analysis"}, {"id": "Tools", "title": "Tools"}], "stories": []}


def draft(client, model, *, fetch=None, limit=3, dry_run=False, json_store=None, proposal_store=None, **options):
    return stories.draft_monitor_stories(
        client=client, site=SITE, context=context(), json_store=json_store, transport=model, proposal_store=proposal_store, review_client=client,
        limit=limit, dry_run=dry_run, now=NOW, fetch=fetch or pages(1, 2, 3, 4), **options,
    )


class ReadingTests(unittest.TestCase):
    def test_every_monitor_counts_and_the_monitor_and_details_are_read_from_the_provenance(self) -> None:
        rows, client = world(2, details={1: {"points": 120, "summary": "A Show item."}})
        client.incoming[rows[1]["lineageId"]] = [provenance(rows[1], "huggingface")]
        items, counts = stories.collect_monitored_items(client, site=SITE, since="7d", now=NOW)
        by_id = {item.lineage_id: item for item in items}
        self.assertEqual({item.monitor_id for item in items}, {"hn", "huggingface"})
        self.assertEqual(by_id[rows[0]["lineageId"]].details, {"points": 120, "summary": "A Show item."})
        self.assertEqual(by_id[rows[0]["lineageId"]].verdict["score"], 0.5)
        self.assertEqual(counts["inWindow"], 2)

    def test_a_reference_no_monitor_delivered_is_not_a_monitored_item(self) -> None:
        rows, client = world(2)
        client.incoming[rows[1]["lineageId"]] = []
        items, counts = stories.collect_monitored_items(client, site=SITE, since="7d", now=NOW)
        self.assertEqual([item.lineage_id for item in items], [rows[0]["lineageId"]])
        self.assertEqual(counts["notMonitored"], 1)

    def test_rejected_references_and_ones_outside_the_window_are_not_read(self) -> None:
        rows, client = world(3)
        client.references[0]["curationStatus"] = "rejected"
        client.references[1]["createdAt"] = "2026-09-01T00:00:00Z"
        items, counts = stories.collect_monitored_items(client, site=SITE, since="7d", now=NOW)
        self.assertEqual([item.lineage_id for item in items], [rows[2]["lineageId"]])
        self.assertEqual(counts["inWindow"], 1)

    def test_accepted_references_count_too(self) -> None:
        _, client = world(2, status="accepted")
        items, _ = stories.collect_monitored_items(client, site=SITE, since="7d", now=NOW)
        self.assertEqual(len(items), 2)

    def test_an_item_the_cyclotron_judged_not_relevant_is_left_out(self) -> None:
        rows, client = world(3, verdicts={1: ("exclude", 0.1), 2: 0.8, 3: None})
        items, counts = stories.collect_monitored_items(client, site=SITE, since="7d", now=NOW)
        self.assertEqual(sorted(item.lineage_id for item in items), sorted([rows[1]["lineageId"], rows[2]["lineageId"]]))
        self.assertEqual(counts["judgedNotRelevant"], 1)

    def test_a_decision_names_its_own_positive_label(self) -> None:
        rows, client = world(1, verdicts={1: ("relevant", 0.7)})
        client.relations[rows[0]["lineageId"]][0]["metadata"] = json.dumps({"label": "relevant", "positiveLabel": "relevant"})
        items, _ = stories.collect_monitored_items(client, site=SITE, since="7d", now=NOW)
        self.assertTrue(items[0].relevant)


class RankingTests(unittest.TestCase):
    def ranked(self, **options):
        rows, client = world(**options)
        items, _ = stories.collect_monitored_items(client, site=SITE, since="30d", now=NOW)
        by_lineage = {row["lineageId"]: number for number, row in enumerate(rows, start=1)}
        return [by_lineage[item.lineage_id] for item in stories.rank(items)]

    def test_the_cyclotron_score_orders_the_items(self) -> None:
        self.assertEqual(self.ranked(count=4, verdicts={1: 0.4, 2: 0.95, 3: 0.7, 4: 0.8}), [2, 4, 3, 1])

    def test_an_item_the_cyclotron_scored_comes_before_one_it_did_not_judge(self) -> None:
        self.assertEqual(self.ranked(count=3, verdicts={1: None, 2: 0.2, 3: None}), [2, 1, 3])

    def test_the_sources_own_numbers_only_break_a_tie_in_the_score(self) -> None:
        details = {1: {"likes": 5, "downloads": 900}, 2: {"likes": 50}, 3: {"likes": 5, "downloads": 9000}, 4: {"likes": 9999}}
        self.assertEqual(self.ranked(count=4, details=details, verdicts={1: 0.8, 2: 0.8, 3: 0.8, 4: 0.7}), [2, 3, 1, 4])

    def test_the_newest_arrival_breaks_the_last_tie_and_the_order_is_stable(self) -> None:
        self.assertEqual(self.ranked(count=3, verdicts={1: 0.8, 2: 0.8, 3: 0.8}), [1, 2, 3])

    def test_no_source_is_named_in_the_code(self) -> None:
        tree = ast.parse(Path(stories.__file__).read_text(encoding="utf-8"))
        docstrings = {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
        words = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name)] + [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
        words += [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]
        text = " ".join(words).lower()
        for name in ("huggingface", "hugging face", "hacker news", "arxiv", "email"):
            self.assertNotIn(name, text, name)
        self.assertNotRegex(text, r"\bhn\b")


class DraftingTests(unittest.TestCase):
    def test_the_top_items_each_get_one_model_call_and_one_cited_draft(self) -> None:
        rows, client = world(4, verdicts={1: 0.5, 2: 0.9, 3: 0.7, 4: 0.6})
        model = StoryModel()
        run = draft(client, model, limit=2)
        self.assertEqual(len(model.requests), 2)
        self.assertEqual([entry["referenceId"] for entry in run["ranking"][:2]], [rows[1]["id"], rows[2]["id"]])
        self.assertEqual(len(run["drafts"]), 2)
        for record in run["drafts"]:
            self.assertEqual(record["kind"], "story_draft")
            self.assertEqual(record["citationCheck"]["status"], "passed")
            self.assertIn(record["citedItems"][0]["url"], record["body"])
            self.assertEqual(record["monitorId"], "hn")
            self.assertIn("hn monitor", record["body"])
            self.assertEqual(record["evidence"]["source"], f"hn monitor: {record['citedItems'][0]['url']}")

    def test_the_model_is_shown_the_source_and_the_page_text_and_not_the_verdict(self) -> None:
        rows, client = world(1, details={1: {"points": 120, "author": "pat", "summary": "A Show item."}})
        model = StoryModel()
        draft(client, model)
        shown = json.loads(model.requests[0]["input"])
        self.assertEqual(model.requests[0]["model"], "gpt-6-luna")
        source = shown["source"]
        self.assertEqual((source["handle"], source["url"], source["monitor"], source["summary"]), ("I1", rows[0]["sourceUri"], "hn", "A Show item."))
        self.assertEqual(source["facts"], {"points": 120, "author": "pat"})
        self.assertIn("reads a draft", source["page_text"])
        self.assertEqual(shown["allowed_sections"], ["Analysis", "Tools"])
        self.assertNotIn("0.5", json.dumps(shown))

    def test_a_page_that_cannot_be_read_leaves_the_story_to_the_stored_details(self) -> None:
        _, client = world(1, details={1: {"summary": "Foo is an open tool that checks claims against their sources.", "contributors": 42, "released": "2026-10-20"}})

        def broken(url):
            raise OSError("down")

        model = StoryModel()
        run = draft(client, model, fetch=broken)
        shown = json.loads(model.requests[0]["input"])["source"]
        self.assertNotIn("page_text", shown)
        self.assertEqual(run["drafts"][0]["sourceText"], "stored details")

    def test_an_item_with_only_a_title_is_skipped_without_a_model_call(self) -> None:
        _, client = world(2)
        model = StoryModel()
        run = draft(client, model, fetch=pages(2))
        self.assertEqual(len(model.requests), 1)
        self.assertEqual([entry["reason"] for entry in run["skipped"]], ["no_source_text"])
        self.assertEqual(len(run["drafts"]), 1)

    def test_a_draft_that_fails_the_check_is_replaced_by_the_next_item_and_never_filed(self) -> None:
        rows, client = world(3, verdicts={1: 0.9, 2: 0.8, 3: 0.7})
        bad = good_story("", cites=())
        model = StoryModel(by_url={rows[0]["sourceUri"]: bad})
        store = ProposalStore(client)
        run = draft(client, model, limit=1, proposal_store=store)
        self.assertEqual(len(model.requests), 2)
        self.assertEqual([entry["reason"] for entry in run["invalid"]], ["citation_check_failed"])
        self.assertEqual(run["invalid"][0]["referenceId"], rows[0]["id"])
        self.assertEqual(len(client.filed), 1)
        self.assertEqual(json.loads(client.filed[0]["targets"]), [{"type": "entity", "id": f"reference:{rows[1]['lineageId']}"}])

    def test_the_attempts_are_bounded_so_a_run_never_spends_without_end(self) -> None:
        _, client = world(8)
        model = StoryModel(default=good_story("", cites=()))
        run = draft(client, model, limit=2, fetch=pages(*range(1, 9)))
        self.assertEqual(len(model.requests), 4)
        self.assertEqual((run["attempted"], len(run["drafts"])), (4, 0))

    def test_every_kind_of_unsupported_sentence_fails_the_check(self) -> None:
        cases = {
            "no_citation": lambda s: s["dek"].update(cites=[]),
            "unknown_signal:I9": lambda s: s["dek"].update(cites=["I9"]),
            "number_not_in_cited_signals:7": lambda s: s["paragraphs"][0]["sentences"][0].update(text="Foo has 7 users."),
            "number_not_in_cited_signals:2026-01-01": lambda s: s["paragraphs"][0]["sentences"][0].update(text="Foo shipped on 2026-01-01."),
            "banned_word": lambda s: s["headline"].update(text="Foo joins the news desk"),
            "several_sentences_in_one_entry": lambda s: s["dek"].update(text="Foo is new. It checks claims."),
            "unknown_section": lambda s: s.update(section="Sports"),
            "fewer_than_two_body_sentences": lambda s: s["paragraphs"][0]["sentences"].pop(),
        }
        for reason, break_it in cases.items():
            with self.subTest(reason):
                _, client = world(1)
                bad = copy.deepcopy(good_story(""))
                break_it(bad)
                run = draft(client, StoryModel(default=bad))
                problems = [problem["reason"] for problem in run["invalid"][0]["citationCheck"]["problems"]]
                self.assertTrue(any(problem.startswith(reason.split(":")[0]) for problem in problems), problems)
                self.assertEqual(run["drafts"], [])

    def test_a_number_that_is_in_the_page_or_the_title_is_grounded(self) -> None:
        _, client = world(1)
        client.references[0]["title"] = "Foo 2 checks claims"
        good = good_story("")
        good["headline"]["text"] = "Foo 2 checks claims"
        run = draft(client, StoryModel(default=good))
        self.assertEqual(len(run["drafts"]), 1)

    def test_a_near_duplicate_of_an_existing_story_is_dropped(self) -> None:
        _, client = world(1)
        ctx = context()
        ctx["stories"] = [{"id": "s1", "title": "Foo checks claims against sources", "summary": "Foo links each of the claims in a draft to the sources page it came from."}]
        run = stories.draft_monitor_stories(client=client, site=SITE, context=ctx, json_store=None, transport=StoryModel(), now=NOW, fetch=pages(1))
        self.assertEqual(run["drafts"], [])
        self.assertEqual(run["duplicates"][0]["reason"], "near_duplicate")

    def test_the_cost_cap_stops_the_run_before_the_next_call(self) -> None:
        _, client = world(3)
        model = StoryModel()
        run = draft(client, model, maximum_cost_usd=0.0000001)
        self.assertEqual(model.requests, [])
        self.assertIn("--max-cost-usd", run["stoppedForCost"])

    def test_a_model_error_is_recorded_and_the_next_item_is_tried(self) -> None:
        _, client = world(2)
        calls = []

        def model(url, headers, payload):
            calls.append(payload)
            if len(calls) == 1:
                from papyrus_content.ideas import synthesis

                raise synthesis.SynthesisError("The model service answered 500.")
            return StoryModel()(url, headers, payload)

        run = draft(client, model, limit=1)
        self.assertEqual([entry["reason"] for entry in run["invalid"]], ["model_error"])
        self.assertEqual(len(run["drafts"]), 1)

    def test_the_usage_of_every_call_is_recorded_for_the_ledger(self) -> None:
        _, client = world(2)
        run = draft(client, StoryModel(input_tokens=2000, output_tokens=300))
        self.assertEqual(run["modelCalls"], [{"model": "gpt-6-luna", "promptTokens": 2000, "completionTokens": 300, "cachedTokens": 0}] * 2)
        self.assertEqual((run["usage"]["calls"], run["usage"]["inputTokens"], run["usage"]["outputTokens"]), (2, 4000, 600))


class FilingTests(unittest.TestCase):
    def test_a_story_is_filed_as_a_story_draft_proposal_naming_the_monitor(self) -> None:
        rows, client = world(1, monitor="huggingface")
        run = draft(client, StoryModel(), proposal_store=ProposalStore(client))
        filed = client.filed[0]
        self.assertEqual(filed["kind"], "story_draft")
        self.assertEqual(filed["title"], "Foo checks claims against sources")
        self.assertEqual(json.loads(filed["targets"]), [{"type": "entity", "id": f"reference:{rows[0]['lineageId']}"}])
        self.assertEqual(json.loads(filed["evidence"]), {"signals": 1, "source": f"huggingface monitor: {rows[0]['sourceUri']}"})
        self.assertIn("## Source", filed["body"])
        self.assertIn(rows[0]["sourceUri"], filed["body"])
        self.assertEqual(run["drafts"][0]["proposalId"], filed["id"])
        self.assertEqual(run["review"]["status"], "requested")

    def test_a_second_run_never_drafts_the_same_reference_again(self) -> None:
        _, client = world(2)
        store = ProposalStore(client)
        with mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "iam"}):
            first = draft(client, StoryModel(), proposal_store=store)
            model = StoryModel()
            second = draft(client, model, proposal_store=store)
        self.assertEqual(len(first["drafts"]), 2)
        self.assertEqual(model.requests, [])
        self.assertEqual((second["inputs"]["alreadyDrafted"], second["drafts"]), (2, []))
        self.assertEqual(len(client.filed), 2)

    def test_a_declined_draft_is_not_drafted_again(self) -> None:
        _, client = world(1)
        store = ProposalStore(client)
        with mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "iam"}):
            draft(client, StoryModel(), proposal_store=store)
            client.filed[0]["state"] = "declined"
            model = StoryModel()
            draft(client, model, proposal_store=store)
        self.assertEqual(model.requests, [])

    def test_a_json_store_run_is_idempotent_too(self) -> None:
        _, client = world(1)
        with tempfile.TemporaryDirectory() as directory:
            first = draft(client, StoryModel(), json_store=JsonStore(Path(directory)))
            model = StoryModel()
            second = draft(client, model, json_store=JsonStore(Path(directory)))
            self.assertEqual(len(list(Path(directory, "ideas").glob("*.json"))), 1)
        self.assertEqual(len(first["drafts"]), 1)
        self.assertEqual((model.requests, second["drafts"]), ([], []))

    def test_a_promoted_reference_is_left_alone(self) -> None:
        rows, client = world(2)
        client.items = [{"id": "item-1", "metadata": {"frontMatterYaml": f"monitorRecord:\n  referenceId: {rows[0]['id']}\n"}}]
        model = StoryModel()
        run = draft(client, model)
        self.assertEqual(run["inputs"]["promoted"], 1)
        self.assertEqual(len(model.requests), 1)
        self.assertNotIn(rows[0]["id"], [entry["referenceId"] for entry in run["ranking"]])

    def test_a_dry_run_asks_the_model_but_files_stores_and_requests_nothing(self) -> None:
        _, client = world(1)
        with tempfile.TemporaryDirectory() as directory:
            model = StoryModel()
            run = draft(client, model, dry_run=True, json_store=JsonStore(Path(directory)), proposal_store=ProposalStore(client))
            self.assertFalse(Path(directory, "ideas").exists())
            self.assertFalse(Path(directory, "runs").exists())
        self.assertEqual(len(model.requests), 1)
        self.assertEqual((len(run["drafts"]), run["ideasCreated"], run["review"]["requested"]), (1, 0, False))
        self.assertEqual((client.filed, client.reviews), ([], {}))

    def test_nothing_to_write_makes_no_call_and_no_review(self) -> None:
        client = MonitorClient(sections=("Analysis",))
        model = StoryModel()
        run = draft(client, model)
        self.assertEqual((model.requests, run["drafts"], run["review"]["status"]), ([], [], "none"))


class CommandTests(unittest.TestCase):
    def run_cli(self, argv, client, model, environment=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(commands, "create_authoring_client", return_value=(client, {})), \
             mock.patch.object(commands.synthesis, "openai_transport", return_value=model), \
             mock.patch.object(commands.monitor_stories, "fetch_html", side_effect=lambda url: PAGE), \
             mock.patch("papyrus_content.cli.load_dotenv"), mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", **(environment or {})}), \
             redirect_stdout(out), redirect_stderr(err):
            code = papyrus_cli.main(["--allow-cross-root", "ideas", "monitor-stories", *argv])
        return code, out.getvalue() + err.getvalue()

    def test_a_dry_run_prints_the_ranked_drafts_without_filing(self) -> None:
        _, client = world(3)
        with tempfile.TemporaryDirectory() as directory:
            code, output = self.run_cli(["--site", SITE, "--since", "3650d", "--limit", "2", "--store", "proposals", "--dry-run", "--out", directory], client, StoryModel())
            self.assertFalse(Path(directory, "runs").exists())
        self.assertEqual(code, 0, output)
        self.assertIn("would file 2", output)
        self.assertIn("candidates 3", output)
        self.assertIn("## Source", output)
        self.assertEqual(client.filed, [])

    def test_a_real_run_files_the_stories_and_writes_the_report(self) -> None:
        _, client = world(3)
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.md"
            code, output = self.run_cli(["--site", SITE, "--since", "3650d", "--limit", "1", "--store", "proposals", "--out", directory, "--report", str(report)], client, StoryModel())
            self.assertEqual(code, 0, output)
            self.assertTrue(report.read_text().startswith("# Monitor story drafts"))
        self.assertIn("filed 1", output)
        self.assertIn("review\trequested\trequested true", output)
        self.assertEqual(len(client.filed), 1)

    def test_json_output_carries_the_run(self) -> None:
        _, client = world(1)
        with tempfile.TemporaryDirectory() as directory:
            code, output = self.run_cli(["--site", SITE, "--since", "3650d", "--dry-run", "--json", "--out", directory], client, StoryModel())
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output)["run"]["kind"], "monitor-stories-run")

    def test_a_bad_window_and_a_missing_site_are_operator_errors(self) -> None:
        _, client = world(1)
        code, output = self.run_cli(["--site", SITE, "--since", "soon"], client, StoryModel())
        self.assertEqual(code, 2)
        self.assertIn("--since", output)
        code, output = self.run_cli([], client, StoryModel())
        self.assertEqual(code, 2)
        self.assertIn("--site", output)

    def test_it_needs_the_openai_key(self) -> None:
        _, client = world(1)
        with mock.patch.object(commands, "resolve_openai_api_key", return_value=None):
            code, output = self.run_cli(["--site", SITE, "--since", "3650d", "--dry-run"], client, StoryModel())
        self.assertEqual(code, 2)
        self.assertIn("OPENAI_API_KEY", output)


if __name__ == "__main__":
    unittest.main()
