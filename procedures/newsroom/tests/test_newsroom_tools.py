import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_newsroom import newsroom as papyrus_newsroom
from papyrus_newsroom import coverage_theme as papyrus_coverage_theme
from papyrus_newsroom import reference_curation_signals
from papyrus_newsroom import semantic as papyrus_semantic
from papyrus_newsroom import tactus_runtime
from papyrus_knowledge_query.uris import parse_papyrus_uri


class NewsroomToolTests(unittest.TestCase):
    def test_wrapper_shim_exports_newsroom_functions(self):
        import importlib.util

        module_path = REPO_ROOT / "procedures" / "newsroom" / "tools" / "papyrus_newsroom.py"
        spec = importlib.util.spec_from_file_location("papyrus_newsroom_wrapper", module_path)
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)

        self.assertTrue(callable(wrapper.papyrus_build_assignment_agent_context))
        self.assertTrue(callable(wrapper.main))

    def test_execute_tactus_exposes_single_papyrus_host_module(self):
        result = tactus_runtime.execute_tactus(
            'local api = api_list{}; local docs = docs_list{ namespace = "newsroom" }; return { api = api, docs = docs }'
        )

        self.assertTrue(result["ok"])
        resources = result["value"]["api"]["resources"]
        self.assertIn("Assignment", resources)
        self.assertIn("Reference", resources)
        self.assertIn("NewsroomSection", resources)
        self.assertIn("create", resources["Assignment"])
        self.assertIn("update", resources["Assignment"])
        self.assertIn("create", resources["Reference"])
        self.assertIn("docs", result["value"]["api"])
        self.assertEqual(
            result["api_calls"],
            ["papyrus.api.list", "papyrus.docs.list"],
        )

    def test_parse_papyrus_uri_supports_agent_visible_kinds(self):
        cases = {
            "papyrus://reference/reference-1": ("reference", "reference-1"),
            "papyrus://item/item-1": ("item", "item-1"),
            "papyrus://category/category-1": ("category", "category-1"),
            "papyrus://semanticNode/node-1": ("semanticNode", "node-1"),
            "papyrus://message/message-1": ("message", "message-1"),
            "papyrus://assignment/assignment-1": ("assignment", "assignment-1"),
        }
        for uri, expected in cases.items():
            with self.subTest(uri=uri):
                parsed = parse_papyrus_uri(uri)
                self.assertEqual((parsed["kind"], parsed["id"]), expected)
                self.assertEqual(parsed["lineageId"], expected[1])
                self.assertEqual(parsed["objectUri"], uri)

    def test_parse_papyrus_uri_rejects_invalid_uri(self):
        for uri in ["https://reference/reference-1", "papyrus://unknown/object-1", "papyrus://reference/"]:
            with self.subTest(uri=uri):
                with self.assertRaises(ValueError):
                    parse_papyrus_uri(uri)

    def test_execute_tactus_composes_dry_run_plan_code(self):
        result = tactus_runtime.execute_tactus(
            """
local assignment = {
  id = "assignment-123",
  type = "assignment",
  status = "dispatched",
  typeStatus = "assignment#dispatched",
  section = "Research",
  title = "Research Assignment",
  editorial = { newsroom = { assignment = { brief = "Research the topic." } } },
}
local research = {
  summary = "The topic has enough evidence for a focused brief.",
  corpus_key = "AI-ML-research",
  evidence_item_ids = { "research-001" },
  recommended_angle = "Use a workflow angle.",
}
return plan_research_update{ assignment_item = assignment, research = research }
"""
        )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["value"]["lifecycle"], "assignment-research")
        self.assertEqual(result["api_calls"], ["papyrus.plan.research_update"])

    def test_build_assignment_agent_context_assembles_live_desk_context(self):
        assignment_context = {
            "assignment": {
                "id": "assignment-live-123",
                "assignmentTypeKey": "research.edition-candidate",
                "queueKey": "edition:edition-2026-05-16:desk:topic-scaling:lane:analysis",
                "queueStatusKey": "edition:edition-2026-05-16:desk:topic-scaling:lane:analysis#open",
                "status": "open",
                "title": "Analysis candidate: Scaling Agents",
                "brief": "Compare how agentic systems are changing scaling workflows.",
                "categorySetId": "category-set-1",
                "metadata": {
                    "editionDate": "2026-05-16",
                    "deskCategoryKey": "topic.scaling",
                    "deskCategoryLineageId": "category-topic-scaling",
                    "focusCategoryKey": "topic.scaling-agents",
                    "focusCategoryLineageId": "category-topic-scaling-agents",
                    "focusCategoryTitle": "Scaling Agents",
                    "contextProfile": "analysis",
                    "contextTokenBudget": 6000,
                    "contextSources": ["doctrine", "focus-category", "desk-memory", "fresh-evidence"],
                    "referenceLineageIds": ["reference-1"],
                },
            },
            "doctrine": [
                {"scope": "publication", "kind": "mission", "label": "Editorial Mission", "body": ["Study systems as operational systems."]},
                {"scope": "desk", "kind": "policy", "label": "Scaling Desk Policy", "body": ["Prefer concrete operational evidence."]},
            ],
            "targets": [],
            "events": [],
        }
        categories = [
            {
                "id": "category-topic-scaling-v1",
                "lineageId": "category-topic-scaling",
                "categoryKey": "topic.scaling",
                "displayName": "Scaling",
                "depth": 0,
                "categorySetId": "category-set-1",
                "versionState": "current",
                "status": "accepted",
            },
            {
                "id": "category-topic-scaling-agents-v1",
                "lineageId": "category-topic-scaling-agents",
                "categoryKey": "topic.scaling-agents",
                "displayName": "Scaling Agents",
                "shortTitle": "Scaling Agents",
                "parentCategoryKey": "topic.scaling",
                "depth": 1,
                "categorySetId": "category-set-1",
                "versionState": "current",
                "status": "accepted",
            },
            {
                "id": "category-topic-foreign-v1",
                "lineageId": "category-topic-foreign",
                "categoryKey": "topic.foreign",
                "displayName": "Foreign Desk",
                "depth": 0,
                "categorySetId": "category-set-1",
                "versionState": "current",
                "status": "accepted",
            },
        ]
        assignments = [
            {
                "id": "assignment-match-1",
                "title": "Desk assignment",
                "brief": "Relevant desk memory.",
                "status": "completed",
                "updatedAt": "2026-05-15T12:00:00Z",
                "metadata": {
                    "deskCategoryKey": "topic.scaling",
                    "focusCategoryKey": "topic.scaling-agents",
                },
            },
            {
                "id": "assignment-foreign-1",
                "title": "Foreign Desk",
                "brief": "Should not leak into context.",
                "status": "open",
                "updatedAt": "2026-05-15T11:00:00Z",
                "metadata": {
                    "deskCategoryKey": "topic.foreign",
                    "focusCategoryKey": "topic.foreign",
                },
            },
        ]
        published_items = [
            {
                "id": "item-1",
                "headline": "Scaling Agents Review",
                "section": "topic.scaling",
                "publishedAt": "2026-05-14T12:00:00Z",
                "editorial": {"newsroom": {"draft": {"deskCategoryKey": "topic.scaling"}}},
            },
            {
                "id": "item-foreign",
                "headline": "Foreign Desk Review",
                "section": "topic.foreign",
                "publishedAt": "2026-05-14T11:00:00Z",
                "editorial": {"newsroom": {"draft": {"deskCategoryKey": "topic.foreign"}}},
            },
        ]

        class FakeSemanticClient:
            def references_for_category(self, category_lineage_id):
                if category_lineage_id == "category-topic-scaling-agents":
                    return {
                        "relations": [
                            {"subjectId": "reference-1-v1", "subjectLineageId": "reference-1"},
                            {"subjectId": "reference-2-v1", "subjectLineageId": "reference-2"},
                        ]
                    }
                return {"relations": []}

            def get_reference(self, reference_id):
                if reference_id == "reference-2-v1":
                    return {
                        "reference": {
                            "id": reference_id,
                            "lineageId": "reference-2",
                            "versionState": "current",
                            "curationStatus": "rejected",
                            "title": "Rejected Scope Memo",
                            "sourceUri": "https://example.com/rejected",
                            "sourcePublishedAt": "2026-05-13T12:00:00Z",
                        }
                    }
                accepted_ref = {
                    "id": reference_id,
                    "lineageId": "reference-1",
                    "versionState": "current",
                    "curationStatus": "accepted",
                    "title": "Scaling Agent Memo",
                    "sourceUri": "https://example.com/scaling-agent-memo",
                    "sourcePublishedAt": "2026-05-13T12:00:00Z",
                }
                return {"reference": accepted_ref}

            def list_reference_messages(self, reference_lineage_id):
                if reference_lineage_id != "reference-1":
                    return {"messages": []}
                return {
                    "messages": [
                        {
                            "id": "message-1",
                            "summary": "Desk note",
                            "body": "Operational evidence remains stronger than broad claims.",
                            "createdAt": "2026-05-13T13:00:00Z",
                        }
                    ]
                }

        def fake_compaction(*, blocks, profile_key, max_tokens):
            included = blocks[:6]
            return {
                "included_blocks": included,
                "dropped_blocks": blocks[6:],
                "section_token_counts": {"doctrine": 120, "taxonomy": 90, "desk_memory": 140, "fresh_evidence": 80},
                "text": "\n\n".join(block["text"] for block in included),
                "total_tokens": 430,
                "total_characters": 1800,
            }

        with mock.patch.object(papyrus_newsroom, "papyrus_get_assignment_context", return_value={"assignment_context": assignment_context}), \
             mock.patch.object(papyrus_newsroom, "_list_categories", return_value=categories), \
             mock.patch.object(papyrus_newsroom, "_list_category_keywords", return_value=[{"keyword": "scaling agents", "source": "accepted-category-set", "rank": 1}]), \
             mock.patch.object(papyrus_newsroom, "_list_assignments", return_value=assignments), \
             mock.patch.object(papyrus_newsroom, "_assignment_events_for_assignments", return_value=[{"id": "event-1", "assignmentId": "assignment-match-1", "eventType": "completed", "createdAt": "2026-05-15T13:00:00Z"}]), \
             mock.patch.object(papyrus_newsroom, "_recent_published_items", return_value=published_items), \
             mock.patch.object(papyrus_newsroom, "_semantic_client", return_value=FakeSemanticClient()), \
             mock.patch.object(papyrus_newsroom, "_build_biblicus_block_context_pack", side_effect=fake_compaction):
            result = papyrus_newsroom.papyrus_build_assignment_agent_context("assignment-live-123")

        context = result["assignment_agent_context"]
        self.assertEqual(context["deskCategoryKey"], "topic.scaling")
        self.assertEqual(context["focusCategoryKey"], "topic.scaling-agents")
        self.assertEqual(context["contextProfile"], "analysis")
        self.assertEqual(context["contextTokenBudget"], 6000)
        self.assertEqual(context["contextSources"], ["doctrine", "focus-category", "desk-memory", "fresh-evidence"])
        self.assertEqual(context["totalTokens"], 430)
        self.assertIn("Publication Doctrine", context["text"])
        self.assertIn("Desk Doctrine", context["text"])
        self.assertIn("Desk: Scaling", "\n".join(block["text"] for block in context["blocks"]))
        self.assertIn("Focus: Scaling Agents", "\n".join(block["text"] for block in context["blocks"]))
        self.assertIn("Scaling Agent Memo", "\n".join(block["text"] for block in context["blocks"]))
        self.assertNotIn("Rejected Scope Memo", "\n".join(block["text"] for block in context["blocks"]))
        self.assertNotIn("Foreign Desk", context["text"])

    def test_assignment_context_includes_edition_and_same_section_forum_only(self):
        assignment_context = {
            "assignment": {
                "id": "assignment-reporting-001",
                "assignmentTypeKey": "reporting.edition-candidate",
                "status": "open",
                "title": "Reporting candidate",
                "sectionKey": "culture",
                "metadata": {
                    "editionId": "edition-2026-06-05-v1",
                    "sectionKey": "culture",
                    "contextProfile": "reporting",
                },
            },
            "doctrine": [],
            "targets": [],
            "events": [],
        }
        edition_thread = {
            "id": "message-thread-edition-forum-edition-2026-06-05-v1",
            "threadKind": "edition_forum",
            "title": "Edition Forum",
            "status": "active",
            "messages": [{"id": "message-edition-1", "summary": "Edition kickoff", "authorLabel": "editor", "createdAt": "2026-06-01T10:00:00Z"}],
        }
        culture_thread = {
            "id": "message-thread-section-forum-culture",
            "threadKind": "section_forum",
            "title": "Section Forum: Culture",
            "status": "active",
            "primaryAnchorId": "culture",
            "metadata": {"sectionKey": "culture"},
            "messages": [{"id": "message-culture-1", "summary": "Culture steering note", "authorLabel": "human", "createdAt": "2026-06-01T10:10:00Z"}],
        }
        business_thread = {
            "id": "message-thread-section-forum-business",
            "threadKind": "section_forum",
            "title": "Section Forum: Business",
            "status": "active",
            "primaryAnchorId": "business",
            "metadata": {"sectionKey": "business"},
            "messages": [{"id": "message-business-1", "summary": "Business note", "authorLabel": "human", "createdAt": "2026-06-01T10:20:00Z"}],
        }

        class FakeSemanticClient:
            def references_for_category(self, category_lineage_id):
                return {"relations": []}

            def get_reference(self, reference_id):
                return {"reference": {}}

            def list_reference_messages(self, reference_lineage_id):
                return {"messages": []}

        def fake_forum_threads(kind, edition_id, *, status="", limit=200):
            if kind == "edition_forum":
                return [edition_thread]
            if kind == "section_forum":
                return [culture_thread, business_thread]
            return []

        def fake_messages(thread_id, *, limit=400):
            mapping = {
                edition_thread["id"]: edition_thread["messages"],
                culture_thread["id"]: culture_thread["messages"],
                business_thread["id"]: business_thread["messages"],
            }
            return mapping.get(thread_id, [])

        def fake_compaction(*, blocks, profile_key, max_tokens):
            return {
                "included_blocks": blocks,
                "dropped_blocks": [],
                "section_token_counts": {},
                "text": "\n\n".join(block["text"] for block in blocks),
                "total_tokens": 100,
                "total_characters": 500,
            }

        with mock.patch.object(papyrus_newsroom, "papyrus_get_assignment_context", return_value={"assignment_context": assignment_context}), \
             mock.patch.object(papyrus_newsroom, "_list_categories", return_value=[]), \
             mock.patch.object(papyrus_newsroom, "_list_category_keywords", return_value=[]), \
             mock.patch.object(papyrus_newsroom, "_list_assignments", return_value=[]), \
             mock.patch.object(papyrus_newsroom, "_assignment_events_for_assignments", return_value=[]), \
             mock.patch.object(papyrus_newsroom, "_recent_published_items", return_value=[]), \
             mock.patch.object(papyrus_newsroom, "_semantic_client", return_value=FakeSemanticClient()), \
             mock.patch.object(papyrus_newsroom, "_forum_threads_by_kind_and_edition", side_effect=fake_forum_threads), \
             mock.patch.object(papyrus_newsroom, "_list_messages_by_thread_id", side_effect=fake_messages), \
             mock.patch.object(papyrus_newsroom, "_build_biblicus_block_context_pack", side_effect=fake_compaction):
            result = papyrus_newsroom.papyrus_build_assignment_agent_context("assignment-reporting-001")

        context = result["assignment_agent_context"]
        self.assertEqual([message["id"] for message in context["editionForumMessages"]], ["message-edition-1"])
        self.assertEqual(len(context["sectionForumThreads"]), 1)
        self.assertEqual(context["sectionForumThreads"][0]["id"], "message-thread-section-forum-culture")
        combined = "\n".join(block["text"] for block in context["blocks"])
        self.assertIn("Edition Forum: Edition Forum", combined)
        self.assertIn("Section Forum: culture", combined)
        self.assertNotIn("Business note", combined)

    def test_create_section_forum_thread_includes_section_lineage_metadata(self):
        captured: dict[str, dict[str, object]] = {}

        def fake_graphql(query: str, variables: dict[str, object]):
            if "createMessageThread" in query:
                captured["input"] = variables["input"]  # type: ignore[index]
                return {"createMessageThread": variables["input"]}
            return {}

        with mock.patch.object(papyrus_newsroom, "_graphql", side_effect=fake_graphql):
            result = papyrus_newsroom.papyrus_create_section_forum_thread(
                edition_id="edition-2026-06-05-v1",
                section_id="culture",
                section_key="culture",
                section_title="Culture",
                title="Culture planning notes",
                actor_label="editor",
            )

        thread = result["thread"]
        self.assertEqual(thread["threadKind"], "section_forum")
        self.assertEqual(thread["primaryAnchorKind"], "newsroom_section")
        self.assertEqual(thread["primaryAnchorId"], "culture")
        self.assertEqual(thread["primaryAnchorLineageId"], "edition-2026-06-05-v1")
        metadata = thread["metadata"]
        self.assertEqual(metadata["editionId"], "edition-2026-06-05-v1")
        self.assertEqual(metadata["sectionId"], "culture")
        self.assertEqual(metadata["sectionKey"], "culture")
        self.assertEqual(metadata["sectionTitle"], "Culture")
        self.assertIn("input", captured)
        self.assertEqual(captured["input"]["primaryAnchorKind"], "newsroom_section")

    def test_assignment_plan_uses_assignment_type(self):
        plan = papyrus_newsroom.build_assignment_record_plan(
            edition_id="edition-1",
            corpus_key="AI-ML-research",
            generated_at="2026-05-16T12:00:00Z",
            assignment_json=json.dumps(
                {
                    "title": "AI Agents Enter the Lab",
                    "brief": "Explain how agentic systems are changing research workflows.",
                    "angle": "Focus on practical scientific workflow changes.",
                    "research_track_key": "automated-publication-systems",
                    "research_lens": "agent-workflow",
                    "target_system_type": "research newsroom",
                    "category_key": "automated-scientific-discovery",
                    "evidence_item_ids": ["research-001"],
                    "recent_article_notes": ["Avoid yesterday's benchmark roundup."],
                }
            ),
        )

        item = plan["item"]
        self.assertTrue(plan["dryRun"])
        self.assertEqual(plan["lifecycle"], "assignment-dispatch")
        self.assertEqual(item["type"], "assignment")
        self.assertEqual(item["status"], "dispatched")
        self.assertEqual(item["typeStatus"], "assignment#dispatched")
        self.assertEqual(item["lineageId"], item["id"])
        self.assertEqual(item["versionNumber"], 1)
        self.assertEqual(item["versionState"], "current")
        self.assertRegex(item["contentHash"], r"^sha256:[a-f0-9]{64}$")
        self.assertEqual(item["body"], [])
        self.assertIsNone(item["publishedAt"])
        self.assertEqual(plan["editionItem"]["editionId"], "edition-1")
        self.assertEqual(plan["editionItem"]["editionLineageId"], "edition-1")
        self.assertEqual(plan["editionItem"]["itemLineageId"], item["lineageId"])
        self.assertEqual(plan["editionItem"]["placementKey"], "assignment:ai-agents-enter-the-lab")
        assignment = item["editorial"]["newsroom"]["assignment"]
        self.assertEqual(assignment["corpusKey"], "AI-ML-research")
        self.assertEqual(assignment["categoryKey"], "automated-scientific-discovery")
        self.assertEqual(assignment["evidenceItemIds"], ["research-001"])
        self.assertEqual(assignment["researchTrackKey"], "automated-publication-systems")
        self.assertEqual(assignment["researchLens"], "agent-workflow")
        self.assertEqual(assignment["targetSystemType"], "research newsroom")
        self.assertIn("execution traces or logs", assignment["expectedEvidenceClasses"])
        self.assertIn("Where does the system branch, retry, pause, or escalate to a human?", assignment["comparisonQuestions"])
        self.assertEqual(assignment["evidenceRubric"][0]["key"], "autonomy-scope")
        self.assertEqual(assignment["downstreamReporter"]["procedure"], "procedures/newsroom/reporter.tac")
        evidence_relation = next(record for record in plan["records"] if record["modelName"] == "SemanticRelation")
        self.assertEqual(evidence_relation["input"]["predicate"], "uses_evidence")
        self.assertEqual(evidence_relation["input"]["subjectId"], item["id"])
        self.assertEqual(evidence_relation["input"]["objectId"], "reference-knowledge-corpus-ai-ml-research-research-001-v1")

    def test_track_assignment_requires_target_system_type(self):
        with self.assertRaisesRegex(ValueError, "assignment.targetSystemType is required"):
            papyrus_newsroom.build_assignment_record_plan(
                edition_id="edition-1",
                corpus_key="AI-ML-research",
                generated_at="2026-05-16T12:00:00Z",
                assignment_json=json.dumps(
                    {
                        "title": "AI Agents Enter the Lab",
                        "research_track_key": "automated-publication-systems",
                        "research_lens": "agent-workflow",
                    }
                ),
            )

    def test_doi_backfill_plan_is_assignment_first(self):
        payload = papyrus_newsroom.papyrus_doi_backfill_plan(
            corpus_key="AI-ML-research",
            max_count=25,
            use_llm=False,
        )["doi_backfill_plan"]
        self.assertEqual(payload["mode"], "assignment-first")
        self.assertIn("create-doi-backfill-assignment", payload["commands"]["create_assignment"])
        self.assertIn("doi-backfill-now", payload["commands"]["run_now"])
        self.assertIn("reference.doi-backfill", payload["commands"]["process_queue"])

    def test_dispatch_plan_caps_assignments_by_section_ratio(self):
        plan = papyrus_newsroom.build_assignment_dispatch_plan(
            edition_id="edition-1",
            corpus_key="AI-ML-research",
            generated_at="2026-05-16T12:00:00Z",
            assignment_ratio=1.5,
            section_targets_json=json.dumps(
                [
                    {"section": "Research", "target_articles": 2},
                    {"section": "Markets", "target_articles": 1},
                ]
            ),
            assignments_json=json.dumps(
                [
                    {"section": "Research", "title": "Research 1"},
                    {"section": "Research", "title": "Research 2"},
                    {"section": "Research", "title": "Research 3"},
                    {"section": "Markets", "title": "Markets 1"},
                    {"section": "Markets", "title": "Markets 2"},
                    {"section": "Markets", "title": "Markets 3"},
                ]
            ),
        )

        self.assertTrue(plan["dryRun"])
        self.assertEqual(plan["lifecycle"], "assignment-dispatch")
        self.assertEqual(plan["reviewerLoad"]["targetArticleCount"], 3)
        self.assertEqual(plan["reviewerLoad"]["dispatchedAssignmentCount"], 5)
        self.assertEqual(plan["reviewerLoad"]["suppressedCandidateCount"], 1)
        self.assertEqual(len(plan["recordPlans"]), 5)
        self.assertEqual(len(plan["reporterDispatches"]), 5)
        self.assertEqual(plan["sectionTargets"][0]["dispatchCount"], 3)
        self.assertEqual(plan["sectionTargets"][1]["dispatchCount"], 2)
        self.assertEqual(plan["recordPlans"][0]["item"]["type"], "assignment")
        self.assertEqual(plan["reporterDispatches"][0]["procedure"], "procedures/newsroom/reporter.tac")
        self.assertIn('"type": "assignment"', plan["reporterDispatches"][0]["input"]["assignment_json"])

    def test_draft_plan_creates_article_from_assignment_item(self):
        plan = papyrus_newsroom.build_draft_update_plan(
            generated_at="2026-05-16T12:30:00Z",
            assignment_item_json=json.dumps(
                {
                    "id": "assignment-1",
                    "type": "assignment",
                    "status": "dispatched",
                    "typeStatus": "assignment#dispatched",
                    "slug": "ai-agents-enter-the-lab",
                    "section": "Research",
                    "title": "AI Agents Enter the Lab",
                    "editorial": {
                        "newsroom": {
                            "assignment": {
                                "brief": "Explain research agents.",
                                "researchTrackKey": "automated-publication-systems",
                                "researchLens": "agent-workflow",
                                "targetSystemType": "research newsroom",
                                "comparisonQuestions": [
                                    "What is the end-to-end handoff sequence from signal detection to published output?"
                                ],
                                "corpusKey": "AI-ML-research",
                            }
                        }
                    },
                }
            ),
            draft_json=json.dumps(
                {
                    "headline": "AI Agents Enter the Lab",
                    "deck": "Research teams are handing more lab work to autonomous systems.",
                    "body": [
                        "Agentic systems are moving from demos into research workflows.",
                        "The strongest evidence comes from scientific discovery and evaluation corpora.",
                    ],
                    "byline": "Papyrus Staff",
                    "evidence_item_ids": ["research-001"],
                }
            ),
        )

        assignment = plan["assignmentItem"]
        item = plan["draftItem"]
        self.assertTrue(plan["dryRun"])
        self.assertEqual(assignment["id"], "assignment-1-v2")
        self.assertEqual(assignment["previousVersionId"], "assignment-1")
        self.assertEqual(assignment["type"], "assignment")
        self.assertEqual(assignment["status"], "drafted")
        self.assertEqual(assignment["typeStatus"], "assignment#drafted")
        self.assertEqual(item["id"], "item-ai-agents-enter-the-lab")
        self.assertEqual(item["type"], "article")
        self.assertEqual(item["status"], "draft")
        self.assertEqual(item["typeStatus"], "article#draft")
        self.assertEqual(item["sectionStatus"], "research#draft")
        self.assertIsNone(item["publishedAt"])
        self.assertIn("assignment", item["editorial"]["newsroom"])
        self.assertEqual(item["editorial"]["newsroom"]["assignmentItemId"], "assignment-1-v2")
        self.assertEqual(item["editorial"]["newsroom"]["draft"]["evidenceItemIds"], ["research-001"])
        self.assertEqual(plan["records"][0]["action"], "create")
        self.assertEqual(plan["records"][1]["action"], "update")
        self.assertEqual(plan["records"][1]["input"]["versionState"], "superseded")
        self.assertEqual(plan["records"][2]["action"], "create")
        relation_records = [record for record in plan["records"] if record["modelName"] == "SemanticRelation"]
        self.assertEqual(len(relation_records), 2)
        self.assertEqual({record["input"]["subjectId"] for record in relation_records}, {"assignment-1-v2", "item-ai-agents-enter-the-lab"})

    def test_list_assignments_research_type_includes_all_research_prefix_keys(self):
        assignments = [
            {
                "id": "assignment-curation-1",
                "assignmentTypeKey": "curation.reference-intake",
                "createdAt": "2026-06-03T19:18:00Z",
            },
            {
                "id": "assignment-tavily-1",
                "assignmentTypeKey": "research.tavily-deep",
                "createdAt": "2026-06-03T19:14:00Z",
                "title": "LLM webinar",
            },
            {
                "id": "assignment-edition-1",
                "assignmentTypeKey": "research.edition-candidate",
                "createdAt": "2026-05-31T19:00:00Z",
                "title": "World models",
            },
        ]
        with mock.patch.object(papyrus_newsroom, "_list_assignments", return_value=assignments):
            result = papyrus_newsroom.papyrus_list_assignments(limit=5, type="research")
        ids = [entry["id"] for entry in result["assignments"]]
        self.assertEqual(ids, ["assignment-tavily-1", "assignment-edition-1"])

    def test_research_plan_preserves_assignment_type(self):
        plan = papyrus_newsroom.build_research_update_plan(
            generated_at="2026-05-16T12:15:00Z",
            assignment_item_json=json.dumps(
                {
                    "id": "assignment-1",
                    "type": "assignment",
                    "status": "dispatched",
                    "typeStatus": "assignment#dispatched",
                    "slug": "ai-agents-enter-the-lab",
                    "section": "Research",
                    "title": "AI Agents Enter the Lab",
                    "editorial": {
                        "newsroom": {
                            "assignment": {
                                "brief": "Explain research agents.",
                                "researchTrackKey": "automated-publication-systems",
                                "researchLens": "agent-workflow",
                                "targetSystemType": "research newsroom",
                                "comparisonQuestions": [
                                    "What is the end-to-end handoff sequence from signal detection to published output?"
                                ],
                            }
                        }
                    },
                }
            ),
            research_json=json.dumps(
                {
                    "summary": "Evidence supports a practical research-workflow angle.",
                    "corpus_key": "AI-ML-research",
                    "category_key": "automated-scientific-discovery",
                    "evidence_item_ids": ["research-001", "research-002"],
                    "doctrine_context": {
                        "publication": {"available": True},
                        "desk": {"available": False, "fallback": "publication"},
                    },
                    "queries": ["agentic research workflows"],
                    "source_snapshots": [{"itemId": "research-001", "title": "Lab agents"}],
                    "proposed_references": [
                        {
                            "title": "Candidate source",
                            "url": "https://example.com/candidate",
                            "ingestion_rationale": "Candidate source relates to the research focus and publication mission.",
                        }
                    ],
                    "research_notes": ["Tie the story to concrete workflow changes."],
                    "comparison_findings": ["Release still requires a human approval gate."],
                    "rubric_assessments": [
                        {"key": "autonomy-scope", "finding": "Partial autonomy only."},
                        {"key": "editorial-control", "finding": "Editors can veto publication."},
                    ],
                    "open_questions": ["Which examples are strongest for the edition?"],
                    "coverage_gaps": ["Need one skeptical source."],
                    "recommended_angle": "Focus on lab workflow delegation.",
                }
            ),
        )

        item = plan["item"]
        self.assertTrue(plan["dryRun"])
        self.assertEqual(plan["lifecycle"], "assignment-research")
        self.assertEqual(item["id"], "assignment-1-v2")
        self.assertEqual(item["previousVersionId"], "assignment-1")
        self.assertEqual(item["type"], "assignment")
        self.assertEqual(item["status"], "researched")
        self.assertEqual(item["typeStatus"], "assignment#researched")
        self.assertIsNone(item["publishedAt"])
        self.assertIn("assignment", item["editorial"]["newsroom"])
        research = item["editorial"]["newsroom"]["research"]
        self.assertEqual(research["status"], "researched")
        self.assertEqual(research["corpusKey"], "AI-ML-research")
        self.assertEqual(research["evidenceItemIds"], ["research-001", "research-002"])
        self.assertEqual(research["researchTrackKey"], "automated-publication-systems")
        self.assertEqual(research["researchLens"], "agent-workflow")
        self.assertEqual(research["targetSystemType"], "research newsroom")
        self.assertEqual(research["doctrineContext"]["desk"]["fallback"], "publication")
        self.assertEqual(research["proposedReferences"][0]["url"], "https://example.com/candidate")
        self.assertEqual(research["comparisonFindings"], ["Release still requires a human approval gate."])
        self.assertEqual(research["rubricAssessments"][0]["key"], "autonomy-scope")
        self.assertEqual(research["procedure"]["role"], "researcher")
        self.assertEqual(plan["records"][0]["action"], "create")
        self.assertEqual(plan["records"][1]["input"]["versionState"], "superseded")
        relation_records = [record for record in plan["records"] if record["modelName"] == "SemanticRelation"]
        self.assertEqual(len(relation_records), 2)
        self.assertEqual(relation_records[0]["input"]["objectId"], "reference-knowledge-corpus-ai-ml-research-research-001-v1")
        self.assertEqual(relation_records[0]["input"]["relationTypeKey"], "uses_evidence")

    def test_live_assignment_research_packet_plan_creates_message_and_produces_relation(self):
        plan = papyrus_newsroom.build_assignment_research_packet_plan(
            generated_at="2026-05-18T15:30:00Z",
            assignment={
                "id": "assignment-live-123",
                "assignmentTypeKey": "research.edition-candidate",
                "queueKey": "edition:edition-2026-05-18:desk:automation:lane:reporting",
                "queueStatusKey": "edition:edition-2026-05-18:desk:automation:lane:reporting#open",
                "status": "open",
                "title": "Research automated publication systems",
                "brief": "Find current source material.",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "metadata": {
                    "deskCategoryKey": "automation",
                    "focusCategoryKey": "automated-publication-systems",
                    "contextProfile": "reporting",
                    "contextTokenBudget": 4000,
                },
            },
            research={
                "summary": "Found one current source prospect.",
                "corpus_key": "AI-ML-research",
                "queries": ["automated publication systems newsroom"],
                "source_snapshots": [
                    {
                        "url": "https://example.com/source",
                        "source_domain": "example.com",
                        "evidence_candidate_id": "evidence-candidate-1",
                    }
                ],
                "proposed_references": [
                    {
                        "title": "Candidate source",
                        "url": "https://example.com/source",
                        "ingestion_rationale": "Candidate source relates to the focus and publication mission.",
                    }
                ],
                "evidence_item_ids": [],
                "research_mode": "source_discovery",
                "internalFindings": {
                    "summary": "Internal evidence is thin.",
                    "evidenceItemIds": [],
                    "queries": ["automated publication systems newsroom"],
                },
                "sourceDiscovery": {
                    "webSearches": ["automated publication systems newsroom"],
                    "sourceSnapshots": [
                        {
                            "url": "https://example.com/source",
                            "source_domain": "example.com",
                        }
                    ],
                },
                "synthesis": {
                    "summary": "Found one current source prospect.",
                    "recommendedAngle": "Review as intake candidate.",
                },
                "recommended_angle": "Review as intake candidate.",
            },
        )

        self.assertTrue(plan["dryRun"])
        self.assertEqual(plan["lifecycle"], "assignment-research-packet")
        self.assertEqual([record["modelName"] for record in plan["records"]], ["Message", "ModelAttachment", "ModelAttachment", "SemanticRelation"])
        message = plan["records"][0]["input"]
        self.assertEqual(message["messageKind"], "research_packet")
        self.assertEqual(message["messageDomain"], "assignment_work")
        metadata_attachment = plan["records"][2]
        self.assertEqual(metadata_attachment["input"]["role"], "metadata")
        metadata = json.loads(metadata_attachment["body"])
        self.assertEqual(metadata["kind"], "research.packet.created")
        self.assertEqual(metadata["assignmentId"], "assignment-live-123")
        self.assertEqual(metadata["research"]["researchMode"], "source_discovery")
        self.assertEqual(metadata["research"]["internalFindings"]["summary"], "Internal evidence is thin.")
        self.assertEqual(metadata["research"]["sourceDiscovery"]["webSearches"], ["automated publication systems newsroom"])
        self.assertEqual(metadata["research"]["synthesis"]["recommendedAngle"], "Review as intake candidate.")
        self.assertEqual(metadata["research"]["sourceSnapshots"][0]["source_domain"], "example.com")
        self.assertEqual(metadata["research"]["proposedReferences"][0]["ingestion_rationale"], "Candidate source relates to the focus and publication mission.")
        relation = plan["records"][3]["input"]
        self.assertEqual(relation["predicate"], "produces")
        self.assertEqual(relation["relationTypeKey"], "produces")
        self.assertEqual(relation["relationDomain"], "workflow")
        self.assertEqual(relation["subjectKind"], "assignment")
        self.assertEqual(relation["subjectId"], "assignment-live-123")
        self.assertEqual(relation["objectKind"], "message")

    def test_execute_tactus_can_plan_live_assignment_research_packet(self):
        result = tactus_runtime.execute_tactus(
            """
local assignment = {
  id = "assignment-live-123",
  assignmentTypeKey = "research.edition-candidate",
  queueKey = "edition:edition-2026-05-18:desk:automation:lane:reporting",
  status = "open",
  title = "Research automated publication systems",
}
local research = {
  summary = "Found one source prospect.",
  corpus_key = "AI-ML-research",
  source_snapshots = { { url = "https://example.com/source", source_domain = "example.com" } },
  proposed_references = { { title = "Candidate source", url = "https://example.com/source", ingestion_rationale = "Review for intake." } },
  evidence_item_ids = {},
}
return plan_assignment_research_packet{ assignment = assignment, research = research }
"""
        )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["value"]["lifecycle"], "assignment-research-packet")
        self.assertEqual(result["value"]["records"][0]["modelName"], "Message")
        self.assertEqual(result["value"]["records"][3]["input"]["relationTypeKey"], "produces")
        self.assertEqual(result["api_calls"], ["papyrus.plan.assignment_research_packet"])

    def test_live_assignment_reporting_context_packet_plan_creates_private_message_only(self):
        plan = papyrus_newsroom.build_assignment_reporting_context_packet_plan(
            generated_at="2026-05-18T16:00:00Z",
            assignment={
                "id": "assignment-reporting-123",
                "assignmentTypeKey": "reporting.edition-candidate",
                "queueKey": "edition:edition-2026-05-23:section:news:lane:reporting",
                "queueStatusKey": "edition:edition-2026-05-23:section:news:lane:reporting#open",
                "status": "open",
                "title": "News reporting candidate",
                "sectionKey": "news",
                "classifierId": "demo-classifier",
                "metadata": {
                    "editionId": "edition-2026-05-23-v1",
                    "candidateRank": 1,
                    "slotTarget": {"sectionKey": "news", "slots": 2, "candidateRank": 1},
                    "reportingContextOrder": [
                        "publication-doctrine",
                        "section-doctrine",
                        "assignment-brief",
                        "accepted-knowledge-base-evidence",
                        "recent-section-memory",
                        "fresh-source-needs",
                    ],
                },
            },
            reporting={
                "summary": "A reported candidate is ready for editor selection.",
                "why_now": "The source material changed this week.",
                "nut_graf_candidate": "The article should explain what changed and why it matters.",
                "recommended_angle": "Focus on practical reader impact.",
                "confirmed_facts": ["The accepted reference confirms the release date."],
                "source_trail": [{"title": "Accepted source", "reference_id": "reference-1-v1"}],
                "accepted_reference_ids": ["reference-1-v1"],
                "proposed_references": [{"title": "Fresh source prospect", "url": "https://example.com/source"}],
                "recent_desk_memory_used": ["Prior News coverage emphasized verification."],
                "coverage_gaps": ["Need comment from affected users."],
                "open_questions": ["Is the rollout complete?"],
                "risk_flags": ["Avoid promotional framing."],
                "verification_needs": ["Verify the fresh prospect before copywriting."],
                "source_diversity_notes": ["Accepted evidence is single-source so far."],
                "copywriter_brief": "Use the accepted source and clearly label unresolved questions.",
                "editor_recommendation": "hold",
            },
        )

        self.assertTrue(plan["dryRun"])
        self.assertEqual(plan["lifecycle"], "assignment-reporting-context-packet")
        self.assertEqual([record["modelName"] for record in plan["records"]], ["Message", "ModelAttachment", "ModelAttachment", "SemanticRelation"])
        self.assertFalse(any(record["modelName"] in {"Item", "EditionItem"} for record in plan["records"]))
        message = plan["records"][0]["input"]
        self.assertEqual(message["messageKind"], "reporting_context_packet")
        self.assertEqual(message["messageDomain"], "assignment_work")
        metadata = json.loads(plan["records"][2]["body"])
        self.assertEqual(metadata["kind"], "reporting.context_packet.created")
        self.assertEqual(metadata["assignmentId"], "assignment-reporting-123")
        self.assertEqual(metadata["reporting"]["sectionKey"], "news")
        self.assertEqual(metadata["reporting"]["editionId"], "edition-2026-05-23-v1")
        self.assertEqual(metadata["reporting"]["acceptedReferenceIds"], ["reference-1-v1"])
        self.assertEqual(metadata["reporting"]["editorRecommendation"], "hold")
        relation = plan["records"][3]["input"]
        self.assertEqual(relation["predicate"], "produces")
        self.assertEqual(relation["subjectKind"], "assignment")
        self.assertEqual(relation["objectKind"], "message")

    def test_reporting_context_packet_plan_links_source_research_lineage(self):
        plan = papyrus_newsroom.build_assignment_reporting_context_packet_plan(
            generated_at="2026-05-18T16:15:00Z",
            assignment={
                "id": "assignment-reporting-derived",
                "assignmentTypeKey": "reporting.edition-candidate",
                "queueKey": "edition:edition-2026-05-23:section:science:lane:reporting",
                "status": "open",
                "sectionKey": "science",
            },
            reporting={
                "summary": "A reported candidate is derived from research.",
                "section_key": "science",
                "edition_id": "edition-2026-05-23-v1",
                "source_research_packet_id": "message-research-packet-1",
                "source_research_assignment_id": "assignment-research-1",
                "copywriter_brief": "Use only after editor selection.",
            },
        )

        relation_records = [record["input"] for record in plan["records"] if record["modelName"] == "SemanticRelation"]
        self.assertEqual([relation["predicate"] for relation in relation_records], ["produces", "derived_from", "derived_from"])
        self.assertEqual(relation_records[1]["subjectKind"], "assignment")
        self.assertEqual(relation_records[1]["objectKind"], "message")
        self.assertEqual(relation_records[1]["objectId"], "message-research-packet-1")
        self.assertEqual(relation_records[2]["objectKind"], "assignment")
        self.assertEqual(relation_records[2]["objectId"], "assignment-research-1")

    def test_execute_tactus_can_plan_reporting_context_packet(self):
        result = tactus_runtime.execute_tactus(
            """
local assignment = {
  id = "assignment-reporting-123",
  assignmentTypeKey = "reporting.edition-candidate",
  queueKey = "edition:edition-2026-05-23:section:news:lane:reporting",
  status = "open",
  sectionKey = "news",
  metadata = { editionId = "edition-2026-05-23-v1", candidateRank = 1 },
}
local reporting = {
  summary = "Reporting context ready.",
  section_key = "news",
  edition_id = "edition-2026-05-23-v1",
  confirmed_facts = { "Accepted source confirms the date." },
  accepted_reference_ids = { "reference-1-v1" },
  copywriter_brief = "Draft only after editor selection.",
  editor_recommendation = "select",
}
return plan_assignment_reporting_context_packet{ assignment = assignment, reporting = reporting }
"""
        )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["value"]["lifecycle"], "assignment-reporting-context-packet")
        self.assertEqual(result["value"]["records"][0]["input"]["messageKind"], "reporting_context_packet")
        self.assertEqual(result["value"]["records"][3]["input"]["relationTypeKey"], "produces")
        self.assertEqual(result["api_calls"], ["papyrus.plan.assignment_reporting_context_packet"])

    def test_reporter_procedure_routes_live_reporting_assignments_to_context_packets(self):
        source = (REPO_ROOT / "procedures" / "newsroom" / "reporter.tac").read_text()
        self.assertIn("reporting.edition-candidate Assignments must produce a", source)
        self.assertIn("reporting_context_packet payload", source)
        self.assertIn("Do not generate Papyrus persistence snippets", source)
        self.assertIn("Do not call Papyrus persistence planners", source)
        self.assertIn("run one broad knowledge_query", source)
        self.assertIn("source_trail plus related metadata fields", source)
        self.assertIn('"work_product_kind":"reporting_context_packet"', source)
        self.assertIn("the outer CLI writes Message", source)
        self.assertIn("return a reporting_context_packet payload only", source)

    def test_research_explorer_requires_broad_knowledge_query_orientation(self):
        source = (REPO_ROOT / "procedures" / "newsroom" / "research_explorer.tac").read_text()
        self.assertIn("Required policy sequence:", source)
        self.assertIn("Run one broad knowledge_query", source)

    def test_execute_tactus_exposes_knowledge_query_helper(self):
        with mock.patch("papyrus_newsroom.tactus_runtime.build_environment_services", return_value=object()), \
             mock.patch("papyrus_newsroom.tactus_runtime.run_knowledge_query") as run_query:
            run_query.return_value = {
                "structured": {"semanticMatches": []},
                "context": {"text": "Accepted context."},
                "warnings": [],
            }
            result = tactus_runtime.execute_tactus(
                'return knowledge_query{ query = "agent memory", max_tokens = 200, top_k = 3, format = "both" }'
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["value"]["context"]["text"], "Accepted context.")
        self.assertEqual(result["api_calls"], ["papyrus.knowledge.query"])
        run_query.assert_called_once()
        query_input = run_query.call_args.args[0]
        self.assertEqual(query_input["semanticQuery"], "agent memory")
        self.assertEqual(query_input["scope"]["topK"], 3)
        self.assertEqual(query_input["output"]["maxTokens"], 200)

    def test_execute_tactus_exposes_papyrus_uri_resolver(self):
        with mock.patch("papyrus_newsroom.tactus_runtime.newsroom.papyrus_resolve_uri") as resolve_uri:
            resolve_uri.return_value = {
                "uri": "papyrus://reference/reference-1",
                "kind": "reference",
                "lineageId": "reference-1",
                "object": {"id": "reference-1-v1", "lineageId": "reference-1", "curationStatus": "accepted"},
            }
            result = tactus_runtime.execute_tactus('return papyrus.resolve_uri{ uri = "papyrus://reference/reference-1" }')

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["value"]["object"]["id"], "reference-1-v1")
        self.assertEqual(result["api_calls"], ["papyrus.resolve_uri"])
        resolve_uri.assert_called_once_with("papyrus://reference/reference-1")

    def test_execute_tactus_exposes_reference_fetch_url_text_helper(self):
        with mock.patch("papyrus_newsroom.tactus_runtime.newsroom.papyrus_reference_fetch_url_text") as fetch_url_text:
            fetch_url_text.return_value = {"reference_url_text": {"ok": True, "changes": 1}}
            result = tactus_runtime.execute_tactus(
                'return reference_fetch_url_text{ reference_id = "reference-1", corpus_key = "AI-ML-research", apply = false }'
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["value"]["reference_url_text"]["ok"], True)
        self.assertEqual(result["api_calls"], ["papyrus.reference.fetch_url_text"])
        fetch_url_text.assert_called_once()

    def test_execute_tactus_exposes_reference_generate_metadata_helper(self):
        with mock.patch(
            "papyrus_newsroom.tactus_runtime.newsroom.papyrus_reference_generate_metadata_from_text"
        ) as generate_metadata:
            generate_metadata.return_value = {"reference_metadata_generation": {"ok": True, "generated": 1}}
            handler = tactus_runtime.API_METHODS[("reference", "generate_metadata_from_text")]
            result = handler(
                {
                    "reference_id": "reference-1",
                    "corpus_key": "AI-ML-research",
                    "apply": False,
                }
            )

        self.assertEqual(result["reference_metadata_generation"]["ok"], True)
        helper_pairs = {(name, namespace, method) for name, namespace, method in tactus_runtime.HELPER_BINDINGS}
        self.assertIn(
            ("reference_generate_metadata_from_text", "reference", "generate_metadata_from_text"),
            helper_pairs,
        )
        generate_metadata.assert_called_once()

    def test_execute_tactus_exposes_reference_filter_extracted_text_helper(self):
        with mock.patch(
            "papyrus_newsroom.tactus_runtime.newsroom.papyrus_reference_filter_extracted_text"
        ) as filter_text:
            filter_text.return_value = {"reference_text_filter": {"ok": True, "filtered": 1}}
            handler = tactus_runtime.API_METHODS[("reference", "filter_extracted_text")]
            result = handler(
                {
                    "reference_id": "reference-1",
                    "corpus_key": "AI-ML-research",
                    "apply": False,
                }
            )

        self.assertEqual(result["reference_text_filter"]["ok"], True)
        helper_pairs = {(name, namespace, method) for name, namespace, method in tactus_runtime.HELPER_BINDINGS}
        self.assertIn(
            ("reference_filter_extracted_text", "reference", "filter_extracted_text"),
            helper_pairs,
        )
        filter_text.assert_called_once()

    def test_knowledge_query_helper_accepts_uri_anchor(self):
        with mock.patch("papyrus_newsroom.tactus_runtime.build_environment_services", return_value=object()), \
             mock.patch("papyrus_newsroom.tactus_runtime.run_knowledge_query") as run_query:
            run_query.return_value = {
                "structured": {"anchors": [{"kind": "reference", "lineageId": "reference-1"}]},
                "context": {"text": "Anchored context."},
                "warnings": [],
            }
            result = tactus_runtime.execute_tactus(
                'return knowledge_query{ uri = "papyrus://reference/reference-1", max_tokens = 200, top_k = 3 }'
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["value"]["context"]["text"], "Anchored context.")
        query_input = run_query.call_args.args[0]
        self.assertEqual(query_input["anchors"], [{"uri": "papyrus://reference/reference-1"}])

    def test_research_harness_supports_uri_anchored_knowledge_trace(self):
        assignment = {
            "id": "assignment-live-123",
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "research#open",
            "status": "open",
            "title": "Explore internal evidence",
        }
        with mock.patch("papyrus_newsroom.tactus_runtime.build_environment_services", return_value=object()), \
             mock.patch("papyrus_newsroom.tactus_runtime.run_knowledge_query") as run_query:
            run_query.return_value = {
                "structured": {
                    "anchors": [
                        {"kind": "reference", "id": "reference-1-v1", "lineageId": "reference-1", "curationStatus": "accepted"}
                    ],
                    "semanticMatches": [],
                },
                "context": {"text": "Accepted anchored context."},
                "warnings": [],
            }
            result = tactus_runtime.execute_tactus_harnessed(
                """
local knowledge = knowledge_search_uri("papyrus://reference/reference-1", { max_tokens = 300 })
local ids = evidence_item_ids_from_knowledge(knowledge)
return finish_research{
  summary = "Built exploratory packet from internal evidence.",
  queries = {"anchored query"},
  source_snapshots = {},
  proposed_references = {},
  evidence_item_ids = ids,
  recommended_angle = "Start with accepted internal evidence.",
  researchTrace = {
    knowledgeQueries = {"anchored query"},
    papyrusUrisInspected = {"papyrus://reference/reference-1"},
    webSearches = {},
    acceptedEvidenceIds = ids,
    unresolvedGaps = {},
  },
}
""",
                harness="research",
                assignment_item_json=json.dumps(assignment),
                corpus_key="AI-ML-research",
                max_evidence_items=8,
                research_mode="internal_brief",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["value"]["research_packet"]["evidence_item_ids"], ["reference-1-v1"])
        self.assertEqual(result["value"]["research_packet"]["research_mode"], "internal_brief")
        self.assertEqual(result["value"]["research_packet"]["researchTrace"]["webSearches"], [])
        self.assertEqual(result["value"]["research_record_plan"]["message_persistence"], "outer_cli_layer")
        self.assertEqual(result["api_calls"], ["papyrus.knowledge.query", "papyrus.plan.assignment_research_packet"])

    def test_research_harness_applies_assignment_and_insight_knowledge_scope_defaults(self):
        assignment = {
            "id": "assignment-live-456",
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "research#open",
            "status": "open",
            "title": "Explore AI in gaming",
        }
        with mock.patch("papyrus_newsroom.tactus_runtime.build_environment_services", return_value=object()), \
             mock.patch("papyrus_newsroom.tactus_runtime.run_knowledge_query") as run_query:
            run_query.return_value = {
                "structured": {"anchors": [], "semanticMatches": []},
                "context": {"text": "Internal context."},
                "warnings": [],
            }
            result = tactus_runtime.execute_tactus_harnessed(
                """
local knowledge = knowledge_search("ai in gaming")
return finish_research{
  summary = "Built packet.",
  queries = {"ai in gaming"},
  source_snapshots = {},
  proposed_references = {},
  evidence_item_ids = {},
  recommended_angle = "Angle",
  researchTrace = { knowledgeQueries = {"ai in gaming"}, webSearches = {}, acceptedEvidenceIds = {} },
}
""",
                harness="research",
                assignment_item_json=json.dumps(assignment),
                corpus_key="AI-ML-research",
                max_evidence_items=8,
                research_mode="internal_brief",
            )

        self.assertTrue(result["ok"], result.get("error"))
        query_input = run_query.call_args.args[0]
        scope = query_input.get("scope") or {}
        self.assertIn("assignment", scope.get("includeObjectKinds") or [])
        self.assertIn("message", scope.get("includeObjectKinds") or [])
        self.assertEqual(scope.get("includeMessageKinds"), ["insight"])
        self.assertEqual(scope.get("includeAssignmentTypeKeys"), ["research.*", "reporting.*"])

    def test_research_harness_requires_discovery_for_source_discovery_mode(self):
        assignment = {
            "id": "assignment-live-123",
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "research#open",
            "status": "open",
            "title": "Explore source discovery",
        }
        result = tactus_runtime.execute_tactus_harnessed(
            """
return finish_research{
  summary = "Internal-only packet should fail in source discovery mode.",
  queries = {"agent catalog"},
  source_snapshots = {},
  proposed_references = {},
  evidence_item_ids = {},
  recommended_angle = "Find external source prospects.",
  researchTrace = {
    knowledgeQueries = {"agent catalog"},
    papyrusUrisInspected = {},
    webSearches = {},
    acceptedEvidenceIds = {},
    unresolvedGaps = {},
  },
}
""",
            harness="research",
            assignment_item_json=json.dumps(assignment),
            corpus_key="AI-ML-research",
            max_evidence_items=8,
            research_mode="source_discovery",
        )

        self.assertFalse(result["ok"])
        self.assertIn("requires web discovery", result["error"]["message"])

    def test_research_harness_accepts_source_discovery_bundle_with_prospects(self):
        assignment = {
            "id": "assignment-live-123",
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "research#open",
            "status": "open",
            "title": "Explore source discovery",
        }
        result = tactus_runtime.execute_tactus_harnessed(
            """
return finish_research{
  research_mode = "source_discovery",
  summary = "Internal orientation plus external prospect.",
  queries = {"agent catalog"},
  source_snapshots = { { url = "https://example.com/source", source_domain = "example.com" } },
  proposed_references = { { title = "Candidate", url = "https://example.com/source", ingestion_rationale = "Candidate supports the research focus." } },
  evidence_item_ids = {},
  recommended_angle = "Compare current terminology.",
  researchTrace = {
    knowledgeQueries = {"agent catalog"},
    papyrusUrisInspected = {},
    webSearches = {"agent catalog business process automation"},
    acceptedEvidenceIds = {},
    unresolvedGaps = {},
  },
}
""",
            harness="research",
            assignment_item_json=json.dumps(assignment),
            corpus_key="AI-ML-research",
            max_evidence_items=8,
            research_mode="source_discovery",
        )

        self.assertTrue(result["ok"], result.get("error"))
        packet = result["value"]["research_packet"]
        self.assertEqual(packet["research_mode"], "source_discovery")
        self.assertEqual(packet["sourceDiscovery"]["webSearches"], ["agent catalog business process automation"])
        self.assertEqual(packet["sourceDiscovery"]["proposedReferences"][0]["title"], "Candidate")

    def test_research_harness_web_search_uses_reference_web_search_api(self):
        assignment = {
            "id": "assignment-live-123",
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "research#open",
            "status": "open",
            "title": "Explore source discovery",
        }
        with mock.patch(
            "papyrus_newsroom.tactus_runtime.reference_curation_signals.reference_web_search",
            return_value={
                "query": "ancient language ai decipherment",
                "results": [
                    {
                        "title": "Ithaca Nature paper",
                        "url": "https://example.org/ithaca",
                        "source_domain": "example.org",
                        "evidence_candidate_id": "evidence-candidate-1",
                        "rank": 1,
                    }
                ],
                "metadata": {"answer": "Project and paper references for ancient-text decipherment."},
            },
        ) as web_search:
            result = tactus_runtime.execute_tactus_harnessed(
                """
local search = web_search("ancient language ai decipherment")
return finish_research_from_search(search, { research_mode = "source_discovery" })
""",
                harness="research",
                assignment_item_json=json.dumps(assignment),
                corpus_key="AI-ML-research",
                max_evidence_items=8,
                research_mode="source_discovery",
            )

        self.assertTrue(result["ok"], result.get("error"))
        packet = result["value"]["research_packet"]
        self.assertEqual(packet["source_snapshots"][0]["url"], "https://example.org/ithaca")
        self.assertEqual(packet["proposed_references"][0]["url"], "https://example.org/ithaca")
        self.assertEqual(packet["researchTrace"]["webSearches"], ["ancient language ai decipherment"])
        web_search.assert_called_once()
        self.assertEqual(web_search.call_args.kwargs["query"], "ancient language ai decipherment")

    def test_research_harness_finish_research_from_search_accepts_table_call_syntax(self):
        assignment = {
            "id": "assignment-live-123",
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "research#open",
            "status": "open",
            "title": "Explore source discovery",
        }
        with mock.patch(
            "papyrus_newsroom.tactus_runtime.reference_curation_signals.reference_web_search",
            return_value={
                "query": "erdos unit distance conjecture",
                "results": [
                    {
                        "title": "OpenAI announcement",
                        "url": "https://openai.com/index/model-disproves-discrete-geometry-conjecture/",
                        "source_domain": "openai.com",
                        "evidence_candidate_id": "evidence-candidate-1",
                        "rank": 1,
                    }
                ],
                "metadata": {"answer": "OpenAI disproved the conjecture."},
            },
        ):
            result = tactus_runtime.execute_tactus_harnessed(
                """
local search = web_search("erdos unit distance conjecture")
return finish_research_from_search{
  research_mode = "full_research",
  summary = "Agent-style table call",
  queries = {"erdos unit distance conjecture"},
  source_snapshots = search and search.results or {},
  proposed_references = search and proposed_references_from_search(search) or {},
  evidence_item_ids = {},
}
""",
                harness="research",
                assignment_item_json=json.dumps(assignment),
                corpus_key="AI-ML-research",
                max_evidence_items=8,
                research_mode="full_research",
            )

        self.assertTrue(result["ok"], result.get("error"))
        packet = result["value"]["research_packet"]
        self.assertEqual(packet["proposed_references"][0]["url"], "https://openai.com/index/model-disproves-discrete-geometry-conjecture/")
        self.assertEqual(packet["source_snapshots"][0]["url"], "https://openai.com/index/model-disproves-discrete-geometry-conjecture/")
        boundary = packet["researchTrace"]["discoveryBoundary"]
        self.assertEqual(boundary["searchResultCount"], 1)
        self.assertEqual(boundary["discoveryTerminalState"], "succeeded")

    def test_research_harness_normalizes_newlines_inside_quoted_strings(self):
        assignment = {
            "id": "assignment-live-123",
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "research#open",
            "status": "open",
            "title": "Explore source discovery",
        }
        with mock.patch(
            "papyrus_newsroom.tactus_runtime.reference_curation_signals.reference_web_search",
            return_value={
                "query": "erdos unit distance conjecture",
                "results": [
                    {
                        "title": "OpenAI announcement",
                        "url": "https://openai.com/index/model-disproves-discrete-geometry-conjecture/",
                        "source_domain": "openai.com",
                        "evidence_candidate_id": "evidence-candidate-1",
                        "rank": 1,
                    }
                ],
                "metadata": {"answer": "OpenAI disproved the conjecture."},
            },
        ):
            result = tactus_runtime.execute_tactus_harnessed(
                """
local search = web_search("OpenAI Erdos
planar unit distance conjecture")
return finish_research_from_search{
  research_mode = "full_research",
  summary = "Agent-style table call with wrapped query",
  queries = {"erdos unit distance conjecture"},
  source_snapshots = search and search.results or {},
  proposed_references = search and proposed_references_from_search(search) or {},
  evidence_item_ids = {},
}
""",
                harness="research",
                assignment_item_json=json.dumps(assignment),
                corpus_key="AI-ML-research",
                max_evidence_items=8,
                research_mode="full_research",
            )

        self.assertTrue(result["ok"], result.get("error"))
        packet = result["value"]["research_packet"]
        self.assertEqual(packet["proposed_references"][0]["url"], "https://openai.com/index/model-disproves-discrete-geometry-conjecture/")

    def test_research_harness_normalizes_malformed_search_metadata(self):
        assignment = {
            "id": "assignment-live-123",
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "research#open",
            "status": "open",
            "title": "Explore source discovery",
        }
        with mock.patch(
            "papyrus_newsroom.tactus_runtime.reference_curation_signals.reference_web_search",
            return_value={
                "query": "ancient language ai decipherment",
                "results": [
                    {
                        "title": "Ithaca Nature paper",
                        "url": "https://example.org/ithaca",
                        "source_domain": "example.org",
                        "evidence_candidate_id": "evidence-candidate-1",
                        "rank": 1,
                    }
                ],
                "metadata": "not-a-table",
            },
        ):
            result = tactus_runtime.execute_tactus_harnessed(
                """
local search = web_search("ancient language ai decipherment")
return finish_research_from_search(search, { research_mode = "source_discovery" })
""",
                harness="research",
                assignment_item_json=json.dumps(assignment),
                corpus_key="AI-ML-research",
                max_evidence_items=8,
                research_mode="source_discovery",
            )

        self.assertTrue(result["ok"], result.get("error"))
        packet = result["value"]["research_packet"]
        self.assertEqual(packet["source_snapshots"][0]["url"], "https://example.org/ithaca")
        boundary = packet["researchTrace"]["discoveryBoundary"]
        self.assertEqual(boundary["webSearchPath"], "papyrus.reference.web_search")
        self.assertEqual(boundary["searchResultCount"], 1)
        self.assertIsInstance(boundary["searchMetadataShapeOk"], bool)

    def test_research_harness_sets_blocked_reason_when_reference_web_search_fails(self):
        assignment = {
            "id": "assignment-live-123",
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "research#open",
            "status": "open",
            "title": "Explore source discovery",
        }
        with mock.patch(
            "papyrus_newsroom.tactus_runtime.reference_curation_signals.reference_web_search",
            side_effect=RuntimeError("boom"),
        ):
            result = tactus_runtime.execute_tactus_harnessed(
                """
local search = web_search("ancient language ai decipherment")
return finish_research_from_search(search, { research_mode = "source_discovery" })
""",
                harness="research",
                assignment_item_json=json.dumps(assignment),
                corpus_key="AI-ML-research",
                max_evidence_items=8,
                research_mode="source_discovery",
            )

        self.assertTrue(result["ok"], result.get("error"))
        packet = result["value"]["research_packet"]
        self.assertEqual(packet["source_snapshots"], [])
        self.assertEqual(packet["proposed_references"], [])
        self.assertIn("papyrus.reference.web_search failed", packet["sourceDiscovery"]["blockedReason"])
        boundary = packet["researchTrace"]["discoveryBoundary"]
        self.assertEqual(boundary["webSearchPath"], "papyrus.reference.web_search")
        self.assertEqual(boundary["searchResultCount"], 0)
        self.assertTrue(boundary["searchMetadataShapeOk"])
        self.assertIn("papyrus.reference.web_search failed", boundary["blockedReason"])

    def test_research_harness_retries_zero_result_discovery_until_success(self):
        assignment = {
            "id": "assignment-live-123",
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "research#open",
            "status": "open",
            "title": "Explore source discovery",
        }
        responses = [
            {
                "query": "agentic ai protocols survey",
                "results": [],
                "metadata": {"answer": ""},
            },
            {
                "query": "agentic ai protocols survey review explainer",
                "results": [
                    {
                        "title": "Survey hit",
                        "url": "https://example.org/survey",
                        "source_domain": "example.org",
                        "evidence_candidate_id": "evidence-candidate-2",
                        "rank": 1,
                    }
                ],
                "metadata": {"answer": "survey source"},
            },
        ]
        with mock.patch(
            "papyrus_newsroom.tactus_runtime.reference_curation_signals.reference_web_search",
            side_effect=responses,
        ) as web_search:
            result = tactus_runtime.execute_tactus_harnessed(
                """
local search = web_search("agentic ai protocols survey", { retry_budget = 4 })
return finish_research_from_search(search, { research_mode = "source_discovery" })
""",
                harness="research",
                assignment_item_json=json.dumps(assignment),
                corpus_key="AI-ML-research",
                max_evidence_items=8,
                research_mode="source_discovery",
            )

        self.assertTrue(result["ok"], result.get("error"))
        packet = result["value"]["research_packet"]
        self.assertEqual(packet["source_snapshots"][0]["url"], "https://example.org/survey")
        boundary = packet["researchTrace"]["discoveryBoundary"]
        self.assertEqual(boundary["discoveryTerminalState"], "succeeded")
        self.assertEqual(boundary["discoveryAttemptsTotal"], 2)
        self.assertEqual(boundary["discoveryResultCounts"], [0, 1])
        self.assertEqual(len(boundary["discoveryQueriesTried"]), 2)
        web_search.assert_called()
        self.assertEqual(web_search.call_count, 2)

    def test_research_harness_exhausted_zero_results_sets_blocked_reason(self):
        assignment = {
            "id": "assignment-live-123",
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "research#open",
            "status": "open",
            "title": "Explore source discovery",
        }
        with mock.patch(
            "papyrus_newsroom.tactus_runtime.reference_curation_signals.reference_web_search",
            return_value={
                "query": "agentic ai protocols survey",
                "results": [],
                "metadata": {"answer": ""},
            },
        ) as web_search:
            result = tactus_runtime.execute_tactus_harnessed(
                """
local search = web_search("agentic ai protocols survey", { retry_budget = 4 })
return finish_research_from_search(search, { research_mode = "source_discovery" })
""",
                harness="research",
                assignment_item_json=json.dumps(assignment),
                corpus_key="AI-ML-research",
                max_evidence_items=8,
                research_mode="source_discovery",
            )

        self.assertTrue(result["ok"], result.get("error"))
        packet = result["value"]["research_packet"]
        self.assertEqual(packet["source_snapshots"], [])
        self.assertEqual(packet["proposed_references"], [])
        self.assertEqual(packet["sourceDiscovery"]["blockedReason"], "web_discovery_exhausted_zero_results")
        boundary = packet["researchTrace"]["discoveryBoundary"]
        self.assertEqual(boundary["discoveryTerminalState"], "exhausted")
        self.assertEqual(boundary["discoveryAttemptsTotal"], 4)
        self.assertEqual(boundary["discoveryResultCounts"], [0, 0, 0, 0])
        self.assertEqual(len(boundary["discoveryQueriesTried"]), 4)
        self.assertEqual(web_search.call_count, 4)

    def test_track_research_warns_when_doctrine_context_and_rubric_are_missing(self):
        plan = papyrus_newsroom.build_research_update_plan(
            generated_at="2026-05-16T12:15:00Z",
            assignment_item_json=json.dumps(
                {
                    "id": "assignment-1",
                    "type": "assignment",
                    "status": "dispatched",
                    "typeStatus": "assignment#dispatched",
                    "slug": "ai-agents-enter-the-lab",
                    "section": "Research",
                    "title": "AI Agents Enter the Lab",
                    "editorial": {
                        "newsroom": {
                            "assignment": {
                                "brief": "Explain research agents.",
                                "researchTrackKey": "automated-publication-systems",
                                "researchLens": "agent-workflow",
                                "targetSystemType": "research newsroom",
                            }
                        }
                    },
                }
            ),
            research_json=json.dumps(
                {
                    "summary": "Evidence supports a practical research-workflow angle.",
                    "corpus_key": "AI-ML-research",
                    "evidence_item_ids": ["research-001"],
                    "queries": ["agentic research workflows"],
                    "source_snapshots": [{"itemId": "research-001", "title": "Lab agents"}],
                    "recommended_angle": "Focus on lab workflow delegation.",
                }
            ),
        )

        self.assertIn("research.doctrineContext is empty", plan["warnings"])
        self.assertIn("research.rubricAssessments is empty", plan["warnings"])

    def test_live_assignment_context_normalizes_to_procedure_item(self):
        result = papyrus_newsroom.papyrus_assignment_context_to_item(
            generated_at="2026-05-16T12:15:00Z",
            assignment_context_json=json.dumps(
                {
                    "assignment": {
                        "id": "assignment-live-123",
                        "assignmentTypeKey": "research.edition-candidate",
                        "queueKey": "edition:edition-2026-05-16:desk:automated-scientific-discovery:lane:reporting",
                        "queueStatusKey": "edition:edition-2026-05-16:desk:automated-scientific-discovery:lane:reporting#open",
                        "status": "open",
                        "title": "Reporting candidate 1: Automated Scientific Discovery",
                        "brief": "Report a fresh evidence-led candidate story.",
                        "metadata": {
                            "editionDate": "2026-05-16",
                            "deskCategoryKey": "automated-scientific-discovery",
                            "deskCategoryLineageId": "category-1",
                            "deskCategoryTitle": "Automated Scientific Discovery",
                            "focusCategoryKey": "agent-workflow",
                            "focusCategoryLineageId": "category-focus-1",
                            "focusCategoryTitle": "Agent Workflow",
                            "contextProfile": "reporting",
                            "contextTokenBudget": 4000,
                            "contextSources": ["doctrine", "focus-category", "desk-memory", "fresh-evidence"],
                            "rootCategoryKey": "automated-scientific-discovery",
                            "researchTrackKey": "automated-publication-systems",
                            "researchTrackTitle": "Fully-Automated Publication Systems",
                            "researchLens": "agent-workflow",
                            "researchLensTitle": "Agent Workflow",
                            "assignmentTemplateKey": "agent-workflow",
                            "assignmentTemplateTitle": "Agent Workflow",
                            "targetSystemType": "research newsroom",
                            "expectedEvidenceClasses": ["runbooks or workflow descriptions"],
                            "comparisonQuestions": ["What is the end-to-end handoff sequence from signal detection to published output?"],
                            "evidenceRubric": [{"key": "autonomy-scope"}],
                            "referenceLineageIds": ["reference-1"],
                        },
                    },
                    "doctrine": [{"scope": "publication", "kind": "mission", "label": "Editorial Mission", "slug": "editorial-doctrine-mission", "body": ["Study publication systems as operational systems."]}],
                    "targets": [{"kind": "category", "id": "category-1", "lineageId": "category-1", "label": "Automated Scientific Discovery", "detail": "requests_work_on"}],
                    "events": [{"id": "assignment-event-1", "assignmentId": "assignment-live-123", "assignmentTypeKey": "research.edition-candidate", "queueKey": "edition:edition-2026-05-16:desk:automated-scientific-discovery:lane:reporting", "eventType": "created", "createdAt": "2026-05-16T12:00:00Z"}],
                }
            ),
        )

        item = result["item"]
        self.assertEqual(item["id"], "assignment-live-123")
        self.assertEqual(item["type"], "assignment")
        self.assertEqual(item["status"], "dispatched")
        self.assertEqual(item["section"], "automated-scientific-discovery")
        assignment = item["editorial"]["newsroom"]["assignment"]
        self.assertEqual(assignment["deskCategoryKey"], "automated-scientific-discovery")
        self.assertEqual(assignment["deskCategoryLineageId"], "category-1")
        self.assertEqual(assignment["focusCategoryKey"], "agent-workflow")
        self.assertEqual(assignment["focusCategoryTitle"], "Agent Workflow")
        self.assertEqual(assignment["contextProfile"], "reporting")
        self.assertEqual(assignment["contextTokenBudget"], 4000)
        self.assertEqual(assignment["contextSources"], ["doctrine", "focus-category", "desk-memory", "fresh-evidence"])
        self.assertEqual(assignment["researchTrackKey"], "automated-publication-systems")
        self.assertEqual(assignment["researchLens"], "agent-workflow")
        self.assertEqual(assignment["targetSystemType"], "research newsroom")
        self.assertEqual(assignment["expectedEvidenceClasses"], ["runbooks or workflow descriptions"])
        self.assertEqual(assignment["comparisonQuestions"][0], "What is the end-to-end handoff sequence from signal detection to published output?")
        self.assertEqual(assignment["liveAssignment"]["status"], "open")
        self.assertEqual(assignment["liveAssignment"]["doctrine"][0]["scope"], "publication")
        self.assertEqual(item["layout"]["source"], "newsroom-live-assignment")

    def test_lambda_auth_header_matches_authoring_lane(self):
        token = papyrus_newsroom._lambda_auth_token("Bearer abc.def.ghi")
        self.assertEqual(token, "PapyrusJwt abc.def.ghi")

    def test_biblicus_tool_resolves_config_and_uses_project_venv(self):
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(papyrus_newsroom.subprocess, "run", return_value=completed) as run:
            result = papyrus_newsroom.biblicus_steering_artifacts("AI-ML-research")

        self.assertEqual(result["status"], "ok")
        command = run.call_args.args[0]
        self.assertEqual(command[1:4], ["-m", "biblicus", "steering"])
        self.assertIn("/Users/ryan/Projects/Biblicus/.venv/bin/python", command[0])
        self.assertIn("/Users/ryan/Projects/Biblicus/corpora/AI-ML-research", command)

    def test_semantic_key_builders_match_relation_indexes(self):
        self.assertEqual(
            papyrus_semantic.semantic_state_key("reference", "reference-1"),
            "reference#reference-1#current",
        )
        self.assertEqual(
            papyrus_semantic.semantic_object_subject_state_key("category", "category-1", "reference"),
            "category#category-1#current#reference",
        )
        self.assertEqual(
            papyrus_semantic.semantic_predicate_object_state_key("classified_as", "category", "category-1"),
            "classified_as#category#category-1#current",
        )

    def test_semantic_client_resolves_papyrus_uri_by_lineage(self):
        def fake_graphql(query, variables):
            if "getReference" in query:
                self.assertEqual(variables["id"], "reference-1")
                return {"getReference": None}
            if "listReferencesByLineageAndVersion" in query:
                self.assertEqual(variables["lineageId"], "reference-1")
                return {
                    "listReferencesByLineageAndVersion": {
                        "items": [
                            {"id": "reference-1-v1", "lineageId": "reference-1", "versionNumber": 1, "versionState": "current", "title": "Reference 1"}
                        ],
                        "nextToken": None,
                    }
                }
            raise AssertionError(f"Unexpected query {query}")

        client = papyrus_semantic.PapyrusSemanticClient(fake_graphql)
        resolved = client.resolve_uri("papyrus://reference/reference-1")

        self.assertEqual(resolved["kind"], "reference")
        self.assertEqual(resolved["lineageId"], "reference-1")
        self.assertEqual(resolved["object"]["id"], "reference-1-v1")

    def test_reference_quality_plan_uses_score_and_supersedes_stale_relation(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "corpusId": "knowledge-corpus-test",
            "externalItemId": "item-a",
            "title": "Reference A",
            "importRunId": "import-1",
        }

        class FakeSemantic:
            def get_semantic_object(self, _kind, _object_id):
                return {"object": {"id": _object_id}}

            def list_outgoing(self, _kind, _lineage_id):
                return {
                    "relations": [
                        {
                            "id": "quality-old",
                            "relationState": "current",
                            "relationTypeKey": "quality_rating_is",
                            "predicate": "quality_rating_is",
                            "objectLineageId": "semantic-node-quality-rating-2-star",
                            "score": 2,
                            "metadata": "{}",
                        }
                    ]
                }

        plan = reference_curation_signals.build_reference_quality_plan(
            reference=reference,
            rating=4,
            note="strong source",
            now="2026-05-19T12:00:00Z",
            semantic_client=FakeSemantic(),
        )

        self.assertEqual(plan["action"], "create")
        create, update = plan["records"]
        self.assertEqual(update["action"], "update")
        self.assertEqual(update["input"]["relationState"], "superseded")
        self.assertEqual(create["input"]["relationTypeKey"], "quality_rating_is")
        self.assertEqual(create["input"]["objectLineageId"], "semantic-node-quality-rating-4-star")
        self.assertEqual(create["input"]["score"], 4)

    def test_reference_summary_plan_writes_reference_metadata_attachment(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "corpusId": "knowledge-corpus-test",
            "externalItemId": "item-a",
            "title": "Reference A",
            "importRunId": "import-1",
        }

        class FakeSemantic:
            def list_incoming(self, _kind, _lineage_id):
                return {"relations": []}

        plan = reference_curation_signals.build_reference_summary_plan(
            reference=reference,
            max_tokens=100,
            summary_text="A short summary.",
            source_text="Long source text.",
            model="manual",
            now="2026-05-19T12:00:00Z",
            semantic_client=FakeSemantic(),
        )

        self.assertEqual(plan["action"], "create")
        self.assertEqual(plan["records"][0]["modelName"], "ModelAttachment")
        metadata = json.loads(plan["records"][0]["body"])
        self.assertEqual(metadata["summary"], "A short summary.")
        self.assertEqual(metadata["summary_resolution"]["summaryTokenBudget"], 100)

    def test_publication_doctrine_context_loads_mission_and_policy(self):
        def fake_graphql(_query, variables):
            slug = variables["slug"]
            body_by_slug = {
                "editorial-doctrine-mission": ["Study publication systems as operational systems."],
                "editorial-doctrine-policy": ["Published stories should distinguish evidence from speculation."],
            }
            return {
                "itemBySlug": {
                    "items": [
                        {
                            "id": f"item-{slug}-v1",
                            "lineageId": f"item-{slug}",
                            "versionNumber": 1,
                            "versionState": "current",
                            "type": "doctrine",
                            "status": "private",
                            "slug": slug,
                            "title": "Editorial Mission" if "mission" in slug else "Editorial Policy",
                            "body": body_by_slug[slug],
                            "editorial": json.dumps({"kind": "mission" if "mission" in slug else "policy"}),
                        }
                    ],
                    "nextToken": None,
                }
            }

        context = reference_curation_signals.load_publication_doctrine_context(graphql_func=fake_graphql)

        self.assertEqual(context["status"], "loaded")
        self.assertEqual(context["scope"], "publication")
        self.assertEqual(context["policyUse"], "context_only_not_reference_rubric")
        self.assertEqual(context["slugs"], ["editorial-doctrine-mission", "editorial-doctrine-policy"])
        self.assertTrue(context["contentHash"])

    def test_reference_summarization_procedure_contains_source_voice_guidance(self):
        source = (REPO_ROOT / "procedures" / "newsroom" / "reference_summarization.tac").read_text()
        self.assertIn("State what the source says directly", source)
        self.assertIn('Do not use referential lead-ins such as:', source)
        self.assertIn('"This paper..."', source)
        self.assertIn("Publication Context:", source)
        self.assertIn("should not be treated as rules that the Reference itself must satisfy", source)

    def test_generate_summary_dispatches_cloud_procedure_alias(self):
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_summarization_cloud_procedure",
            return_value={
                "mode": "reference_summary",
                "summary_text": "Summarized source voice text.",
                "prompt_version": "reference-summary-v3-source-voice",
                "model": "gpt-5.4-mini",
            },
        ) as runner:
            result = reference_curation_signals.generate_summary(
                "Source text.",
                max_tokens=100,
                model="gpt-5.4-mini",
                reference={"title": "Reference A", "sourceUri": "https://example.test/ref"},
                doctrine_context={"records": []},
            )
        self.assertEqual(result["summary_text"], "Summarized source voice text.")
        self.assertEqual(runner.call_args.kwargs["alias"], "references.summarize")

    def test_generate_outcome_summary_dispatches_cloud_procedure_alias(self):
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_summarization_cloud_procedure",
            return_value={
                "mode": "outcome_summary",
                "summary_text": "Outcome-focused source voice summary.",
                "prompt_version": "reference-title-subtitle-summary-v2-source-voice",
                "model": "gpt-5.4-mini",
            },
        ) as runner:
            result = reference_curation_signals.generate_outcome_summary(
                "Source text.",
                reference={"title": "Reference A", "sourceUri": "https://example.test/ref", "mediaType": "application/pdf"},
                title="Known title",
                subtitle="Known subtitle",
                model="gpt-5.4-mini",
            )
        self.assertEqual(result["summary_text"], "Outcome-focused source voice summary.")
        self.assertEqual(runner.call_args.kwargs["alias"], "references.title-subtitle.resolve")

    def test_generate_summary_surfaces_missing_procedure_remediation(self):
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_summarization_cloud_procedure",
            side_effect=ValueError(
                "Missing required cloud procedure 'newsroom.reference.summarization'. "
                "Run poetry run papyrus procedures seed-required --apply to preload standard procedures."
            ),
        ):
            with self.assertRaisesRegex(ValueError, "papyrus procedures seed-required --apply"):
                reference_curation_signals.generate_summary(
                    "Source text.",
                    max_tokens=100,
                    model="gpt-5.4-mini",
                    reference={"title": "Reference A", "sourceUri": "https://example.test/ref"},
                )

    def test_summary_metadata_records_doctrine_context(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "corpusId": "knowledge-corpus-test",
            "externalItemId": "item-a",
            "title": "Reference A",
            "importRunId": "import-1",
        }

        class FakeSemantic:
            def list_incoming(self, _kind, _lineage_id):
                return {"relations": []}

        doctrine_context = {
            "status": "loaded",
            "scope": "publication",
            "policyUse": "context_only_not_reference_rubric",
            "slugs": ["editorial-doctrine-mission", "editorial-doctrine-policy"],
            "records": [],
            "contentHash": "hash-1",
            "warnings": [],
        }
        plan = reference_curation_signals.build_reference_summary_plan(
            reference=reference,
            max_tokens=100,
            summary_text="A short summary.",
            source_text="Long source text.",
            model="gpt-5.4-mini",
            doctrine_context=doctrine_context,
            now="2026-05-19T12:00:00Z",
            semantic_client=FakeSemantic(),
        )

        self.assertEqual(plan["metadata"]["promptVersion"], "reference-summary-v3-source-voice")
        self.assertEqual(plan["metadata"]["doctrineContextStatus"], "loaded")
        self.assertEqual(plan["metadata"]["doctrineScope"], "publication")
        self.assertEqual(plan["metadata"]["policyUse"], "context_only_not_reference_rubric")
        self.assertEqual(plan["metadata"]["doctrineSlugs"], ["editorial-doctrine-mission", "editorial-doctrine-policy"])
        self.assertEqual(plan["metadata"]["doctrineContentHash"], "hash-1")

    def test_manual_summary_metadata_records_doctrine_not_used(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "corpusId": "knowledge-corpus-test",
            "externalItemId": "item-a",
            "title": "Reference A",
            "importRunId": "import-1",
        }

        class FakeSemantic:
            def list_incoming(self, _kind, _lineage_id):
                return {"relations": []}

        plan = reference_curation_signals.build_reference_summary_plan(
            reference=reference,
            max_tokens=100,
            summary_text="Manual summary.",
            model="manual",
            doctrine_context=reference_curation_signals.manual_summary_doctrine_context(),
            now="2026-05-19T12:00:00Z",
            semantic_client=FakeSemantic(),
        )

        self.assertEqual(plan["metadata"]["doctrineContextStatus"], "not_used_manual_summary")
        self.assertEqual(plan["metadata"]["policyUse"], "context_only_not_reference_rubric")

    def test_quality_assessment_prompt_includes_doctrine_but_excludes_policy_as_rubric(self):
        context = {
            "status": "loaded",
            "scope": "publication",
            "policyUse": "context_only_not_reference_rubric",
            "slugs": ["editorial-doctrine-mission", "editorial-doctrine-policy"],
            "records": [
                {"slug": "editorial-doctrine-mission", "label": "Editorial Mission", "body": ["Study operational publication systems."]},
                {"slug": "editorial-doctrine-policy", "label": "Editorial Policy", "body": ["Published items should be evidence-backed."]},
            ],
            "contentHash": "hash-1",
            "warnings": [],
        }
        prompt = reference_curation_signals.build_quality_assessment_prompt(
            "Reference source text.",
            reference={"title": "Reference A", "sourceUri": "https://example.test/ref"},
            rubric="Rate 1 to 5 based on source quality.",
            doctrine_context=context,
        )

        self.assertIn("Study operational publication systems.", prompt)
        self.assertIn("Do not score the Reference by whether it complies with publication policies.", prompt)
        self.assertIn("Rate 1 to 5 based on source quality.", prompt)

    def test_quality_assessment_result_normalizes_structured_output(self):
        response_payload = {
            "output_text": json.dumps({
                "rating": 4,
                "rationale": "Strong peer-reviewed source.",
                "evidence": ["Clear method", "Relevant findings"],
                "caveats": ["Narrow benchmark"],
            })
        }

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps(response_payload).encode("utf-8")

        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
             mock.patch("papyrus_newsroom.reference_curation_signals.urllib.request.urlopen", return_value=FakeResponse()):
            result = reference_curation_signals.generate_quality_assessment(
                "Reference source text.",
                reference={"title": "Reference A"},
                model="gpt-5.4-mini",
                doctrine_context=reference_curation_signals.manual_summary_doctrine_context(),
            )

        self.assertEqual(result["rating"], 4)
        self.assertNotIn("confidence", result)
        self.assertEqual(result["promptVersion"], "reference-quality-v1-publication-doctrine")
        self.assertEqual(result["evidence"], ["Clear method", "Relevant findings"])

    def test_title_subtitle_prompt_requires_verbatim_originals(self):
        prompt = reference_curation_signals.build_title_subtitle_prompt(
            reference={"title": "", "sourceUri": "https://example.test/paper"},
            catalog_entry={"item_id": "item-1", "metadata": {"doi": "10.1234/example"}},
            source_text="Original Paper Title\nOriginal subtitle text",
        )

        self.assertIn("Use the original title verbatim if available.", prompt)
        self.assertIn("Use the original subtitle verbatim if available.", prompt)
        self.assertIn("Do not paraphrase original titles or subtitles.", prompt)
        self.assertIn("Subtitle must be one short prose line.", prompt)
        self.assertIn("Do not use Markdown.", prompt)
        self.assertIn("Do not use bullet points.", prompt)
        self.assertIn("Do not use numbered lists.", prompt)
        self.assertIn("Do not include line breaks.", prompt)
        self.assertIn("typically 4 to 12 words.", prompt)
        self.assertIn("Avoid self-referential document framing", prompt)
        self.assertIn("concrete content signal", prompt)
        self.assertIn("You MAY mention evidence/method terms such as survey", prompt)
        self.assertIn("Good subtitle: 'Survey finds 72% of teens have used AI companions'", prompt)
        self.assertIn("Bad subtitle: 'This article reports survey results'", prompt)

    def test_subtitle_normalizer_is_trim_only(self):
        self.assertEqual(reference_curation_signals._normalize_subtitle_candidate("- First bullet"), "- First bullet")
        self.assertEqual(reference_curation_signals._normalize_subtitle_candidate("1. First bullet"), "1. First bullet")
        self.assertEqual(reference_curation_signals._normalize_subtitle_candidate("Line one\nLine two"), "Line one Line two")
        self.assertEqual(
            reference_curation_signals._normalize_subtitle_candidate("Concise prose subtitle"),
            "Concise prose subtitle",
        )
        self.assertEqual(
            reference_curation_signals._normalize_subtitle_candidate("https://phys.org/news/2025-07-quarters-teens-ai-companions.html"),
            "https://phys.org/news/2025-07-quarters-teens-ai-companions.html",
        )
        self.assertEqual(
            reference_curation_signals._normalize_subtitle_candidate("phys.org/news/2025-07-quarters-teens-ai-companions.html"),
            "phys.org/news/2025-07-quarters-teens-ai-companions.html",
        )
        self.assertEqual(reference_curation_signals._normalize_subtitle_candidate("Study"), "Study")

    def test_title_normalizer_strips_trailing_colon_source_label(self):
        self.assertEqual(
            reference_curation_signals._normalize_reference_title_candidate("Three quarters of US teens use AI companions despite risks: Study"),
            "Three quarters of US teens use AI companions despite risks",
        )

    def test_identifier_prepass_extracts_doi_and_arxiv_from_title_subtitle_without_uri(self):
        prepass = reference_curation_signals._run_identifier_prepass(
            reference={"id": "reference-1-v1", "lineageId": "reference-1", "title": ""},
            catalog_entry={
                "title": "[2408.15247] AutoGen Studio: A No-Code Developer Tool for Building and Debugging Multi-Agent Systems - arXiv",
                "subtitle": "Published draft DOI: 10.1145/1234567.8901234",
                "metadata": {},
            },
        )

        self.assertEqual(prepass["status"], "ok")
        self.assertEqual(prepass["identifiers"]["arxiv_id"], "2408.15247")
        self.assertEqual(prepass["identifiers"]["doi"], "10.1145/1234567.8901234")
        self.assertNotIn("isbn13", prepass["identifiers"])
        self.assertEqual(prepass["resolution"]["arxiv_id"]["selectedSource"], "title")
        self.assertEqual(prepass["resolution"]["doi"]["selectedSource"], "subtitle")

    def test_identifier_prepass_extracts_isbn13_only_when_isbn_marker_present(self):
        without_marker = reference_curation_signals._run_identifier_prepass(
            reference={"id": "reference-1-v1", "lineageId": "reference-1", "title": "Numbers 0306406152"},
            catalog_entry={},
        )
        with_marker = reference_curation_signals._run_identifier_prepass(
            reference={"id": "reference-1-v1", "lineageId": "reference-1", "title": "ISBN 0-306-40615-2"},
            catalog_entry={},
        )

        self.assertNotIn("isbn13", without_marker["identifiers"])
        self.assertEqual(with_marker["identifiers"]["isbn13"], "9780306406157")

    def test_identifier_prepass_prefers_metadata_identifiers_over_title_inference(self):
        prepass = reference_curation_signals._run_identifier_prepass(
            reference={
                "id": "reference-1-v1",
                "lineageId": "reference-1",
                "metadata": {
                    "identifiers": {"doi": "10.5555/accepted-doi"},
                },
            },
            catalog_entry={
                "title": "Potential alternate DOI 10.9999/weaker-doi in title",
                "metadata": {},
            },
        )

        self.assertEqual(prepass["status"], "ok")
        self.assertEqual(prepass["identifiers"]["doi"], "10.5555/accepted-doi")
        self.assertEqual(prepass["resolution"]["doi"]["selectedSource"], "metadata.identifiers")

    def test_identifier_prepass_reports_no_identifier_found(self):
        prepass = reference_curation_signals._run_identifier_prepass(
            reference={"id": "reference-1-v1", "lineageId": "reference-1", "title": "No IDs in this title"},
            catalog_entry={"metadata": {}},
        )

        self.assertEqual(prepass["status"], "no_identifier_found")
        self.assertEqual(prepass["identifiers"], {})

    def test_identifier_prepass_failure_blocks_title_subtitle_plan(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "externalItemId": "item-a",
            "title": "",
            "sourceUri": "https://example.test/ref",
            "metadata": {},
        }

        class FakeSemantic:
            pass

        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_identifier_prepass",
            return_value={
                "status": "failed",
                "failureReason": "unit-test-prepass-failure",
                "identifiers": {},
                "extracted": {},
                "resolution": {},
            },
        ):
            plan = reference_curation_signals.build_reference_title_subtitle_plan(
                reference=reference,
                web_search_enabled=False,
                now="2026-05-20T12:00:00Z",
                semantic_client=FakeSemantic(),
            )

        self.assertEqual(plan["action"], "blocked")
        self.assertEqual(plan["failureReason"], "unit-test-prepass-failure")
        self.assertEqual(plan["records"], [])

    def test_identifier_prepass_failure_blocks_summary_plan(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "externalItemId": "item-a",
            "title": "Some title",
            "sourceUri": "https://example.test/ref",
            "metadata": {},
        }
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._semantic_client",
            return_value=mock.Mock(),
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._resolve_reference",
            return_value=reference,
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_identifier_prepass",
            return_value={
                "status": "failed",
                "failureReason": "unit-test-prepass-failure",
                "identifiers": {},
                "extracted": {},
                "resolution": {},
            },
        ):
            result = reference_curation_signals.reference_summarize(
                reference_id="reference-a-v1",
                max_tokens=100,
                apply=True,
            )

        self.assertEqual(result["action"], "blocked")
        self.assertFalse(result["apply"])
        self.assertEqual(result["records"], [])
        self.assertEqual(result["failureReason"], "unit-test-prepass-failure")

    def test_reference_generate_metadata_from_extracted_text_blocks_missing_text(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "title": "Original title",
            "sourceUri": "https://example.test/ref",
        }
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._semantic_client",
            return_value=mock.Mock(),
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._resolve_reference",
            return_value=reference,
        ):
            result = reference_curation_signals.reference_generate_metadata_from_extracted_text(
                reference_id="reference-a-v1",
                extracted_text="",
                apply=False,
            )

        self.assertEqual(result["status"], "skipped_missing_text")
        self.assertEqual(result["action"], "skipped_missing_text")
        self.assertEqual(result["records"], [])
        self.assertFalse(result["apply"])

    def test_reference_generate_metadata_from_extracted_text_passes_full_context(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "title": "Original title",
            "sourceUri": "https://example.test/ref",
        }
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._semantic_client",
            return_value=mock.Mock(),
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._resolve_reference",
            return_value=reference,
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._load_reference_metadata_payload",
            return_value={},
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._biblicus_python_executable",
            return_value=pathlib.Path("/tmp/fake-biblicus-python"),
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals.subprocess.run",
        ) as run_subprocess:
            def fake_subprocess(command, **kwargs):
                task = command[command.index("--task") + 1]
                payload = json.loads(kwargs["input"])
                self.assertEqual(payload["extracted_text"], "Full extracted text body")
                self.assertEqual(payload["original_title"], "Catalog original title")
                self.assertEqual(payload["original_subtitle"], "Catalog original subtitle")
                self.assertEqual(payload["reference_title"], "Original title")
                self.assertEqual(payload["source_uri"], "https://example.test/ref")
                values = {
                    "title": "Generated title",
                    "subtitle": "Generated subtitle",
                    "summary": "Generated summary",
                }
                value = values[task]
                return mock.Mock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "task": task,
                            "value": value,
                            "prompt_version": "summarize-map-reduce-v2",
                            "model": "gpt-5.4-nano",
                            "map_reduce": {
                                "chunk_count": 1,
                                "map": [{"chunk_index": 1, "candidate": value}],
                                "reduce": {
                                    "summary" if task == "summary" else task: value,
                                    "rationale": "Reduced deterministically.",
                                },
                            },
                        }
                    ),
                    stderr="",
                )

            run_subprocess.side_effect = fake_subprocess
            result = reference_curation_signals.reference_generate_metadata_from_extracted_text(
                reference_id="reference-a-v1",
                extracted_text="Full extracted text body",
                original_title="Catalog original title",
                original_subtitle="Catalog original subtitle",
                model="gpt-5.4-nano",
                apply=False,
            )

        self.assertEqual(result["status"], "generated")
        self.assertEqual(result["generated"]["title"], "Generated title")
        self.assertEqual(result["generated"]["subtitle"], "Generated subtitle")
        self.assertEqual(result["generated"]["summary"], "Generated summary")
        self.assertEqual(run_subprocess.call_count, 3)
        called_tasks = [
            call.args[0][call.args[0].index("--task") + 1]
            for call in run_subprocess.call_args_list
        ]
        self.assertEqual(called_tasks, ["title", "subtitle", "summary"])

    def test_metadata_map_reduce_uses_biblicus_cli_output(self):
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_biblicus_summarize_map_reduce",
            return_value={
                "task": "title",
                "value": "Reduced final title",
                "prompt_version": "summarize-map-reduce-v2",
                "map_reduce": {
                    "chunk_count": 3,
                    "map": [{"chunk_index": 1}, {"chunk_index": 2}, {"chunk_index": 3}],
                    "reduce": {"title": "Reduced final title", "rationale": "Reduced all chunks."},
                },
            },
        ):
            result = reference_curation_signals._run_metadata_map_reduce(
                output_kind="title",
                reference={"id": "reference-1", "title": "Original"},
                context={
                    "extractedText": "Full extracted text body",
                    "originalTitle": "Original",
                    "originalSubtitle": "",
                },
                model="gpt-5.4-nano",
            )

        self.assertEqual(result["value"], "Reduced final title")
        self.assertEqual(result["promptVersion"], "summarize-map-reduce-v2")
        self.assertEqual(result["mapReduce"]["chunk_count"], 3)

    def test_generate_summary_from_reference_text_does_not_use_web_search(self):
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals.reference_web_search",
            side_effect=AssertionError("web search should not be used"),
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_metadata_map_reduce",
            return_value={
                "value": "Generated summary from extracted text.",
                "promptVersion": "summarize-map-reduce-v2",
                "mapReduce": {"chunk_count": 1},
            },
        ):
            result = reference_curation_signals.generate_summary_from_reference_text(
                reference={"id": "reference-1", "title": "Original"},
                extracted_text="Extracted source text body.",
                original_title="Original",
                original_subtitle="",
                model="gpt-5.4-mini",
            )

        self.assertEqual(result["summary"], "Generated summary from extracted text.")
        self.assertEqual(result["mapReduce"]["chunk_count"], 1)

    def test_title_subtitle_resolver_preserves_local_metadata_verbatim(self):
        result = reference_curation_signals.resolve_reference_title_subtitle(
            reference={"id": "reference-1-v1", "title": ""},
            catalog_entry={
                "title": "Exact Source Title",
                "metadata": {"subtitle": "Exact Source Subtitle"},
            },
            web_search_enabled=False,
            now="2026-05-20T12:00:00Z",
        )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["title"], "Exact Source Title")
        self.assertEqual(result["subtitle"], "Exact Source Subtitle")
        self.assertEqual(result["title_mode"], "original_metadata")
        self.assertEqual(result["subtitle_mode"], "original_metadata")

    def test_title_subtitle_resolver_uses_toolless_llm_when_web_search_disabled(self):
        result = reference_curation_signals.resolve_reference_title_subtitle(
            reference={"id": "reference-1-v1", "title": "Known title"},
            catalog_entry={},
            sidecar={},
            web_search_enabled=False,
            llm_toolless_resolver=lambda **_: {
                "title": "Known title",
                "subtitle": "Survey finds routine AI companion use among U.S. teens",
                "title_mode": "original_metadata",
                "subtitle_mode": "generated",
                "source_urls": [],
                "rationale": "Generated from local source context.",
            },
            llm_resolver=lambda **_: (_ for _ in ()).throw(AssertionError("web resolver should not run")),
            now="2026-05-20T12:00:00Z",
        )

        self.assertEqual(result["subtitle"], "Survey finds routine AI companion use among U.S. teens")
        self.assertEqual(result["subtitle_mode"], "generated")
        self.assertFalse(result["web_search_used"])

    def test_generated_subtitle_quality_gate_rejects_generic_or_url_values(self):
        generic = reference_curation_signals.resolve_reference_title_subtitle(
            reference={"id": "reference-1-v1", "title": "Known title"},
            catalog_entry={},
            sidecar={},
            web_search_enabled=False,
            llm_toolless_resolver=lambda **_: {
                "title": "Known title",
                "subtitle": "Study",
                "title_mode": "original_metadata",
                "subtitle_mode": "generated",
                "source_urls": [],
                "rationale": "Generated from source.",
            },
            now="2026-05-20T12:00:00Z",
        )
        self.assertEqual(generic["subtitle"], "")
        self.assertEqual(generic["subtitle_mode"], "unresolved")
        self.assertTrue(any("generic one-word label" in warning for warning in generic.get("warnings", [])))

        url_like = reference_curation_signals.resolve_reference_title_subtitle(
            reference={"id": "reference-1-v1", "title": "Known title"},
            catalog_entry={},
            sidecar={},
            web_search_enabled=False,
            llm_toolless_resolver=lambda **_: {
                "title": "Known title",
                "subtitle": "https://phys.org/news/2025-07-quarters-teens-ai-companions.html",
                "title_mode": "original_metadata",
                "subtitle_mode": "generated",
                "source_urls": [],
                "rationale": "Generated from source.",
            },
            now="2026-05-20T12:00:00Z",
        )
        self.assertEqual(url_like["subtitle"], "")
        self.assertEqual(url_like["subtitle_mode"], "unresolved")
        self.assertTrue(any("looks like URL" in warning for warning in url_like.get("warnings", [])))

    def test_generated_subtitle_allows_substantive_survey_wording(self):
        result = reference_curation_signals.resolve_reference_title_subtitle(
            reference={"id": "reference-1-v1", "title": "Known title"},
            catalog_entry={},
            sidecar={},
            web_search_enabled=False,
            llm_toolless_resolver=lambda **_: {
                "title": "Known title",
                "subtitle": "Survey finds frequent AI companion use among U.S. teens",
                "title_mode": "original_metadata",
                "subtitle_mode": "generated",
                "source_urls": [],
                "rationale": "Generated from source.",
            },
            now="2026-05-20T12:00:00Z",
        )

        self.assertEqual(result["subtitle"], "Survey finds frequent AI companion use among U.S. teens")
        self.assertEqual(result["subtitle_mode"], "generated")

    def test_non_generated_subtitle_quality_gate_rejects_generic_pilot_study(self):
        self.assertEqual(
            reference_curation_signals._non_generated_subtitle_quality_issue(
                "a pilot study",
                subtitle_mode="original_web_metadata",
            ),
            "generic pilot-study subtitle",
        )

    def test_title_subtitle_plan_updates_title_and_metadata_attachment(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "externalItemId": "item-a",
            "title": "",
            "sourceUri": "https://example.test/ref",
            "metadata": {},
        }

        class FakeSemantic:
            pass

        with mock.patch(
            "papyrus_newsroom.reference_curation_signals.resolve_reference_title_subtitle",
            return_value={
                "status": "resolved",
                "title": "Exact Source Title",
                "subtitle": "Exact Source Subtitle",
                "title_mode": "original_web_metadata",
                "subtitle_mode": "original_web_metadata",
                "source": "html_metadata",
                "model": "gpt-5.4-mini",
                "web_search_used": False,
                "source_urls": ["https://example.test/ref"],
                "rationale": "Resolved from metadata.",
                "summary": "This work reports the main finding and why it matters.",
                "summary_resolution": {
                    "summaryTokenBudget": 500,
                    "actualTokenEstimate": 20,
                    "model": "gpt-5.4-mini",
                    "promptVersion": "reference-title-subtitle-summary-v2-source-voice",
                    "source": "llm_outcome_summary",
                    "source_urls": ["https://example.test/ref"],
                    "run_id": "run-1",
                    "resolved_at": "2026-05-20T12:00:00Z",
                    "rationale": "Outcome summary generated from source text.",
                },
                "run_id": "run-1",
                "resolved_at": "2026-05-20T12:00:00Z",
                "prompt_version": "",
                "warnings": [],
            },
        ):
            plan = reference_curation_signals.build_reference_title_subtitle_plan(
                reference=reference,
                web_search_enabled=False,
                now="2026-05-20T12:00:00Z",
                semantic_client=FakeSemantic(),
            )

        self.assertEqual(plan["action"], "update")
        self.assertEqual(plan["records"][0]["modelName"], "ModelAttachment")
        metadata = json.loads(plan["records"][0]["body"])
        self.assertEqual(metadata["title"], "Exact Source Title")
        self.assertEqual(metadata["subtitle"], "Exact Source Subtitle")
        self.assertEqual(metadata["title_subtitle_resolution"]["title_mode"], "original_web_metadata")
        self.assertNotIn("summary", metadata)
        self.assertNotIn("summary_resolution", metadata)

    def test_title_subtitle_plan_does_not_noop_when_existing_subtitle_is_url(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "externalItemId": "item-a",
            "title": "Reference title",
            "sourceUri": "https://example.test/ref",
            "metadata": {
                "subtitle": "https://example.test/path/to/article",
            },
        }

        with mock.patch(
            "papyrus_newsroom.reference_curation_signals.resolve_reference_title_subtitle",
            return_value={
                "status": "resolved",
                "title": "Reference title",
                "subtitle": "Concise informative subtitle for this reference",
                "title_mode": "original_metadata",
                "subtitle_mode": "generated",
                "source": "llm_no_web_search",
                "model": "gpt-5.4-mini",
                "web_search_used": False,
                "source_urls": ["https://example.test/ref"],
                "rationale": "Generated replacement subtitle.",
                "summary": "",
                "summary_resolution": {},
                "run_id": "run-1",
                "resolved_at": "2026-05-20T12:00:00Z",
                "warnings": [],
            },
        ):
            plan = reference_curation_signals.build_reference_title_subtitle_plan(
                reference=reference,
                web_search_enabled=False,
                now="2026-05-20T12:00:00Z",
            )

        self.assertEqual(plan["action"], "update")

    def test_title_subtitle_resolve_reports_vector_sync_surface_status(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionState": "current",
            "curationStatus": "accepted",
            "externalItemId": "item-a",
            "title": "",
            "sourceUri": "https://example.test/ref",
            "metadata": {},
        }

        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._semantic_client",
            return_value=mock.Mock(get_reference=mock.Mock(return_value={"reference": reference})),
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._read_reference_sidecar",
            return_value={},
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._read_reference_catalog_entry",
            return_value={},
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals.build_reference_title_subtitle_plan",
            return_value={
                "kind": "reference.title-subtitle.plan",
                "action": "update",
                "reference": {"id": "reference-a-v1", "lineageId": "reference-a"},
                "resolution": {"status": "resolved", "title": "Resolved Title", "subtitle": "Resolved Subtitle"},
                "records": [{"modelName": "Reference", "action": "update", "input": {"id": "reference-a-v1", "title": "Resolved Title"}}],
                "warnings": [],
            },
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._apply_plan_if_requested",
            return_value={"action": "update", "apply": True, "applied": [{"modelName": "Reference", "action": "update", "id": "reference-a-v1"}], "warnings": []},
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals.apply_title_subtitle_local_metadata",
            return_value={"updated": [{"target": "catalog"}], "errors": [], "skipped": []},
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._sync_reference_vectors",
            return_value={
                "failed": False,
                "resultsByLineageId": {"reference-a": {"updated": True, "skipped": None, "failed": None}},
                "resultsByReferenceId": {"reference-a-v1": {"updated": True, "skipped": None, "failed": None}},
            },
        ):
            result = reference_curation_signals.reference_title_subtitle_resolve(
                reference_id="reference-a-v1",
                apply=True,
            )

        self.assertTrue(result["localUpdated"])
        self.assertTrue(result["graphqlUpdated"])
        self.assertTrue(result["vectorIndexUpdated"])
        self.assertIsNone(result["vectorIndexSkipped"])
        self.assertIsNone(result["vectorIndexFailed"])

    def test_title_subtitle_resolve_marks_partial_failure_when_vector_sync_fails(self):
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._sync_reference_vectors",
            return_value={
                "failed": True,
                "message": "Vector index sync failed after GraphQL/local updates.",
                "resultsByLineageId": {"reference-a": {"updated": False, "skipped": None, "failed": "Vector index sync failed after GraphQL/local updates."}},
                "resultsByReferenceId": {"reference-a-v1": {"updated": False, "skipped": None, "failed": "Vector index sync failed after GraphQL/local updates."}},
            },
        ):
            annotated = reference_curation_signals._attach_title_subtitle_surface_statuses(
                {
                    "action": "update",
                    "apply": True,
                    "applied": [{"modelName": "Reference", "action": "update", "id": "reference-a-v1"}],
                    "localMetadata": {"updated": [{"target": "catalog"}]},
                    "warnings": [],
                },
                references=[{
                    "id": "reference-a-v1",
                    "lineageId": "reference-a",
                    "versionState": "current",
                    "curationStatus": "accepted",
                }],
                apply=True,
                vector_sync=True,
            )

        self.assertIn("vectorSync", annotated)
        self.assertIsNotNone(annotated["vectorIndexFailed"])
        self.assertTrue(annotated["partialFailure"])

    def test_catalog_title_subtitle_enrichment_writes_metadata_without_web(self):
        result = reference_curation_signals.enrich_reference_catalog_title_subtitle(
            catalog={
                "items": [
                    {
                        "item_id": "item-1",
                        "metadata": {
                            "title": "Verbatim Catalog Title",
                            "subtitle": "Verbatim Catalog Subtitle",
                            "summary": "Existing metadata summary.",
                        },
                    }
                ]
            },
            web_search=False,
        )

        item = result["catalog"]["items"][0]
        self.assertEqual(item["title"], "Verbatim Catalog Title")
        self.assertEqual(item["subtitle"], "Verbatim Catalog Subtitle")
        self.assertEqual(item["metadata"]["subtitle"], "Verbatim Catalog Subtitle")
        self.assertNotIn("summary", item)
        self.assertEqual(item["metadata"]["summary"], "Existing metadata summary.")
        self.assertEqual(item["metadata"]["title_subtitle_resolution"]["title_mode"], "original_metadata")
        self.assertNotIn("summary_resolution", item["metadata"])

    def test_biblicus_catalog_item_keeps_editorial_fields_in_metadata_only(self):
        enriched = reference_curation_signals.apply_title_subtitle_to_catalog_item(
            {
                "id": "item-1",
                "relpath": "raw/paper.pdf",
                "sha256": "abc123",
                "bytes": 10,
                "media_type": "application/pdf",
                "created_at": "2026-05-01T00:00:00Z",
                "title": "Old title",
                "metadata": {},
                "papyrus": {"legacy": True},
                "summary": "Legacy root summary",
            },
            resolution={
                "status": "resolved",
                "title": "Updated title",
                "subtitle": "Updated subtitle",
                "summary": "Updated summary",
                "title_mode": "original_metadata",
                "subtitle_mode": "original_metadata",
                "summary_mode": "original_metadata",
            },
        )

        self.assertEqual(enriched["title"], "Updated title")
        self.assertNotIn("subtitle", enriched)
        self.assertNotIn("summary", enriched)
        self.assertNotIn("papyrus", enriched)
        self.assertEqual(enriched["metadata"]["subtitle"], "Updated subtitle")
        self.assertEqual(enriched["metadata"]["summary"], "Updated summary")
        self.assertIn("papyrus", enriched["metadata"])

    def test_resolver_preserves_local_subtitle_verbatim(self):
        result = reference_curation_signals.resolve_reference_title_subtitle(
            reference={"id": "reference-1-v1", "title": "Reliable Title"},
            catalog_entry={
                "title": "Reliable Title",
                "metadata": {"subtitle": "- one\n- two", "summary": "A valid local summary."},
            },
            web_search_enabled=False,
            now="2026-05-20T12:00:00Z",
        )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["title"], "Reliable Title")
        self.assertEqual(result["subtitle"], "- one - two")
        self.assertEqual(result["subtitle_mode"], "original_metadata")
        self.assertEqual(result["summary"], "")

    def test_catalog_title_subtitle_enrichment_prefers_newest_items(self):
        result = reference_curation_signals.enrich_reference_catalog_title_subtitle(
            catalog={
                "items": [
                    {
                        "id": "older-item",
                        "created_at": "2026-01-01T00:00:00Z",
                        "title": "Older Title",
                        "metadata": {},
                    },
                    {
                        "id": "newer-item",
                        "created_at": "2026-05-20T00:00:00Z",
                        "title": "Newer Title",
                        "metadata": {},
                    },
                ]
            },
            web_search=False,
            max_count=1,
        )

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["itemKey"], "1")

    def test_catalog_only_missing_requires_title_subtitle_and_summary(self):
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals.generate_outcome_summary",
            return_value="Generated summary for only-missing test.",
        ):
            result = reference_curation_signals.enrich_reference_catalog_title_subtitle(
                catalog={
                    "items": [
                        {
                            "id": "item-1",
                            "title": "Existing Title",
                            "subtitle": "Existing Subtitle",
                            "metadata": {
                                "title": "Existing Title",
                                "subtitle": "Existing Subtitle",
                            },
                        }
                    ]
                },
                web_search=False,
                only_missing=True,
            )

        self.assertEqual(result["items"][0]["action"], "noop")

    def test_refresh_summary_updates_metadata_summary_even_with_existing_title_subtitle(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "externalItemId": "item-a",
            "title": "Existing Title",
            "sourceUri": "https://example.test/ref",
            "metadata": {
                "subtitle": "Existing Subtitle",
                "summary": "Old summary.",
                "summary_resolution": {"summaryTokenBudget": 500},
            },
        }

        class FakeSemantic:
            pass

        with mock.patch(
            "papyrus_newsroom.reference_curation_signals.resolve_reference_title_subtitle",
            return_value={
                "status": "resolved",
                "title": "Existing Title",
                "subtitle": "Existing Subtitle",
                "title_mode": "existing_reference",
                "subtitle_mode": "existing_reference_metadata",
                "source": "llm_outcome_summary",
                "model": "gpt-5.4-mini",
                "web_search_used": False,
                "source_urls": [],
                "rationale": "Summary refresh.",
                "summary": "New summary content.",
                "summary_resolution": {
                    "summaryTokenBudget": 500,
                    "actualTokenEstimate": 10,
                    "model": "gpt-5.4-mini",
                    "promptVersion": "reference-title-subtitle-summary-v2-source-voice",
                    "source": "llm_outcome_summary",
                    "source_urls": [],
                    "run_id": "run-1",
                    "resolved_at": "2026-05-20T12:00:00Z",
                    "rationale": "Refreshed summary.",
                },
                "run_id": "run-1",
                "resolved_at": "2026-05-20T12:00:00Z",
                "prompt_version": "",
                "warnings": [],
            },
        ):
            plan = reference_curation_signals.build_reference_title_subtitle_plan(
                reference=reference,
                web_search_enabled=False,
                refresh=False,
                refresh_summary=True,
                now="2026-05-20T12:00:00Z",
                semantic_client=FakeSemantic(),
            )

        self.assertEqual(plan["action"], "update")
        self.assertEqual(plan["records"][0]["modelName"], "ModelAttachment")
        metadata = json.loads(plan["records"][0]["body"])
        self.assertEqual(metadata["subtitle"], "Existing Subtitle")
        self.assertNotIn("summary", metadata)

    def test_local_title_normalization_strips_citation_wrappers(self):
        result = reference_curation_signals.resolve_reference_title_subtitle(
            reference={},
            catalog_entry={
                "title": "[2408.15247] AutoGen Studio: A No-Code Developer Tool for Building and Debugging Multi-Agent Systems - arXiv, accessed May 19, 2026,",
                "metadata": {},
            },
            sidecar={},
            web_search_enabled=False,
        )

        self.assertEqual(
            result["title"],
            "AutoGen Studio: A No-Code Developer Tool for Building and Debugging Multi-Agent Systems",
        )
        self.assertEqual(result["subtitle"], "")

    def test_title_subtitle_plan_captures_arxiv_identifier_before_title_normalization(self):
        reference = {
            "id": "reference-a-v1",
            "lineageId": "reference-a",
            "versionNumber": 1,
            "externalItemId": "item-a",
            "title": "",
            "metadata": {},
        }

        class FakeSemantic:
            pass

        plan = reference_curation_signals.build_reference_title_subtitle_plan(
            reference=reference,
            catalog_entry={
                "title": "[2408.15247] AutoGen Studio: A No-Code Developer Tool for Building and Debugging Multi-Agent Systems - arXiv",
                "metadata": {},
            },
            web_search_enabled=False,
            include_summary=False,
            now="2026-05-20T12:00:00Z",
            semantic_client=FakeSemantic(),
        )

        self.assertEqual(plan["action"], "update")
        metadata = json.loads(plan["records"][0]["body"])
        self.assertEqual(
            metadata["title"],
            "AutoGen Studio: A No-Code Developer Tool for Building and Debugging Multi-Agent Systems",
        )
        self.assertEqual(metadata["identifiers"]["arxiv_id"], "2408.15247")
        self.assertEqual(metadata["identifier_resolution"]["status"], "ok")

    def test_reference_list_status_all_does_not_filter(self):
        references = [
            {
                "id": "reference-a-v1",
                "lineageId": "reference-a",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "a",
                "title": "Accepted reference",
                "curationStatus": "accepted",
                "importedAt": "2026-05-21T00:00:00Z",
                "updatedAt": "2026-05-21T00:00:00Z",
                "sourceUri": "https://example.com/a",
                "storagePath": "corpora/AI-ML-research/a.txt",
            },
            {
                "id": "reference-b-v1",
                "lineageId": "reference-b",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "b",
                "title": "Pending reference",
                "curationStatus": "pending",
                "importedAt": "2026-05-20T00:00:00Z",
                "updatedAt": "2026-05-20T00:00:00Z",
                "sourceUri": "https://example.com/b",
                "storagePath": "corpora/AI-ML-research/b.txt",
            },
        ]
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals.list_references_by_corpus",
            return_value=references,
        ):
            result = reference_curation_signals.reference_list(
                corpus_key="AI-ML-research",
                limit=10,
                status="all",
                order="newest",
                scan_limit=1000,
            )

        self.assertEqual(result["count"], 2)
        self.assertEqual({item["curationStatus"] for item in result["items"]}, {"accepted", "pending"})

    def test_reference_list_status_filter_remains_exact(self):
        references = [
            {
                "id": "reference-a-v1",
                "lineageId": "reference-a",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "a",
                "title": "Accepted reference",
                "curationStatus": "accepted",
                "importedAt": "2026-05-21T00:00:00Z",
                "updatedAt": "2026-05-21T00:00:00Z",
                "sourceUri": "https://example.com/a",
                "storagePath": "corpora/AI-ML-research/a.txt",
            },
            {
                "id": "reference-b-v1",
                "lineageId": "reference-b",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "b",
                "title": "Pending reference",
                "curationStatus": "pending",
                "importedAt": "2026-05-20T00:00:00Z",
                "updatedAt": "2026-05-20T00:00:00Z",
                "sourceUri": "https://example.com/b",
                "storagePath": "corpora/AI-ML-research/b.txt",
            },
        ]
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals.list_references_by_corpus",
            return_value=references,
        ):
            result = reference_curation_signals.reference_list(
                corpus_key="AI-ML-research",
                limit=10,
                status="accepted",
                order="newest",
                scan_limit=1000,
            )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["id"], "reference-a-v1")

    def test_reference_list_imported_order_uses_import_timestamp(self):
        references = [
            {
                "id": "reference-new-v1",
                "lineageId": "reference-new",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "new",
                "title": "Recently imported",
                "curationStatus": "accepted",
                "importedAt": "2026-05-30T00:00:00Z",
                "sourcePublishedAt": "2020-01-01T00:00:00Z",
            },
            {
                "id": "reference-old-import-v1",
                "lineageId": "reference-old-import",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "old-import",
                "title": "Older import, newer publication",
                "curationStatus": "accepted",
                "importedAt": "2026-05-01T00:00:00Z",
                "sourcePublishedAt": "2026-05-29T00:00:00Z",
            },
        ]
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals.list_references_by_newsroom_feed_imported",
            return_value=references,
        ):
            imported_result = reference_curation_signals.reference_list(
                corpus_key="AI-ML-research",
                limit=10,
                status="all",
                order="imported",
                scan_limit=1000,
            )
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals.list_references_by_corpus",
            return_value=references,
        ):
            published_result = reference_curation_signals.reference_list(
                corpus_key="AI-ML-research",
                limit=10,
                status="all",
                order="published",
                scan_limit=1000,
            )

        self.assertEqual(imported_result["items"][0]["id"], "reference-new-v1")
        self.assertEqual(published_result["items"][0]["id"], "reference-old-import-v1")

    def test_reference_curate_recent_all_includes_undated_and_old_references(self):
        references = [
            {
                "id": "reference-old-v1",
                "lineageId": "reference-old",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-demo",
                "externalItemId": "old",
                "title": "Old",
                "curationStatus": "accepted",
                "importedAt": "2020-01-01T00:00:00Z",
            },
            {
                "id": "reference-undated-v1",
                "lineageId": "reference-undated",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-demo",
                "externalItemId": "undated",
                "title": "Undated",
                "curationStatus": "accepted",
            },
        ]
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals.list_references_by_corpus",
            return_value=references,
        ):
            selected = reference_curation_signals._select_references_for_curate_recent(
                corpus_key="demo-corpus",
                since_dt=None,
                curate_all=True,
                max_count=0,
                scan_limit=100,
            )
        self.assertEqual(len(selected), 2)

    def test_reference_curate_recent_defaults_to_48h_all_statuses(self):
        references = [
            {
                "id": "reference-new-v1",
                "lineageId": "reference-new",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "new",
                "title": "Newest",
                "curationStatus": "pending",
                "importedAt": "2026-05-22T11:00:00Z",
            },
            {
                "id": "reference-mid-v1",
                "lineageId": "reference-mid",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "mid",
                "title": "Within 48 hours",
                "curationStatus": "accepted",
                "importedAt": "2026-05-21T13:00:00Z",
            },
            {
                "id": "reference-old-v1",
                "lineageId": "reference-old",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "old",
                "title": "Older than 48 hours",
                "curationStatus": "accepted",
                "importedAt": "2026-05-20T08:00:00Z",
            },
        ]
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._now",
            return_value="2026-05-22T12:00:00Z",
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals.list_references_by_corpus",
            return_value=references,
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_identifier_stage",
            return_value=(
                {"status": "ok", "identifiers": {"doi": "10.1/test"}},
                {"status": "ok", "success": True, "action": "run", "failureReason": ""},
            ),
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_title_stage",
            return_value={"status": "update", "success": True, "action": "update", "failureReason": ""},
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_summary_stage",
            return_value={"status": "create", "success": True, "action": "create", "failureReason": ""},
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_quality_stage",
            return_value={"status": "create", "success": True, "action": "create", "failureReason": ""},
        ):
            result = reference_curation_signals.reference_curate_recent(
                corpus_key="AI-ML-research",
                apply=False,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["selectedCount"], 2)
        self.assertEqual({item["reference"]["curationStatus"] for item in result["items"]}, {"pending", "accepted"})

    def test_reference_curate_recent_reference_ids_override_window_selection(self):
        reference = {
            "id": "reference-explicit-v1",
            "lineageId": "reference-explicit",
            "versionNumber": 1,
            "corpusId": "knowledge-corpus-ai-ml-research",
            "externalItemId": "explicit",
            "title": "Explicit selection",
            "curationStatus": "pending",
            "importedAt": "2026-05-10T08:00:00Z",
        }
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._now",
            return_value="2026-05-22T12:00:00Z",
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._resolve_reference",
            return_value=reference,
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_identifier_stage",
            return_value=(
                {"status": "ok", "identifiers": {"doi": "10.1/test"}},
                {"status": "ok", "success": True, "action": "run", "failureReason": ""},
            ),
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_title_stage",
            return_value={"status": "noop", "success": True, "action": "noop", "failureReason": ""},
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_summary_stage",
            return_value={"status": "noop", "success": True, "action": "noop", "failureReason": ""},
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_quality_stage",
            return_value={"status": "noop", "success": True, "action": "noop", "failureReason": ""},
        ):
            result = reference_curation_signals.reference_curate_recent(
                corpus_key="AI-ML-research",
                reference_ids=["reference-explicit-v1"],
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["selectedCount"], 1)
        self.assertEqual(result["items"][0]["reference"]["id"], "reference-explicit-v1")

    def test_reference_curate_recent_enforces_stage_order(self):
        reference = {
            "id": "reference-order-v1",
            "lineageId": "reference-order",
            "versionNumber": 1,
            "corpusId": "knowledge-corpus-ai-ml-research",
            "externalItemId": "order",
            "title": "Order check",
            "curationStatus": "accepted",
            "importedAt": "2026-05-22T11:00:00Z",
        }
        call_order = []

        def identifier_stage(**kwargs):
            call_order.append("identifier")
            return (
                {"status": "ok", "identifiers": {"doi": "10.1/test"}},
                {"status": "ok", "success": True, "action": "run", "failureReason": ""},
            )

        def title_stage(**kwargs):
            call_order.append("title")
            return {"status": "update", "success": True, "action": "update", "failureReason": ""}

        def summary_stage(**kwargs):
            call_order.append("summary")
            return {"status": "create", "success": True, "action": "create", "failureReason": ""}

        def quality_stage(**kwargs):
            call_order.append("quality")
            return {"status": "create", "success": True, "action": "create", "failureReason": ""}

        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._now",
            return_value="2026-05-22T12:00:00Z",
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals.list_references_by_corpus",
            return_value=[reference],
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_identifier_stage",
            side_effect=identifier_stage,
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_title_stage",
            side_effect=title_stage,
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_summary_stage",
            side_effect=summary_stage,
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_quality_stage",
            side_effect=quality_stage,
        ):
            result = reference_curation_signals.reference_curate_recent(
                corpus_key="AI-ML-research",
                apply=False,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(call_order, ["identifier", "title", "summary", "quality"])

    def test_reference_curate_recent_returns_partial_failure_when_any_reference_fails(self):
        references = [
            {
                "id": "reference-pass-v1",
                "lineageId": "reference-pass",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "pass",
                "title": "Pass",
                "curationStatus": "accepted",
                "importedAt": "2026-05-22T11:00:00Z",
            },
            {
                "id": "reference-fail-v1",
                "lineageId": "reference-fail",
                "versionNumber": 1,
                "corpusId": "knowledge-corpus-ai-ml-research",
                "externalItemId": "fail",
                "title": "Fail",
                "curationStatus": "accepted",
                "importedAt": "2026-05-22T10:00:00Z",
            },
        ]
        identifier_stage_outputs = [
            (
                {"status": "ok", "identifiers": {"doi": "10.1/pass"}},
                {"status": "ok", "success": True, "action": "run", "failureReason": ""},
            ),
            (
                {"status": "failed", "failureReason": "prepass failure", "identifiers": {}},
                {"status": "failed", "success": False, "action": "run", "failureReason": "prepass failure"},
            ),
        ]
        with mock.patch(
            "papyrus_newsroom.reference_curation_signals._now",
            return_value="2026-05-22T12:00:00Z",
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals.list_references_by_corpus",
            return_value=references,
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_identifier_stage",
            side_effect=identifier_stage_outputs,
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_title_stage",
            side_effect=[
                {"status": "update", "success": True, "action": "update", "failureReason": ""},
                {"status": "skipped", "success": False, "action": "skip", "failureReason": "identifier prepass failed"},
            ],
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_summary_stage",
            side_effect=[
                {"status": "create", "success": True, "action": "create", "failureReason": ""},
                {"status": "skipped", "success": False, "action": "skip", "failureReason": "identifier prepass failed"},
            ],
        ), mock.patch(
            "papyrus_newsroom.reference_curation_signals._run_reference_curation_quality_stage",
            side_effect=[
                {"status": "create", "success": True, "action": "create", "failureReason": ""},
                {"status": "skipped", "success": False, "action": "skip", "failureReason": "identifier prepass failed"},
            ],
        ):
            result = reference_curation_signals.reference_curate_recent(
                corpus_key="AI-ML-research",
                apply=False,
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["degraded"])
        self.assertEqual(result["summary"]["failedCount"], 1)

    def test_reference_curate_recent_resume_skips_completed_successful_stages(self):
        reference = {
            "id": "reference-resume-v1",
            "lineageId": "reference-resume",
            "versionNumber": 1,
            "corpusId": "knowledge-corpus-ai-ml-research",
            "externalItemId": "resume",
            "title": "Resume",
            "curationStatus": "accepted",
            "importedAt": "2026-05-22T11:00:00Z",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = pathlib.Path(tmpdir) / "manifest.json"
            with mock.patch(
                "papyrus_newsroom.reference_curation_signals._now",
                return_value="2026-05-22T12:00:00Z",
            ), mock.patch(
                "papyrus_newsroom.reference_curation_signals.list_references_by_corpus",
                return_value=[reference],
            ), mock.patch(
                "papyrus_newsroom.reference_curation_signals._resolve_reference",
                return_value=reference,
            ), mock.patch(
                "papyrus_newsroom.reference_curation_signals._reference_curation_manifest_path",
                return_value=manifest_path,
            ), mock.patch(
                "papyrus_newsroom.reference_curation_signals._run_identifier_prepass",
                return_value={"status": "ok", "failureReason": "", "identifiers": {"doi": "10.1/resume"}},
            ), mock.patch(
                "papyrus_newsroom.reference_curation_signals.reference_title_subtitle_resolve",
                return_value={"action": "update"},
            ) as title_mock, mock.patch(
                "papyrus_newsroom.reference_curation_signals.reference_summarize",
                return_value={"action": "create"},
            ) as summary_mock, mock.patch(
                "papyrus_newsroom.reference_curation_signals.reference_quality_assess",
                return_value={"action": "create"},
            ) as quality_mock:
                first = reference_curation_signals.reference_curate_recent(
                    corpus_key="AI-ML-research",
                    apply=False,
                )
                second = reference_curation_signals.reference_curate_recent(
                    corpus_key="AI-ML-research",
                    apply=False,
                    resume=str(manifest_path),
                )

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertEqual(title_mock.call_count, 1)
            self.assertEqual(summary_mock.call_count, 1)
            self.assertEqual(quality_mock.call_count, 1)
            self.assertEqual(second["items"][0]["stages"]["identifierPrepass"]["status"], "reused")
            self.assertEqual(second["items"][0]["stages"]["titleSubtitle"]["status"], "reused")
            self.assertEqual(second["items"][0]["stages"]["summary"]["status"], "reused")
            self.assertEqual(second["items"][0]["stages"]["quality"]["status"], "reused")

    def test_placeholder_title_is_not_written(self):
        result = reference_curation_signals.resolve_reference_title_subtitle(
            reference={},
            catalog_entry={},
            sidecar={},
            web_search_enabled=True,
            llm_resolver=lambda **_: {
                "title": "Unresolved",
                "subtitle": "ScienceDirect article metadata unavailable",
                "title_mode": "unresolved",
                "subtitle_mode": "generated_fallback",
                "source_urls": [],
                "rationale": "Could not verify.",
                "promptVersion": "test",
                "model": "gpt-5.4-mini",
            },
        )

        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["title"], "")
        self.assertEqual(result["subtitle"], "ScienceDirect article metadata unavailable")

    def test_semantic_neighbors_and_walk_use_graph_indexes(self):
        calls = []

        def fake_graphql(query, variables):
            calls.append(variables)
            if "listSemanticRelationsBySubjectState" in query:
                return {
                    "listSemanticRelationsBySubjectState": {
                        "items": [
                            {
                                "id": "rel-1",
                                "relationState": "current",
                                "predicate": "classified_as",
                                "subjectKind": "reference",
                                "subjectId": "ref-v1",
                                "subjectLineageId": "ref",
                                "objectKind": "category",
                                "objectId": "cat-v1",
                                "objectLineageId": "cat",
                                "subjectStateKey": "reference#ref#current",
                                "objectStateKey": "category#cat#current",
                                "predicateObjectStateKey": "classified_as#category#cat#current",
                            }
                        ],
                        "nextToken": None,
                    }
                }
            if "listSemanticRelationsByObjectState" in query:
                return {"listSemanticRelationsByObjectState": {"items": [], "nextToken": None}}
            raise AssertionError(f"Unexpected query {query}")

        client = papyrus_semantic.PapyrusSemanticClient(fake_graphql)
        neighbors = client.neighbors("reference", "ref")
        self.assertEqual(neighbors["neighborRefs"], [{"kind": "category", "lineageId": "cat", "id": "cat-v1"}])
        walked = client.walk("reference", "ref", depth=1)
        self.assertIn({"kind": "category", "lineageId": "cat"}, walked["nodes"])
        self.assertEqual(calls[0]["subjectStateKey"], "reference#ref#current")

    def test_signal_trend_report_scores_recent_accepted_references(self):
        result = papyrus_coverage_theme.signals_trend_report(
            corpus_key="AI-ML-research",
            topic="AI in video games",
            coverage_key="coverage.ai-in-video-games",
            sections=["culture", "methods"],
            references=[
                {
                    "id": "reference-ai-games-1",
                    "lineageId": "reference-ai-games-1",
                    "versionState": "current",
                    "corpusId": "knowledge-corpus-ai-ml-research",
                    "title": "AI tools reshape video game design workflows",
                    "sourceUri": "https://example.com/ai-games",
                    "sourcePublishedAt": "2026-05-20T12:00:00Z",
                    "curationStatus": "accepted",
                },
                {
                    "id": "reference-ai-games-2",
                    "lineageId": "reference-ai-games-2",
                    "versionState": "current",
                    "corpusId": "knowledge-corpus-ai-ml-research",
                    "title": "Studios test generative NPC behavior in games",
                    "sourceUri": "https://studio.example/npc",
                    "sourcePublishedAt": "2026-05-19T12:00:00Z",
                    "curationStatus": "accepted",
                },
            ],
            semantic_nodes=[],
            now="2026-05-21T12:00:00Z",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["signals"][0]["coverageKey"], "coverage.ai-in-video-games")
        self.assertEqual(result["signals"][0]["acceptedEvidenceCount"], 2)
        self.assertIn("arts", result["signals"][0]["sectionFit"])
        self.assertFalse(any(record["modelName"] in {"Item", "EditionItem"} for record in result["records"]))
        self.assertEqual(result["records"][0]["input"]["messageKind"], "edition_signal_report")
        evidence_relations = [
            record for record in result["records"]
            if record["modelName"] == "SemanticRelation" and record["input"]["relationTypeKey"] == "uses_evidence"
        ]
        self.assertEqual(len(evidence_relations), 2)

    def _concept_report_fixture(self):
        references = [
            {
                "id": "reference-1-v1",
                "lineageId": "reference-1",
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "title": "AI agents in simulation pipelines",
                "sourceUri": "https://example.com/agents-sim",
                "sourcePublishedAt": "2026-05-20T12:00:00Z",
                "curationStatus": "accepted",
            },
            {
                "id": "reference-2-v1",
                "lineageId": "reference-2",
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "title": "Agent orchestration in production",
                "sourceUri": "https://studio.example/orchestration",
                "sourcePublishedAt": "2026-05-19T12:00:00Z",
                "curationStatus": "accepted",
            },
            {
                "id": "reference-3-v1",
                "lineageId": "reference-3",
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "title": "Reinforcement learning in game simulation",
                "sourceUri": "https://research.example/rl-sim",
                "sourcePublishedAt": "2026-05-18T12:00:00Z",
                "curationStatus": "accepted",
            },
            {
                "id": "reference-4-v1",
                "lineageId": "reference-4",
                "versionState": "current",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "title": "Early signal on agent tooling",
                "sourceUri": "https://archive.example/agent-tooling",
                "sourcePublishedAt": "2026-05-08T12:00:00Z",
                "curationStatus": "accepted",
            },
        ]
        semantic_nodes = [
            {
                "id": "semantic-node-ai-agents-v1",
                "lineageId": "semantic-node-ai-agents",
                "versionState": "current",
                "status": "accepted",
                "nodeKind": "entity",
                "nodeKey": "entity.ai-agents",
                "displayName": "AI Agents",
                "corpusId": "knowledge-corpus-ai-ml-research",
            },
            {
                "id": "semantic-node-rl-v1",
                "lineageId": "semantic-node-rl",
                "versionState": "current",
                "status": "accepted",
                "nodeKind": "entity",
                "nodeKey": "entity.reinforcement-learning",
                "displayName": "Reinforcement Learning",
                "corpusId": "knowledge-corpus-ai-ml-research",
            },
            {
                "id": "semantic-node-simulation-v1",
                "lineageId": "semantic-node-simulation",
                "versionState": "current",
                "status": "accepted",
                "nodeKind": "entity",
                "nodeKey": "entity.simulation",
                "displayName": "Simulation",
                "corpusId": "knowledge-corpus-ai-ml-research",
            },
        ]
        node_by_lineage = {node["lineageId"]: node for node in semantic_nodes}

        def mention(reference_id: str, reference_lineage_id: str, concept_lineage_id: str, score: float = 1.0):
            node = node_by_lineage[concept_lineage_id]
            return papyrus_coverage_theme.semantic_relation(
                predicate="mentions",
                subject_kind="reference",
                subject_id=reference_id,
                subject_lineage_id=reference_lineage_id,
                object_kind="semanticNode",
                object_id=node["id"],
                object_lineage_id=concept_lineage_id,
                score=score,
                now="2026-05-21T12:00:00Z",
            )

        semantic_relations = [
            mention("reference-1-v1", "reference-1", "semantic-node-ai-agents", score=0.9),
            mention("reference-1-v1", "reference-1", "semantic-node-rl", score=0.8),
            mention("reference-2-v1", "reference-2", "semantic-node-ai-agents", score=0.95),
            mention("reference-3-v1", "reference-3", "semantic-node-rl", score=0.92),
            mention("reference-3-v1", "reference-3", "semantic-node-simulation", score=0.88),
            mention("reference-4-v1", "reference-4", "semantic-node-ai-agents", score=0.5),
            papyrus_coverage_theme.semantic_relation(
                predicate="broader_than",
                subject_kind="semanticNode",
                subject_id="semantic-node-rl-v1",
                subject_lineage_id="semantic-node-rl",
                object_kind="semanticNode",
                object_id="semantic-node-ai-agents-v1",
                object_lineage_id="semantic-node-ai-agents",
                score=1.0,
                now="2026-05-21T12:00:00Z",
            ),
            papyrus_coverage_theme.semantic_relation(
                predicate="broader_than",
                subject_kind="semanticNode",
                subject_id="semantic-node-rl-v1",
                subject_lineage_id="semantic-node-rl",
                object_kind="semanticNode",
                object_id="semantic-node-simulation-v1",
                object_lineage_id="semantic-node-simulation",
                score=1.0,
                now="2026-05-21T12:00:00Z",
            ),
        ]
        return {
            "references": references,
            "semantic_nodes": semantic_nodes,
            "semantic_relations": semantic_relations,
        }

    def test_concept_report_all_builds_popularity_trending_and_pagerank(self):
        fixture = self._concept_report_fixture()
        result = papyrus_coverage_theme.signals_concept_report(
            corpus_key="AI-ML-research",
            report_type="all",
            limit=3,
            trend_window_days=7,
            references=fixture["references"],
            semantic_nodes=fixture["semantic_nodes"],
            semantic_relations=fixture["semantic_relations"],
            now="2026-05-21T12:00:00Z",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "signals concept-report")
        self.assertEqual(result["reportType"], "all")
        self.assertEqual(result["popularity"][0]["conceptLineageId"], "semantic-node-ai-agents")
        self.assertEqual(result["popularity"][0]["distinctReferenceCount"], 3)
        self.assertEqual(result["trending"][0]["conceptLineageId"], "semantic-node-rl")
        self.assertEqual(result["pagerank"][0]["conceptLineageId"], "semantic-node-rl")
        self.assertFalse(any(record["modelName"] in {"Item", "EditionItem"} for record in result["records"]))
        self.assertEqual(result["records"][0]["input"]["messageKind"], "concept_report")
        self.assertEqual(result["records"][0]["input"]["messageDomain"], "analytics")
        signal_report_types = {
            str((record["input"].get("metadata") or {}).get("reportType"))
            for record in result["records"]
            if record["modelName"] == "SemanticRelation"
            and record["input"].get("relationTypeKey") == "uses_signal"
        }
        self.assertEqual(signal_report_types, {"popularity", "trending", "pagerank"})

    def test_concept_report_respects_single_report_type_selection(self):
        fixture = self._concept_report_fixture()
        result = papyrus_coverage_theme.signals_concept_report(
            corpus_key="AI-ML-research",
            report_type="popularity",
            limit=2,
            trend_window_days=7,
            references=fixture["references"],
            semantic_nodes=fixture["semantic_nodes"],
            semantic_relations=fixture["semantic_relations"],
            now="2026-05-21T12:00:00Z",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["reportType"], "popularity")
        self.assertGreaterEqual(len(result["popularity"]), 1)
        self.assertEqual(result["trending"], [])
        self.assertEqual(result["pagerank"], [])
        signal_report_types = {
            str((record["input"].get("metadata") or {}).get("reportType"))
            for record in result["records"]
            if record["modelName"] == "SemanticRelation"
            and record["input"].get("relationTypeKey") == "uses_signal"
        }
        self.assertEqual(signal_report_types, {"popularity"})

    def test_newsroom_cli_concept_report_command_outputs_all_three_reports(self):
        from papyrus_newsroom import cli as newsroom_cli

        fixture = self._concept_report_fixture()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump(
                {
                    "references": fixture["references"],
                    "semanticNodes": fixture["semantic_nodes"],
                    "semanticRelations": fixture["semantic_relations"],
                },
                handle,
            )
            handle.flush()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = newsroom_cli.main(
                    [
                        "signals",
                        "concept-report",
                        "--corpus-key",
                        "AI-ML-research",
                        "--report-type",
                        "all",
                        "--limit",
                        "3",
                        "--trend-window-days",
                        "7",
                        "--now",
                        "2026-05-21T12:00:00Z",
                        "--input",
                        handle.name,
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["command"], "signals concept-report")
        self.assertEqual(payload["reportType"], "all")
        self.assertGreaterEqual(payload["summary"]["popularityCount"], 1)
        self.assertGreaterEqual(payload["summary"]["trendingCount"], 1)
        self.assertGreaterEqual(payload["summary"]["pagerankCount"], 1)

    def test_concept_report_centrality_most_returns_highest_pagerank_concepts(self):
        fixture = self._concept_report_fixture()
        result = papyrus_coverage_theme.signals_concept_report(
            corpus_key="AI-ML-research",
            report_type="centrality",
            order="most",
            limit=3,
            references=fixture["references"],
            semantic_nodes=fixture["semantic_nodes"],
            semantic_relations=fixture["semantic_relations"],
            now="2026-05-21T12:00:00Z",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["reportType"], "centrality")
        self.assertEqual(result["order"], "most")
        self.assertGreaterEqual(len(result["centrality"]), 1)
        self.assertTrue(result["summary"]["centralityStability"]["stable"])
        # Most-central first: the concept with the most mention + ontology weight leads.
        self.assertEqual(result["centrality"][0]["metric"], "pagerankScore")
        self.assertGreaterEqual(result["centrality"][0]["score"], result["centrality"][-1]["score"])
        # Suggestion list only: never creates reader-facing records.
        self.assertFalse(any(record["modelName"] in {"Item", "EditionItem"} for record in result["records"]))

    def test_concept_report_centrality_least_returns_opposite_end_of_same_ranking(self):
        fixture = self._concept_report_fixture()
        most = papyrus_coverage_theme.signals_concept_report(
            corpus_key="AI-ML-research",
            report_type="centrality",
            order="most",
            limit=3,
            references=fixture["references"],
            semantic_nodes=fixture["semantic_nodes"],
            semantic_relations=fixture["semantic_relations"],
            now="2026-05-21T12:00:00Z",
        )
        least = papyrus_coverage_theme.signals_concept_report(
            corpus_key="AI-ML-research",
            report_type="centrality",
            order="least",
            limit=3,
            references=fixture["references"],
            semantic_nodes=fixture["semantic_nodes"],
            semantic_relations=fixture["semantic_relations"],
            now="2026-05-21T12:00:00Z",
        )

        self.assertTrue(least["ok"])
        self.assertEqual(least["order"], "least")
        self.assertTrue(least["summary"]["centralityStability"]["stable"])
        self.assertGreaterEqual(len(least["centrality"]), 1)
        # Same ranking, opposite end: least-central first, and the least end's
        # top score must not exceed the most end's top score.
        self.assertLessEqual(least["centrality"][0]["score"], most["centrality"][0]["score"])
        # The two ends together cover the full ranking without overlap at the top.
        most_ids = {concept["conceptLineageId"] for concept in most["centrality"]}
        least_ids = {concept["conceptLineageId"] for concept in least["centrality"]}
        self.assertEqual(most_ids | least_ids, {"semantic-node-ai-agents", "semantic-node-rl", "semantic-node-simulation"})

    def test_concept_report_centrality_fails_closed_on_sparse_graph(self):
        fixture = self._concept_report_fixture()
        sparse_relations = [
            relation
            for relation in fixture["semantic_relations"]
            if relation.get("relationTypeKey") != "mentions"
        ]
        # Drop every mention edge so no reference mentions any concept: the
        # concept-only subgraph has no edges that differentiate centrality.
        isolated_nodes = [node for node in fixture["semantic_nodes"] if node["lineageId"] != "semantic-node-rl"]
        sparse_relations = [
            relation
            for relation in sparse_relations
            if relation.get("subjectLineageId") not in {"semantic-node-rl"}
            and relation.get("objectLineageId") not in {"semantic-node-rl"}
        ]
        result = papyrus_coverage_theme.signals_concept_report(
            corpus_key="AI-ML-research",
            report_type="centrality",
            order="least",
            limit=3,
            references=fixture["references"],
            semantic_nodes=isolated_nodes,
            semantic_relations=sparse_relations,
            now="2026-05-21T12:00:00Z",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["centrality"], [])
        self.assertFalse(result["summary"]["centralityStability"]["stable"])
        self.assertIn("sparse", result["summary"]["centralityStability"]["reason"])
        # No invented scores, no records creating reader-facing items.
        self.assertFalse(any(record["modelName"] in {"Item", "EditionItem"} for record in result["records"]))

    def test_newsroom_cli_concept_report_centrality_least_command(self):
        from papyrus_newsroom import cli as newsroom_cli

        fixture = self._concept_report_fixture()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump(
                {
                    "references": fixture["references"],
                    "semanticNodes": fixture["semantic_nodes"],
                    "semanticRelations": fixture["semantic_relations"],
                },
                handle,
            )
            handle.flush()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = newsroom_cli.main(
                    [
                        "signals",
                        "concept-report",
                        "--corpus-key",
                        "AI-ML-research",
                        "--report-type",
                        "centrality",
                        "--order",
                        "least",
                        "--limit",
                        "3",
                        "--now",
                        "2026-05-21T12:00:00Z",
                        "--input",
                        handle.name,
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["command"], "signals concept-report")
        self.assertEqual(payload["reportType"], "centrality")
        self.assertEqual(payload["order"], "least")
        self.assertGreaterEqual(payload["summary"]["centralityCount"], 1)
        self.assertTrue(payload["summary"]["centralityStability"]["stable"])

    def test_newsroom_cli_concept_report_centrality_fails_closed_on_empty_graph(self):
        from papyrus_newsroom import cli as newsroom_cli

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump(
                {
                    "references": [
                        {
                            "id": "reference-1-v1",
                            "lineageId": "reference-1",
                            "versionState": "current",
                            "corpusId": "knowledge-corpus-ai-ml-research",
                            "title": "x",
                            "sourceUri": "https://example.com/x",
                            "curationStatus": "accepted",
                            "sourcePublishedAt": "2026-05-20T12:00:00Z",
                        }
                    ],
                    "semanticNodes": [
                        {
                            "id": "semantic-node-a-v1",
                            "lineageId": "semantic-node-a",
                            "versionState": "current",
                            "status": "accepted",
                            "nodeKind": "entity",
                            "nodeKey": "entity.a",
                            "displayName": "A",
                            "corpusId": "knowledge-corpus-ai-ml-research",
                        }
                    ],
                    "semanticRelations": [],
                },
                handle,
            )
            handle.flush()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = newsroom_cli.main(
                    [
                        "signals",
                        "concept-report",
                        "--corpus-key",
                        "AI-ML-research",
                        "--report-type",
                        "centrality",
                        "--order",
                        "least",
                        "--limit",
                        "3",
                        "--now",
                        "2026-05-21T12:00:00Z",
                        "--input",
                        handle.name,
                    ]
                )

        # An empty relations list must pass through the CLI (not collapse to
        # None and trigger a live load) and the report must fail closed.
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["reportType"], "centrality")
        self.assertEqual(payload["centrality"], [])
        self.assertFalse(payload["summary"]["centralityStability"]["stable"])

    def test_coverage_theme_plan_counts_assignments_and_avoids_items(self):
        plan = papyrus_coverage_theme.build_coverage_theme_plan(
            date="2026-05-21",
            topic="AI in video games",
            corpus_key="AI-ML-research",
            category_key="AI-ML-research",
            coverage_key="coverage.ai-in-video-games",
            sections=["culture", "methods"],
            section_budgets={"arts": 2, "methods": 1},
            run_id="coverage-theme-test",
            now="2026-05-21T12:00:00Z",
        )

        self.assertEqual(plan["summary"]["researchAssignmentCount"], 2)
        self.assertEqual(plan["summary"]["slotCount"], 3)
        self.assertEqual(plan["summary"]["reportingAssignmentCount"], 5)
        self.assertFalse(any(record["modelName"] in {"Item", "EditionItem"} for record in plan["records"]))
        forum_messages = [
            record for record in plan["records"]
            if record["modelName"] == "Message" and record["input"].get("messageKind") == "forum_post"
        ]
        self.assertGreaterEqual(len(forum_messages), 1)
        self.assertEqual(
            len([record for record in plan["records"] if record["modelName"] == "EditionSlot"]),
            3,
        )
        relation_types = {
            record["input"]["relationTypeKey"]
            for record in plan["records"]
            if record["modelName"] == "SemanticRelation"
        }
        self.assertIn("planned_for_edition", relation_types)
        self.assertIn("targets_section", relation_types)
        self.assertIn("targets_slot", relation_types)
        self.assertIn("requests_work_on", relation_types)
        self.assertIn("targets_lane", relation_types)
        self.assertIn("derived_from", relation_types)

    def test_coverage_theme_reporting_requires_agent_success_without_fallback(self):
        with mock.patch.object(
            papyrus_coverage_theme,
            "_create_cloud_procedure_client",
            return_value=object(),
        ), mock.patch.object(
            papyrus_coverage_theme,
            "_start_cloud_procedure_run",
            side_effect=RuntimeError("cloud unavailable"),
        ):
            result = papyrus_coverage_theme.coverage_theme_run(
                date="2026-05-21",
                topic="AI in video games",
                corpus_key="AI-ML-research",
                category_key="AI-ML-research",
                coverage_key="coverage.ai-in-video-games",
                sections=["culture"],
                section_budgets={"arts": 1},
                run_id="coverage-theme-test",
                through="reporting",
                require_agent_success=True,
                allow_fallback=True,
                now="2026-05-21T12:00:00Z",
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["degraded"])
        self.assertEqual(result["error"]["code"], "agent_success_required")

    def test_coverage_theme_reporting_allow_fallback_creates_private_packets_only(self):
        result = papyrus_coverage_theme.coverage_theme_run(
            date="2026-05-21",
            topic="AI in video games",
            corpus_key="AI-ML-research",
            category_key="AI-ML-research",
            coverage_key="coverage.ai-in-video-games",
            sections=["culture", "methods"],
            section_budgets={"arts": 2, "methods": 1},
            run_id="coverage-theme-test",
            through="reporting",
            allow_fallback=True,
            now="2026-05-21T12:00:00Z",
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["degraded"])
        self.assertEqual(result["summary"]["researchPacketCount"], 2)
        self.assertEqual(result["summary"]["reportingPacketCount"], 5)
        self.assertFalse(any(record["modelName"] in {"Item", "EditionItem"} for record in result["records"]))
        message_kinds = [
            record["input"]["messageKind"]
            for record in result["records"]
            if record["modelName"] == "Message"
        ]
        self.assertEqual(message_kinds.count("research_packet"), 2)
        self.assertEqual(message_kinds.count("reporting_context_packet"), 5)
        produces = [
            record for record in result["records"]
            if record["modelName"] == "SemanticRelation" and record["input"]["relationTypeKey"] == "produces"
        ]
        self.assertEqual(len(produces), 7)

    def test_story_budget_output_groups_reporting_candidates_from_graph_state(self):
        assignment = papyrus_coverage_theme.reporting_assignment_record(
            run_id="coverage-theme-test",
            date="2026-05-21",
            topic="AI in video games",
            corpus_key="AI-ML-research",
            category_key="AI-ML-research",
            category=None,
            category_set=None,
            coverage_node={
                "id": "semantic-node-coverage-ai-in-video-games-v1",
                "lineageId": "semantic-node-coverage-ai-in-video-games",
                "versionNumber": 1,
                "nodeKey": "coverage.ai-in-video-games",
                "displayName": "AI in video games",
            },
            edition={"id": "edition-edition-2026-05-21-v1", "lineageId": "edition-edition-2026-05-21"},
            section={"id": "arts", "title": "Arts", "type": "canonical"},
            slots=1,
            dispatch_count=2,
            angle={"key": "reader-impact", "label": "reader impact", "prompt": "reader impact"},
            candidate_rank=1,
            source_research_assignment={"id": "assignment-research"},
            signal=None,
            now="2026-05-21T12:00:00Z",
            priority=101,
        )
        message = {
            "id": "message-reporting-context-packet-test",
            "messageKind": "reporting_context_packet",
            "messageDomain": "assignment_work",
            "summary": "Reporting packet ready.",
        }
        relation = papyrus_coverage_theme.semantic_relation(
            predicate="produces",
            subject_kind="assignment",
            subject_id=assignment["id"],
            object_kind="message",
            object_id=message["id"],
            now="2026-05-21T12:00:00Z",
            metadata={},
        )
        slot_relation = papyrus_coverage_theme.semantic_relation(
            predicate="targets_slot",
            subject_kind="assignment",
            subject_id=assignment["id"],
            object_kind="editionSlot",
            object_id="edition-slot-edition-edition-2026-05-21-v1-arts-01-v1",
            object_lineage_id="edition-slot-edition-edition-2026-05-21-v1-arts-01",
            now="2026-05-21T12:00:00Z",
            metadata={"slotRank": 1, "sectionKey": "arts", "candidateRank": 1},
        )
        result = papyrus_coverage_theme.story_budget_output(
            run_id="coverage-theme-test",
            state={
                "assignments": [assignment],
                "messages": [message],
                "semanticRelations": [relation, slot_relation],
                "assignmentEvents": [
                    {
                        "id": "assignment-event-review",
                        "assignmentId": assignment["id"],
                        "eventType": "reporting_hold",
                        "note": "Needs stronger evidence.",
                        "createdAt": "2026-05-21T12:30:00Z",
                    }
                ],
                "modelAttachments": [],
                "items": [],
                "editionItems": [],
                "editionSlots": [
                    {
                        "id": "edition-slot-edition-edition-2026-05-21-v1-arts-01-v1",
                        "editionId": "edition-edition-2026-05-21-v1",
                        "sectionKey": "arts",
                        "slotRank": 1,
                        "targetType": "article",
                        "targetLengthBand": "standard",
                        "minImageAssets": 1,
                        "status": "assigned",
                        "selectedAssignmentId": None,
                        "metadata": {},
                        "createdAt": "2026-05-21T12:00:00Z",
                        "updatedAt": "2026-05-21T12:00:00Z",
                    }
                ],
            },
        )

        self.assertEqual(result["summary"]["sectionCount"], 1)
        self.assertEqual(result["summary"]["slotCount"], 1)
        section = result["sections"][0]
        self.assertEqual(section["sectionKey"], "arts")
        self.assertEqual(section["counts"]["reporting"], 1)
        self.assertEqual(section["counts"]["slots"], 1)
        self.assertEqual(section["counts"]["held"], 1)
        self.assertEqual(len(section["slots"]), 1)
        self.assertEqual(section["slots"][0]["candidateCount"], 1)
        self.assertTrue(section["reportingCandidates"][0]["packetAvailable"])

    def test_plan_forum_kickoff_supersede_skips_optional_desk_and_dispatch(self):
        edition_id = "edition-edition-2026-06-05-v1"
        thread_id = papyrus_coverage_theme._canonical_edition_forum_thread_id(edition_id)
        messages = [
            {
                "id": "message-1",
                "threadId": thread_id,
                "messageKind": "forum_post",
                "status": "active",
                "summary": "AI in video games",
                "content": "# AI in video games\n\n## Why this edition\n",
                "metadata": {"planningPhase": "edition_theme_kickoff"},
            },
            {
                "id": "message-2",
                "threadId": thread_id,
                "messageKind": "forum_post",
                "status": "active",
                "summary": "Optional desk: Arts",
                "metadata": {"planningPhase": "rotating_desk_selection"},
            },
            {
                "id": "message-3",
                "threadId": thread_id,
                "messageKind": "forum_post",
                "status": "active",
                "summary": "Reporting candidates: AI in video games",
                "content": "# Reporting candidates\n",
                "metadata": {"planningPhase": "reporting_dispatch"},
            },
        ]
        records = papyrus_coverage_theme._plan_forum_kickoff_supersede_records(
            {thread_id: messages},
            now="2026-06-01T12:00:00Z",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["input"]["id"], "message-1")
        self.assertEqual(records[0]["input"]["status"], "deleted")

    def test_plan_forum_refresh_supersede_includes_all_planning_phases(self):
        edition_id = "edition-edition-2026-06-05-v1"
        thread_id = papyrus_coverage_theme._canonical_edition_forum_thread_id(edition_id)
        messages = [
            {
                "id": "message-1",
                "threadId": thread_id,
                "messageKind": "forum_post",
                "status": "active",
                "summary": "AI in video games",
                "content": "# AI in video games\n\n## Why this edition\n",
                "metadata": {"planningPhase": "edition_theme_kickoff"},
            },
            {
                "id": "message-2",
                "threadId": thread_id,
                "messageKind": "forum_post",
                "status": "active",
                "summary": "Optional desk: Arts",
                "metadata": {"planningPhase": "rotating_desk_selection"},
            },
            {
                "id": "message-3",
                "threadId": thread_id,
                "messageKind": "forum_post",
                "status": "active",
                "summary": "Reporting candidates: AI in video games",
                "content": "# Reporting candidates\n",
                "metadata": {"planningPhase": "reporting_dispatch"},
            },
        ]
        records = papyrus_coverage_theme._plan_forum_refresh_supersede_records(
            {thread_id: messages},
            now="2026-06-01T12:00:00Z",
        )
        deleted_ids = {record["input"]["id"] for record in records}
        self.assertEqual(deleted_ids, {"message-1", "message-2", "message-3"})

    def test_canonical_edition_forum_thread_messages_includes_pending_records(self):
        edition_id = "edition-edition-2026-06-05-v1"
        thread_id = papyrus_coverage_theme._canonical_edition_forum_thread_id(edition_id)
        state = {
            "messages": [{
                "id": "message-1",
                "threadId": thread_id,
                "sequenceNumber": 1,
                "messageKind": "forum_post",
                "status": "active",
            }],
        }
        pending = [{
            "modelName": "Message",
            "input": {
                "id": "message-2",
                "threadId": thread_id,
                "sequenceNumber": 2,
                "messageKind": "forum_post",
                "status": "active",
            },
        }]
        messages = papyrus_coverage_theme._canonical_edition_forum_thread_messages(
            edition_id=edition_id,
            state=state,
            pending_records=pending,
        )
        self.assertEqual([int(message["sequenceNumber"]) for message in messages], [1, 2])

    def test_resolve_edition_theme_signal_uses_knowledge_base_references(self):
        now = "2026-06-01T12:00:00Z"
        references = [
            {
                "id": f"reference-ai-games-{index}",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "curationStatus": "accepted",
                "versionState": "current",
                "title": f"Generative agents for game worlds {index}",
                "sourceUri": "https://arxiv.org/abs/2605.12345",
                "sourcePublishedAt": "2026-05-20T00:00:00Z",
            }
            for index in range(12)
        ] + [
            {
                "id": "reference-unrelated-1",
                "corpusId": "knowledge-corpus-ai-ml-research",
                "curationStatus": "accepted",
                "versionState": "current",
                "title": "Unrelated protein folding benchmark",
                "sourceUri": "https://example.org/paper",
                "sourcePublishedAt": "2026-05-21T00:00:00Z",
            },
        ]
        signal = papyrus_coverage_theme.resolve_edition_theme_signal(
            signal=None,
            topic="AI in video games",
            coverage_key="coverage.ai-in-video-games",
            corpus_key="AI-ML-research",
            category_key="AI-ML-research",
            sections=["methods", "arts"],
            state={"references": references, "semanticNodes": []},
            now=now,
        )
        snapshot = signal.get("knowledgeBaseSnapshot") or {}
        self.assertGreaterEqual(snapshot.get("acceptedCorpusCount"), 13)
        self.assertGreater(signal.get("acceptedEvidenceCount"), 0)
        self.assertNotIn("thin", str(signal.get("whyNow") or "").lower())
        self.assertIn("accepted reference", str(signal.get("whyNow") or "").lower())

    def test_is_usable_theme_label_rejects_url_tokens(self):
        self.assertFalse(papyrus_coverage_theme._is_usable_theme_label("Https"))
        self.assertFalse(papyrus_coverage_theme._is_usable_theme_label("arxiv.org"))
        self.assertFalse(papyrus_coverage_theme._is_usable_theme_label("Language"))
        self.assertTrue(papyrus_coverage_theme._is_usable_theme_label("Generative game worlds"))

    def test_theme_phrases_from_reference_titles_extracts_bigrams(self):
        phrases = papyrus_coverage_theme._theme_phrases_from_reference_titles([
            "Video-LLaMA: An Instruction-tuned Audio-Visual Language Model for Video Understanding",
            "Streaming Video Question-Answering with In-context Video KV-Cache Retrieval",
        ])
        self.assertTrue(any("video" in phrase.lower() for phrase in phrases))

    def test_derive_edition_forum_thread_title_prefers_themes_over_domains(self):
        title = papyrus_coverage_theme.derive_edition_forum_thread_title(
            theme_line="AI in video games",
            signal={
                "whyNow": "25 accepted references mention AI in video games; domains include arxiv.org.",
                "sourceDomains": ["arxiv.org"],
                "acceptedEvidenceCount": 25,
                "knowledgeBaseSnapshot": {
                    "alternateTrendTopics": [
                        {"topic": "Generative game worlds", "acceptedEvidenceCount": 18},
                        {"topic": "Video understanding", "acceptedEvidenceCount": 12},
                    ],
                },
            },
            core_sections=[{"sectionKey": "methods", "sectionTitle": "Methods"}],
        )
        self.assertIn("AI in video games", title)
        self.assertNotIn("arxiv.org", title.lower())
        self.assertTrue(
            "generative game worlds" in title.lower() or "video understanding" in title.lower(),
            title,
        )

    def test_coverage_theme_plan_creates_forum_kickoff_threads_and_messages(self):
        plan = papyrus_coverage_theme.build_coverage_theme_plan(
            date="2026-06-05",
            topic="AI in video games",
            corpus_key="AI-ML-research",
            category_key="AI-ML-research",
            coverage_key="coverage.ai-in-video-games",
            sections=["culture"],
            section_budgets={"arts": 2},
            run_id="coverage-theme-forum-test",
            now="2026-06-01T12:00:00Z",
            state={
                "newsroomSections": [
                {"id": "arts", "title": "Arts", "type": "floating", "enabled": True, "sortOrder": 1},
                {"id": "methods", "title": "Methods", "type": "canonical", "enabled": True, "sortOrder": 2},
            ],
                "categories": [],
                "categorySets": [],
            },
        )

        thread_records = [record for record in plan["records"] if record["modelName"] == "MessageThread"]
        message_records = [
            record for record in plan["records"]
            if record["modelName"] == "Message" and record["input"].get("messageKind") == "forum_post"
        ]
        edition_thread = next(record["input"] for record in thread_records if record["input"]["threadKind"] == "edition_forum")
        section_threads = [record["input"] for record in thread_records if record["input"]["threadKind"] == "section_forum"]
        self.assertEqual(len(thread_records), 1)
        self.assertEqual(len(message_records), 1)
        self.assertEqual(section_threads, [])
        self.assertEqual(edition_thread["primaryAnchorKind"], "edition")
        self.assertTrue(plan["forumKickoff"]["editionThreadId"].startswith("message-thread-edition-forum-"))
        self.assertEqual(plan["forumKickoff"]["rotatingDeskStatus"], "pending_selection")
        self.assertIn("arts", plan["forumKickoff"]["optionalDeskSectionKeys"])
        self.assertEqual(plan["summary"]["forumThreadCount"], 1)
        self.assertEqual(plan["summary"]["forumMessageCount"], 1)
        body = message_records[0]["input"]["content"]
        thread_title = edition_thread["title"]
        self.assertNotEqual(thread_title, "Edition Forum")
        self.assertIn("AI in video games", thread_title)
        self.assertIn("## Why this edition", body)
        self.assertNotIn("in-window are thin", body)
        self.assertIn("## Desk-shaped story seeds", body)
        self.assertNotIn("How To Steer", body)
        self.assertNotIn("Phase 1", body)
        self.assertNotIn("Phase 2", body)
        self.assertNotIn("Phase 3", body)
        self.assertIn("edition", plan["forumKickoff"])
        self.assertEqual(plan["forumKickoff"]["sections"], [])

    def test_coverage_theme_plan_skips_duplicate_forum_kickoff_on_identical_rerun(self):
        edition_id = "edition-edition-2026-06-05-v1"
        edition_thread_id = f"message-thread-edition-forum-{papyrus_coverage_theme._safe_id(edition_id)}"
        edition_body = papyrus_coverage_theme._edition_forum_kickoff_body(
            topic="AI in video games",
            coverage_key="coverage.ai-in-video-games",
            core_sections=[],
            optional_desk_sections=[{
                "sectionId": "arts",
                "sectionKey": "arts",
                "sectionTitle": "Arts",
                "sectionType": "floating",
                "slots": 2,
                "dispatchCount": 3,
                "suggestedTopics": ["AI in video games"],
            }],
            recent_optional_desk_usage=[],
        )
        existing_state = {
            "newsroomSections": [
                {"id": "arts", "title": "Arts", "type": "floating", "enabled": True, "sortOrder": 1},
                {"id": "methods", "title": "Methods", "type": "canonical", "enabled": True, "sortOrder": 2},
            ],
            "categories": [],
            "categorySets": [],
            "messageThreads": [
                {
                    "id": edition_thread_id,
                    "threadKind": "edition_forum",
                    "primaryAnchorKind": "edition",
                    "primaryAnchorId": edition_id,
                    "primaryAnchorLineageId": edition_id,
                    "messageCount": 1,
                    "createdByLabel": "papyrus-editor",
                    "createdAt": "2026-06-01T09:00:00Z",
                    "metadata": {"editionId": edition_id},
                },
            ],
            "messages": [
                {
                    "id": f"message-forum-{papyrus_coverage_theme._safe_id(edition_thread_id)}-0001",
                    "threadId": edition_thread_id,
                    "messageKind": "forum_post",
                    "status": "active",
                    "summary": "AI in video games",
                    "content": edition_body,
                    "sequenceNumber": 1,
                    "importRunId": "coverage-theme-forum-rerun",
                    "metadata": {"planningPhase": "edition_theme_kickoff"},
                },
            ],
        }

        plan = papyrus_coverage_theme.build_coverage_theme_plan(
            date="2026-06-05",
            topic="AI in video games",
            corpus_key="AI-ML-research",
            category_key="AI-ML-research",
            coverage_key="coverage.ai-in-video-games",
            sections=["culture"],
            section_budgets={"arts": 2},
            run_id="coverage-theme-forum-rerun",
            now="2026-06-01T12:00:00Z",
            state=existing_state,
        )

        forum_posts = [
            record for record in plan["records"]
            if record["modelName"] == "Message" and record["input"].get("messageKind") == "forum_post"
        ]
        self.assertEqual(forum_posts, [])
        self.assertEqual(plan["forumKickoff"]["editionKickoffAction"], "skip")
        self.assertEqual(plan["forumKickoff"]["sections"], [])
        self.assertEqual(plan["summary"]["forumMessageCount"], 0)

    def test_partition_sections_for_dispatch_defers_optional_desks(self):
        sections = [
            {"id": "methods", "title": "Methods", "type": "canonical"},
            {"id": "arts", "title": "Arts", "type": "floating"},
        ]
        dispatch, provisional = papyrus_coverage_theme.partition_sections_for_dispatch(sections)
        self.assertEqual([section["id"] for section in dispatch], ["methods"])
        self.assertEqual([section["id"] for section in provisional], ["arts"])

    def test_collect_recent_optional_desk_usage_ignores_unconfirmed_budgets(self):
        editions = [{
            "id": "edition-edition-2026-06-05-v1",
            "editionDate": "2026-06-05",
            "metadata": {
                "sectionBudgets": [{"sectionKey": "arts", "slots": 2}],
            },
        }]
        self.assertEqual(papyrus_coverage_theme.collect_recent_optional_desk_usage(editions), [])
        editions[0]["metadata"]["selectedOptionalDeskKey"] = "arts"
        usage = papyrus_coverage_theme.collect_recent_optional_desk_usage(editions)
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["sectionKey"], "arts")
        self.assertEqual(usage[0].get("selectionSource"), "confirmed")

    def test_fallback_rotating_section_selection_avoids_recent_usage(self):
        context = {
            "editionId": "edition-edition-2026-06-06-v1",
            "acceptedTheme": "AI in video games",
            "candidateSections": [
                {"sectionKey": "arts", "sectionTitle": "Arts", "sectionType": "floating"},
                {"sectionKey": "gaming", "sectionTitle": "Gaming", "sectionType": "rotating"},
            ],
            "recentOptionalDeskUsage": [{"sectionKey": "arts", "editionDate": "2026-06-05"}],
        }
        selection = papyrus_coverage_theme.fallback_rotating_section_selection(context=context)
        self.assertEqual(selection["recommendedSectionKey"], "gaming")

    def test_optional_desk_dispatch_exists_detects_prior_dispatch(self):
        run_id = "coverage-theme-dispatch-test"
        section_key = "arts"
        edition_id = "edition-edition-2026-06-05-v1"
        state = {
            "assignments": [
                {"id": papyrus_coverage_theme.optional_desk_research_assignment_id(run_id=run_id, section_key=section_key)},
            ],
            "editionSlots": [
                {"id": papyrus_coverage_theme.optional_desk_slot_ids(edition_id=edition_id, section_key=section_key, slots=2)[0]},
            ],
        }
        self.assertTrue(
            papyrus_coverage_theme.optional_desk_dispatch_exists(
                state,
                run_id=run_id,
                section_key=section_key,
                edition_id=edition_id,
                section_budgets={"arts": 2},
            )
        )

    def test_optional_desk_dispatch_exists_ignores_stale_run_id(self):
        section_key = "arts"
        edition_id = "edition-edition-2026-06-05-v1"
        prior_run_id = "coverage-theme-2026-06-05-coverage.ai-in-video-games"
        state = {
            "assignments": [
                {
                    "id": papyrus_coverage_theme.optional_desk_research_assignment_id(
                        run_id=prior_run_id,
                        section_key=section_key,
                    ),
                    "sectionKey": section_key,
                    "metadata": {"editionId": edition_id},
                },
            ],
            "editionSlots": [
                {"id": papyrus_coverage_theme.optional_desk_slot_ids(edition_id=edition_id, section_key=section_key, slots=2)[0]},
            ],
        }
        self.assertTrue(
            papyrus_coverage_theme.optional_desk_dispatch_exists(
                state,
                run_id="coverage-theme-new-timestamp-run",
                section_key=section_key,
                edition_id=edition_id,
                section_budgets={"arts": 2},
            )
        )

    def test_resolve_coverage_theme_run_id_reuses_edition_metadata(self):
        state = {
            "editions": [{
                "id": "edition-edition-2026-06-05-v1",
                "editionDate": "2026-06-05",
                "slug": "edition-2026-06-05",
                "metadata": {"coverageThemeRunId": "coverage-theme-2026-06-05-coverage.ai-in-video-games"},
            }],
        }
        run_id = papyrus_coverage_theme.resolve_coverage_theme_run_id(
            date="2026-06-05",
            topic="AI in video games",
            coverage_key="coverage.ai-in-video-games",
            run_id="",
            state=state,
        )
        self.assertEqual(run_id, "coverage-theme-2026-06-05-coverage.ai-in-video-games")

    def test_build_edition_metadata_update_record_uses_valid_fields_only(self):
        edition = {
            "id": "edition-edition-2026-06-05-v1",
            "slug": "edition-2026-06-05",
            "editionDate": "2026-06-05",
            "metadata": {"planningPhase": "theme_proposal"},
        }
        record = papyrus_coverage_theme.build_edition_metadata_update_record(
            edition,
            {"rotatingDeskStatus": "selected", "selectedOptionalDeskKey": "gaming"},
        )
        self.assertEqual(record["action"], "update")
        self.assertNotIn("updatedAt", record["input"])
        self.assertEqual(record["input"]["id"], edition["id"])

    def test_coverage_theme_plan_posts_only_theme_message_when_optional_desk_pending(self):
        plan = papyrus_coverage_theme.build_coverage_theme_plan(
            date="2026-06-05",
            topic="AI in video games",
            corpus_key="AI-ML-research",
            category_key="AI-ML-research",
            coverage_key="coverage.ai-in-video-games",
            sections=["methods", "culture"],
            section_budgets={"methods": 1, "arts": 2},
            run_id="coverage-theme-canonical-forum-test",
            now="2026-06-01T12:00:00Z",
            state={
                "newsroomSections": [
                    {"id": "arts", "title": "Arts", "type": "floating", "enabled": True, "sortOrder": 1},
                    {"id": "methods", "title": "Methods", "type": "canonical", "enabled": True, "sortOrder": 2},
                ],
                "categories": [],
                "categorySets": [],
            },
        )
        section_threads = [
            record["input"]
            for record in plan["records"]
            if record["modelName"] == "MessageThread" and record["input"]["threadKind"] == "section_forum"
        ]
        edition_forum_posts = [
            record["input"]
            for record in plan["records"]
            if record["modelName"] == "Message" and record["input"].get("messageKind") == "forum_post"
        ]
        self.assertEqual(section_threads, [])
        self.assertEqual(len(edition_forum_posts), 1)
        self.assertIn("## Why this edition", edition_forum_posts[0]["content"])
        self.assertTrue(
            papyrus_coverage_theme.should_defer_reporting_dispatch_forum(
                plan,
                skip_rotating_desk=False,
                include_optional_desks=False,
                selected_optional_desk_key="",
            )
        )

    def test_reporting_dispatch_forum_lists_overassigned_candidates(self):
        plan = papyrus_coverage_theme.build_coverage_theme_plan(
            date="2026-06-05",
            topic="AI in video games",
            corpus_key="AI-ML-research",
            category_key="AI-ML-research",
            coverage_key="coverage.ai-in-video-games",
            sections=["methods"],
            section_budgets={"methods": 1},
            run_id="coverage-theme-dispatch-forum-test",
            now="2026-06-01T12:00:00Z",
            state={
                "newsroomSections": [
                    {"id": "methods", "title": "Methods", "type": "canonical", "enabled": True, "sortOrder": 1},
                ],
                "categories": [],
                "categorySets": [],
            },
        )
        dispatch_forum = papyrus_coverage_theme.build_reporting_dispatch_forum_records(
            edition=plan["edition"],
            topic="AI in video games",
            coverage_key="coverage.ai-in-video-games",
            reporting_assignments=plan["reportingAssignments"],
            edition_slots=plan["editionSlots"],
            section_budgets={"methods": 1},
            section_titles={"methods": "Methods"},
            run_id=plan["runId"],
            now="2026-06-01T12:00:00Z",
        )
        self.assertEqual(dispatch_forum["action"], "create")
        self.assertIn("# Reporting candidates", dispatch_forum["message"]["content"])
        self.assertIn("### Methods", dispatch_forum["message"]["content"])
        self.assertIn("Candidate ", dispatch_forum["message"]["content"])
        self.assertNotIn("1.5", dispatch_forum["message"]["content"])
        self.assertNotIn("Publication slots", dispatch_forum["message"]["content"])
        self.assertNotIn("Proposed reporting assignments", dispatch_forum["message"]["content"])
        self.assertNotIn("Phase 3", dispatch_forum["message"]["content"])
        self.assertGreaterEqual(len(plan["reportingAssignments"]), 2)

    def test_coverage_theme_plan_forks_forum_thread_on_material_replan(self):
        edition_id = "edition-edition-2026-06-05-v1"
        edition_thread_id = f"message-thread-edition-forum-{papyrus_coverage_theme._safe_id(edition_id)}"
        existing_state = {
            "newsroomSections": [
                {"id": "arts", "title": "Arts", "type": "floating", "enabled": True, "sortOrder": 1},
                {"id": "methods", "title": "Methods", "type": "canonical", "enabled": True, "sortOrder": 2},
            ],
            "categories": [],
            "categorySets": [],
            "messageThreads": [{
                "id": edition_thread_id,
                "threadKind": "edition_forum",
                "primaryAnchorKind": "edition",
                "primaryAnchorId": edition_id,
                "primaryAnchorLineageId": edition_id,
                "messageCount": 1,
                "createdByLabel": "papyrus-editor",
                "createdAt": "2026-06-01T09:00:00Z",
                "metadata": {"editionId": edition_id},
            }],
            "messages": [{
                "id": f"message-forum-{papyrus_coverage_theme._safe_id(edition_thread_id)}-0001",
                "threadId": edition_thread_id,
                "messageKind": "forum_post",
                "status": "active",
                "summary": "Edition planning suggestions: AI in video games",
                "content": "# Edition Planning Suggestions (Phase 1)\n\n- Suggested edition theme: AI in video games\n",
                "sequenceNumber": 1,
                "importRunId": "coverage-theme-forum-initial",
            }],
        }

        plan = papyrus_coverage_theme.build_coverage_theme_plan(
            date="2026-06-05",
            topic="AI safety in game moderation",
            corpus_key="AI-ML-research",
            category_key="AI-ML-research",
            coverage_key="coverage.ai-safety-in-game-moderation",
            sections=["culture"],
            section_budgets={"arts": 2},
            run_id="coverage-theme-forum-replan",
            now="2026-06-01T12:00:00Z",
            state=existing_state,
        )

        thread_records = [record for record in plan["records"] if record["modelName"] == "MessageThread"]
        edition_threads = [record["input"] for record in thread_records if record["input"]["threadKind"] == "edition_forum"]
        self.assertEqual(len(edition_threads), 1)
        self.assertNotEqual(edition_threads[0]["id"], edition_thread_id)
        self.assertEqual(edition_threads[0]["metadata"].get("parentThreadId"), edition_thread_id)
        self.assertEqual(plan["forumKickoff"]["editionKickoffAction"], "replan")
        replan_message = next(
            record["input"]
            for record in plan["records"]
            if record["modelName"] == "Message"
            and record["input"].get("messageKind") == "forum_post"
            and record["input"]["threadId"] == edition_threads[0]["id"]
        )
        self.assertIn("Edition replan", replan_message["content"])
        self.assertIn("## Why this edition", replan_message["content"])
        self.assertNotIn("planning pass", replan_message["content"].lower())


    def test_execute_tactus_reference_create_dry_run(self):
        planned_reference = {
            "id": "reference-lineage-test",
            "displayName": "Gemma guide",
            "sourceUri": "https://newsletter.example.com/p/gemma",
        }
        plan = {
            "importRunId": "knowledge-import-test",
            "records": [{"modelName": "Reference", "expected": planned_reference}],
        }
        with (
            mock.patch.object(papyrus_newsroom, "_load_steering_config", return_value={"corpora": [{"key": "AI-ML-research", "path": "AI-ML-research"}]}),
            mock.patch.object(papyrus_newsroom, "_resolve_corpus", return_value={"key": "AI-ML-research", "name": "AI/ML Research"}),
            mock.patch("papyrus_content.graphql_authoring.PapyrusGraphQLAuthoringClient") as client_cls,
            mock.patch(
                "papyrus_content.catalog.build_reference_catalog_registration_records",
                return_value=plan,
            ),
            mock.patch("papyrus_content.catalog.assert_reference_catalog_plan_safety"),
            mock.patch("papyrus_content.catalog.build_prepared_reference_catalog", side_effect=lambda catalog, _opts: catalog),
            mock.patch("papyrus_content.catalog.catalog_item_with_external_item_id", side_effect=lambda item: item),
            mock.patch("papyrus_content.steering.resolve_classifier_for_corpus", return_value="classifier-1"),
        ):
            client_cls.return_value.list_records.return_value = []
            result = tactus_runtime.execute_tactus(
                'return Reference.create{ url = "https://newsletter.example.com/p/gemma", title = "Gemma guide", apply = false }'
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["value"]["resource"], "Reference")
        self.assertFalse(result["value"]["applied"])
        self.assertEqual(result["value"]["referenceId"], "reference-lineage-test")
        self.assertIn("papyrus.Reference.create", result["api_calls"])

    def test_execute_tactus_reference_create_rejects_invalid_url(self):
        result = tactus_runtime.execute_tactus(
            'return Reference.create{ url = "not-a-url", apply = false }'
        )
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
