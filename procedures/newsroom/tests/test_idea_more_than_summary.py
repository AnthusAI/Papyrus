"""The minimum standard of an idea: more than a summary of its Reference (ideas/connections.py, features_backend/idea-more-than-summary.feature).

The backend, the pages and the model are fakes; nothing here reaches the network."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_idea_store import FakeIdeaStore  # noqa: E402
from ideas_fixtures import NOW  # noqa: E402
from papyrus_content import review_requests  # noqa: E402
from papyrus_content.ideas import connections as rules, monitor_stories as stories, point_check, retry_memory, review  # noqa: E402
from papyrus_content.ideas.connections import Knowledge, Neighbour, build_connections  # noqa: E402
from papyrus_content.ideas.signal_inputs import SignalMessage  # noqa: E402
from papyrus_content.ideas.signal_queue import ReferenceSummaries  # noqa: E402
from test_monitor_stories import PAGE, MonitorClient, context, world  # noqa: E402
from test_monitoring_stories import fake_idea_sink, quiet_gate  # noqa: E402,F401  (the router task tests' fixtures: the filing sink and the editorial gate are doubles)

REASON = "Claim checking matters to our sourcing coverage."
UNREADABLE = {1: {"likes": 5}}   # stored facts and no summary: the monitor knows nothing about what the page says


@pytest.fixture(autouse=True)
def iam_auth(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")   # earlier drafts are read through listStoryDrafts


def sentence(text, *cites):
    return {"text": text, "cites": list(cites)}


POINT = "Foo is built to check each claim against its source, which is the work claim checking in sourcing needs."
ADDS = {"verdict": "adds", "claim": "Foo checks each claim against its source.", "repeats_itself": False, "exposes_process": False, "reason": "It states what the tool does for sourcing."}


def story(*, dek=("Foo checks each claim against its source, the claim checking that sourcing coverage needs.", "E1"), body=None, headline=("Foo checks claims against sources", "I1"), point=POINT):
    return {
        "point": point,
        "headline": sentence(*headline), "dek": sentence(*dek), "section": "Tools",
        "paragraphs": [{"sentences": [sentence(*entry) for entry in (body or [
            ("Foo is an open tool that checks claims against their sources.", "I1"),
            ("Foo does the claim checking that sourcing coverage needs.", "I1", "E1"),
        ])]}],
    }


class Model:
    """Answers each drafting request with the same story and each point check with ``verdict`` (it adds something, unless the test says otherwise), and records
    the requests: ``drafting`` and ``checks`` tell them apart. ``verdict`` may be a function of the check's input."""

    def __init__(self, answer=None, verdict=None, variations=None) -> None:
        self.answer = answer or story()
        self.verdict = verdict or ADDS
        self.variations = variations   # what the variation writer answers: None offers nothing more than the idea itself
        self.requests: list[dict] = []

    @property
    def drafting(self):
        return [payload for payload in self.requests if not payload["instructions"].startswith(("You are a sceptical editor", "You write other versions"))]

    @property
    def variation_writing(self):
        return [payload for payload in self.requests if payload["instructions"].startswith("You write other versions")]

    @property
    def checks(self):
        return [payload for payload in self.requests if payload["instructions"].startswith("You are a sceptical editor")]

    def __call__(self, url, headers, payload):
        self.requests.append(payload)
        if payload["instructions"].startswith("You are a sceptical editor"):
            answer = self.verdict(json.loads(payload["input"])) if callable(self.verdict) else self.verdict
        elif payload["instructions"].startswith("You write other versions"):
            answer = self.variations if self.variations is not None else {"variations": []}
        else:
            answer = self.answer
        return {"status": "completed", "output_text": json.dumps(answer), "usage": {"input_tokens": 1000, "output_tokens": 300, "input_tokens_details": {"cached_tokens": 0}}}


class LinkedClient(MonitorClient):
    """A backend that also holds the link feed and answers Reference lookups by lineage."""

    def __init__(self, *args, feed=(), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.feed = list(feed)

    def list_by_index(self, index, key):
        if index == "semanticRelationsByNewsroomFeedAndCreatedAt":
            return list(self.feed)
        if index == "referencesByLineageAndVersion":
            return [row for row in self.references if row["lineageId"] == key]
        return super().list_by_index(index, key)


def editor_accepted(row, reason=REASON):
    row.update(curationActorKind="human", curationStatusReason=reason)
    return row


def link(first, second, *, state="suggested", score=0.8, predicate="related_to", note=None):
    """A link row of the feed. ``note`` is what an editor wrote when they accepted or made it (``metadata.note``, decided by a person)."""
    low, high = sorted([first["lineageId"], second["lineageId"]])
    metadata = {"decision": "accepted", "decidedBy": "editor-a", "note": note} if note else {}
    return {"relationState": state, "predicate": predicate, "subjectKind": "reference", "objectKind": "reference", "subjectLineageId": low, "objectLineageId": high,
            "score": score, "createdAt": "2026-10-20T00:00:00Z", "metadata": json.dumps(metadata)}


def run_stories(client, model, *, pages=lambda url: PAGE, store=None, dry_run=False, **options):
    options = {"limit": None, "json_store": None, **options}
    return stories.draft_monitor_stories(
        client=client, site="example-site", context=context(), transport=model, idea_store=store or FakeIdeaStore(client), review_client=client,
        dry_run=dry_run, now=NOW, fetch=pages, **options,
    )


def reasons(run):
    return [problem["reason"] for entry in run["invalid"] for problem in (entry.get("citationCheck") or {}).get("problems", [])]


# --- the pieces ------------------------------------------------------------------------------------------------------------------


def test_there_is_one_standard_and_no_way_back_to_summaries():
    assert rules.MORE_THAN_SUMMARY == "more-than-summary"
    for gone in ("SUMMARY", "MINIMUM_STANDARDS", "DEFAULT_STANDARD", "validate_standard"):
        assert not hasattr(rules, gone), gone
    assert not hasattr(stories, "SUMMARY_SYSTEM_PROMPT") and "minimum_standard" not in stories.draft_monitor_stories.__code__.co_varnames
    assert "judge_old_standard" not in stories.draft_monitor_stories.__code__.co_varnames


def test_an_address_in_the_editors_words_never_reaches_the_writer():
    connections = build_connections("Ask someone@example.org  about it.\nSoon", [], [])
    assert connections.entries[0].row["text"] == "Ask [address removed] about it. Soon"


def test_handles_are_numbered_in_a_fixed_order_and_confirmed_links_come_before_suggested_ones():
    near = Neighbour("l-near", "Near", "https://n", None, "About near.", "suggested", 0.9)
    made = Neighbour("l-made", "Made", "https://m", None, "About made.", "confirmed", None, "They share an author.")
    connections = build_connections(REASON, [{"author": "staff", "date": "2026-10-30", "text": "Worth a look."}], [near, made], suggested_links=3)
    assert [(entry.handle, entry.kind) for entry in connections.entries] == [
        ("E1", "acceptReason"), ("M1", "message"), ("R1", "neighbour"), ("R2", "neighbour"), ("X1", "editorsExplanation")]
    assert connections.by_handle()["R1"].reference.title == "Made" and connections.by_handle()["X1"].about == "R1"
    assert connections.labels_of(["I1", "E1", "R2", "X1", "E1"]) == ["acceptReason", "neighbour:R2", "editorsExplanation:R1"]
    assert connections.found == {"acceptReason": True, "messages": 1, "neighbours": 2, "editorsExplanations": 1, "suggestedLinks": 3}


def test_an_accept_reason_alone_clears_the_bar_for_a_readable_page_and_not_for_an_unreadable_one():
    reason = build_connections(REASON, [], [])
    assert reason.clears_the_bar(True) and not reason.clears_the_bar(False)
    assert not build_connections(None, [], []).clears_the_bar(True)
    assert build_connections(REASON, [{"text": "A comment."}], []).clears_the_bar(False)
    assert build_connections(None, [], [Neighbour("l", "T", "u", None, "Summary.", "confirmed")]).clears_the_bar(False)


def test_a_page_is_readable_with_page_text_or_a_real_summary_and_not_with_facts_alone():
    assert rules.readable({"page_text": "x"}) and rules.readable({"summary": "x"}) and not rules.readable({"facts": {"likes": 3}, "title": "t"})


def problems_of(sentences, connections, readable=True):
    return [problem["reason"] for problem in rules.standard_problems(sentences, connections, page_readable=readable)]


def entry(role, text, *handles):
    return {"where": role, "role": role, "text": text, "handles": list(handles)}


def test_every_sentence_resting_on_the_source_alone_is_only_a_summary():
    connections = build_connections(REASON, [], [])
    summary = [entry("headline", "Foo checks claims", "I1"), entry("dek", "Foo links claims to sources.", "I1"), entry("body", "Foo is an open tool.", "I1")]
    assert problems_of(summary, connections) == ["dek_without_connection", "only_the_source_cited"]


def test_a_connecting_sentence_must_share_a_content_word_with_what_it_cites():
    connections = build_connections(REASON, [], [])
    unrelated = [entry("dek", "A toaster is on sale.", "E1"), entry("body", "A toaster is on sale.", "I1", "E1")]
    assert problems_of(unrelated, connections) == ["connection_ungrounded"]
    related = [entry("dek", "Claim checking is prized.", "E1"), entry("body", "Claim checking is prized.", "I1", "E1")]
    assert problems_of(related, connections) == []


def test_how_the_story_came_to_be_is_not_the_subject():
    """The editors' words are direction for the writer, not content: a sentence that reports them, or how the item was found or matched, fails."""
    connections = build_connections(REASON, [], [])
    for text in ("The editors accepted it because claim checking matters.", "Claim checking, which the editors chose, is the subject.", "The newsroom has this on file for claim checking.",
                 "A suggested link ties it to claim checking.", "It is close to a related Reference on claim checking."):
        found = problems_of([entry("dek", text, "E1"), entry("body", text, "I1", "E1")], connections)
        assert found.count("internal_wording") == 2, (text, found)
    plain = [entry("dek", "Claim checking matters to sourcing coverage.", "E1"), entry("body", "Claim checking matters to sourcing coverage.", "I1", "E1")]
    assert problems_of(plain, connections) == []   # the words may inform a sentence; they are not attributed to anyone


def test_a_message_is_cited_only_with_the_source_or_a_related_reference():
    connections = build_connections(None, [{"text": "Claim checking is overdue."}], [])
    alone = [entry("dek", "A commenter says claim checking is overdue.", "M1"), entry("body", "A commenter says claim checking is overdue.", "M1")]
    assert "message_cited_without_reference" in problems_of(alone, connections)
    joined = [entry("dek", "A commenter says claim checking is overdue.", "M1", "I1"), entry("body", "A commenter says claim checking is overdue.", "M1", "I1")]
    assert problems_of(joined, connections) == []


def test_no_trend_is_claimed_without_counts_but_a_name_is_not_a_claim():
    connections = build_connections(REASON, [], [])
    claim = [entry("dek", "Claim checking shows a trend.", "E1"), entry("body", "Claim checking is rising.", "I1", "E1")]
    assert problems_of(claim, connections).count("trend_claim_without_signal") == 2
    name = [entry("dek", "Trend Micro ships claim checking.", "E1"), entry("body", "Trend Micro ships claim checking.", "I1", "E1")]
    assert problems_of(name, connections) == []


def test_on_an_unread_page_every_body_sentence_rests_on_the_newsroom_not_on_the_page():
    connections = build_connections(None, [{"text": "Claim checking is overdue."}], [])
    sentences = [entry("dek", "A commenter says claim checking is overdue.", "M1", "I1"), entry("body", "Foo is a tool that checks claims.", "I1"),
                 entry("body", "A commenter says claim checking is overdue.", "M1", "I1")]
    assert problems_of(sentences, connections, readable=False) == ["describes_unread_page"]
    assert problems_of(sentences, connections, readable=True) == []


# --- reading the newsroom ------------------------------------------------------------------------------------------------------


def knowledge_for(client, summaries=None, messages=()):
    summaries = summaries or {}
    rows = {row["lineageId"]: row for row in client.references}
    return Knowledge(client, summary_of=lambda lineage: summaries.get(lineage, ""), reference_of=rows.get, inputs=SimpleNamespace(messages=list(messages)))


def test_a_suggested_neighbour_counts_only_at_the_sites_median_nearest_neighbour_similarity():
    rows, base = world(4)
    feed = [link(rows[0], rows[1], score=0.9), link(rows[0], rows[2], score=0.6), link(rows[2], rows[3], score=0.7)]
    client = LinkedClient(references=rows, relations=base.relations, feed=feed)
    knowledge = knowledge_for(client, {row["lineageId"]: f"About {row['title']}." for row in rows})
    neighbours, suggested = knowledge.neighbours_of(rows[0]["lineageId"])
    # each Reference's closest suggestion: r1 0.9, r2 0.9, r3 0.7, r4 0.7, so the cut is their median, 0.8
    assert knowledge.neighbour_cut == pytest.approx(0.8)
    assert [(row.title, row.provenance) for row in neighbours] == [("Reference 2", "suggested")] and suggested == 2


def test_a_neighbour_with_only_a_title_or_not_accepted_is_not_offered():
    rows, base = world(3)
    rows[2]["curationStatus"] = "pending"
    feed = [link(rows[0], rows[1], score=0.9), link(rows[0], rows[2], score=0.9)]
    client = LinkedClient(references=rows, relations=base.relations, feed=feed)
    knowledge = knowledge_for(client, {rows[2]["lineageId"]: "A summary."})
    assert knowledge.neighbours_of(rows[0]["lineageId"])[0] == []   # r2 has no summary, r3 is pending


def test_a_confirmed_link_is_a_neighbour_whatever_its_similarity_and_may_carry_the_editors_explanation():
    rows, base = world(2)
    feed = [link(rows[0], rows[1], state="current", score=None, note="Both cover the same vendor.")]
    client = LinkedClient(references=rows, relations=base.relations, feed=feed)
    knowledge = knowledge_for(client, {rows[1]["lineageId"]: "A summary."})
    [neighbour], _ = knowledge.neighbours_of(rows[0]["lineageId"])
    assert (neighbour.provenance, neighbour.explanation) == ("confirmed", "Both cover the same vendor.")
    handles = [entry.handle for entry in build_connections(None, [], [neighbour]).entries]
    assert handles == ["R1", "X1"]   # the explanation is a connection handle of its own once #1034 supplies it


def test_a_link_no_person_explained_has_no_explanation_and_a_machine_links_words_are_not_the_editors():
    rows, base = world(2)
    client = LinkedClient(references=rows, relations=base.relations, feed=[link(rows[0], rows[1], state="current", score=None)])
    [neighbour], _ = knowledge_for(client, {rows[1]["lineageId"]: "A summary."}).neighbours_of(rows[0]["lineageId"])
    assert neighbour.explanation is None
    machine = link(rows[0], rows[1], state="current", score=None, note="Matched by similarity.")
    machine["metadata"] = json.dumps({"decision": "accepted", "decidedBy": "auto:vector", "note": "Matched by similarity."})
    client = LinkedClient(references=rows, relations=base.relations, feed=[machine])
    assert knowledge_for(client, {rows[1]["lineageId"]: "A summary."}).neighbours_of(rows[0]["lineageId"])[0][0].explanation is None


def test_on_a_build_whose_edges_carry_no_explanation_field_a_confirmed_link_is_still_a_neighbour(monkeypatch):
    """The rule counts an explanation when the edge has the field (PR #1034, merged) and does not need it."""
    rows, base = world(2)
    client = LinkedClient(references=rows, relations=base.relations, feed=[link(rows[0], rows[1], state="current", score=None, note="Both cover the same vendor.")])
    from papyrus_content.ideas import signal_inputs

    real = signal_inputs.edges_of
    monkeypatch.setattr(signal_inputs, "edges_of", lambda relations: [SimpleNamespace(subject_lineage_id=edge.subject_lineage_id, object_lineage_id=edge.object_lineage_id, predicate=edge.predicate) for edge in real(relations)])
    [neighbour], _ = knowledge_for(client, {rows[1]["lineageId"]: "A summary."}).neighbours_of(rows[0]["lineageId"])
    assert (neighbour.provenance, neighbour.explanation) == ("confirmed", None)


def test_a_backend_that_refuses_a_read_is_noted_and_treated_as_empty():
    rows, base = world(2)

    class Refusing(LinkedClient):
        def list_by_index(self, index, key):
            if index == "semanticRelationsByNewsroomFeedAndCreatedAt":
                raise RuntimeError("not authorized")
            return super().list_by_index(index, key)

    knowledge = knowledge_for(Refusing(references=rows, relations=base.relations))
    assert knowledge.neighbours_of(rows[0]["lineageId"]) == ([], 0) and knowledge.errors == {"links": "RuntimeError"}


def test_the_summary_chain_ends_with_the_curation_summary_then_the_preview_description_that_is_more_than_the_title():
    class Attachments:
        def __init__(self, rows):
            self.rows = rows

        def list_semantic_relations_by_object_state(self, key):
            return []

        def list_reference_attachments_by_lineage(self, lineage):
            return self.rows

    curation = {"role": "curation", "metadata": json.dumps({"summary": {"text": " A  curated   summary. "}})}
    preview = {"role": "preview", "metadata": {"description": "A preview description."}}
    title_only = {"role": "preview", "metadata": {"description": "Some Title"}}
    assert ReferenceSummaries(Attachments([preview, curation]))["l1"] == "A curated summary."
    assert ReferenceSummaries(Attachments([preview]))["l1"] == "A preview description."
    assert ReferenceSummaries(Attachments([title_only]), titles={"l1": "some title"})["l1"] == ""
    assert ReferenceSummaries(Attachments([]), attachment_summary=lambda lineage: "From the metadata attachment.")["l1"] == "From the metadata attachment."

    class Denied(Attachments):
        def list_reference_attachments_by_lineage(self, lineage):
            raise PermissionError("no grant")

    denied = ReferenceSummaries(Denied([]))
    assert denied["l1"] == "" and denied.attachment_error == "PermissionError"


# --- the run ---------------------------------------------------------------------------------------------------------------------


def one_reference(*, reason=True, details=None, **options):
    rows, client = world(1, details=details, **options)
    if reason:
        editor_accepted(rows[0])
    return rows, LinkedClient(references=rows, relations=client.relations, incoming=client.incoming, sections=("Analysis", "Tools"))


def test_an_accepted_reference_with_the_editors_reason_is_filed_and_its_point_checked():
    rows, client = one_reference()
    model = Model()
    run = run_stories(client, model)
    assert [draft["title"] for draft in run["drafts"]] == ["Foo checks claims against sources"]
    filed = client.filed[0]
    assert json.loads(filed["evidence"])["connections"] == ["acceptReason"] and json.loads(filed["evidence"])["minimumStandard"] == "more-than-summary"
    assert json.loads(filed["targets"]) == [{"type": "entity", "id": f"reference:{rows[0]['lineageId']}"}]
    assert "## What editors said" in filed["body"] and REASON in filed["body"]
    knows = json.loads(model.drafting[0]["input"])["what_the_newsroom_knows"]
    assert knows[0]["handle"] == "E1" and knows[0]["text"] == REASON and "not a fact" in knows[0]["note"] and "not to be reported" in knows[0]["note"]
    assert run["connectionsUsed"] == {"acceptReason": 1} and run["nothingToAdd"] == 0
    assert "what this story claims that a reader could not get from the source alone" in model.drafting[0]["instructions"]
    assert len(model.checks) == 1 and run["pointChecks"][0]["failures"] == [] and run["pointChecks"][0]["point"] == POINT


def test_a_summary_of_the_source_is_not_filed():
    rows, client = one_reference()
    summary = story(dek=("Foo links each claim in a draft to the source page it came from.", "I1"),
                    body=[("Foo is an open tool that checks claims against their sources.", "I1"), ("It was written in Rust.", "I1")])
    run = run_stories(client, Model(summary))
    assert run["drafts"] == [] and client.filed == []
    assert "dek_without_connection" in reasons(run) and "only_the_source_cited" in reasons(run)
    assert run["checkFailures"] == {"dek_without_connection": 1, "only_the_source_cited": 1}


def test_a_reference_with_nothing_to_connect_to_is_skipped_before_the_model_is_asked_and_looked_at_again_next_run():
    rows, client = one_reference(reason=False)
    model = Model()
    run = run_stories(client, model)
    assert model.requests == [] and run["drafts"] == [] and run["usage"]["calls"] == 0
    assert run["skipped"] == [{"referenceId": rows[0]["id"], "title": "Reference 1", "reason": "nothing_to_add", "pageReadable": True,
                               "found": {"acceptReason": False, "messages": 0, "neighbours": 0, "editorsExplanations": 0, "suggestedLinks": 0}}]
    assert run["nothingToAdd"] == 1 and run["inputs"]["candidates"] == 1
    editor_accepted(rows[0])   # an editor gives a reason; the Reference was never marked drafted
    again = run_stories(client, Model())
    assert len(again["drafts"]) == 1 and again["inputs"]["alreadyDrafted"] == 0


def test_an_accept_reason_given_by_a_machine_is_not_the_editors_view():
    rows, client = one_reference(reason=False)
    rows[0].update(curationActorKind="cyclotron", curationStatusReason="Judged relevant")
    assert run_stories(client, Model())["nothingToAdd"] == 1


def test_an_unreadable_page_is_not_described_on_an_accept_reason_alone():
    rows, client = one_reference(details=UNREADABLE)
    model = Model()
    run = run_stories(client, model, pages=lambda url: None)
    assert model.requests == [] and run["skipped"][0]["reason"] == "nothing_to_add" and run["skipped"][0]["pageReadable"] is False


def test_an_unreadable_page_proceeds_with_a_comment_and_may_say_only_what_the_comment_bears_on():
    rows, client = one_reference(details=UNREADABLE)
    comment = SignalMessage("m1", "t1", "reference", f"reference#{rows[0]['lineageId']}", "2026-10-30T09:00:00Z", "staff", "Claim checking is overdue for us.")
    knowledge = Knowledge(client, summary_of=lambda lineage: "", reference_of=lambda lineage: None, inputs=SimpleNamespace(messages=[comment]))
    describing = story(dek=("A commenter says claim checking is overdue.", "M1", "I1"), body=[
        ("Foo is a tool that checks claims.", "I1"), ("A commenter says claim checking is overdue for sourcing coverage.", "M1", "I1")])
    assert run_stories(client, Model(describing), pages=lambda url: None, knowledge=knowledge)["checkFailures"] == {"describes_unread_page": 1}
    bearing = story(dek=("A commenter says claim checking is overdue.", "M1", "I1"), body=[
        ("A commenter says claim checking is overdue for sourcing coverage.", "M1", "I1"), ("Claim checking is the sourcing work this item is about.", "E1", "I1")])
    run = run_stories(client, Model(bearing), pages=lambda url: None, knowledge=knowledge)
    assert len(run["drafts"]) == 1 and run["drafts"][0]["evidence"]["connections"] == ["acceptReason", "message:M1"]
    assert run["connectionsUsed"] == {"acceptReason+message": 1}


def test_an_unreadable_page_proceeds_with_a_real_related_reference():
    rows, base = world(2, details=UNREADABLE)
    editor_accepted(rows[0])
    client = LinkedClient(references=rows, relations=base.relations, incoming=base.incoming, sections=("Analysis", "Tools"), feed=[link(rows[0], rows[1], score=0.9)])
    knowledge = knowledge_for(client, {rows[1]["lineageId"]: "Reference 2 checks quotations against archives."})
    bearing = story(dek=("A second tool checks quotations against archives, a form of claim checking.", "E1", "R1"), body=[
        ("Reference 2 checks quotations against archives, which is close to what this item is called.", "R1"),
        ("Claim checking is the sourcing work both tools do.", "E1", "I1")])
    run = run_stories(client, Model(bearing), pages=lambda url: None, knowledge=knowledge, ordered_candidates=[rows[0]["lineageId"]])
    assert len(run["drafts"]) == 1 and run["drafts"][0]["evidence"]["connections"] == ["acceptReason", "neighbour:R1"]
    assert [cited["title"] for cited in run["drafts"][0]["citedItems"]] == ["Reference 1", "Reference 2"]
    assert run["drafts"][0]["targets"] == [{"type": "entity", "id": f"reference:{rows[0]['lineageId']}"}]   # the neighbour stays a candidate of its own
    assert "2. Reference 2" in run["drafts"][0]["body"]


def test_a_dry_run_asks_the_model_and_files_nothing_and_raises_no_flag():
    rows, client = one_reference(reason=False)
    run = run_stories(client, Model(), dry_run=True)
    assert run["curationFlag"]["status"] == "skipped" and client.reviews == {} and run["nothingToAdd"] == 1


# --- the curation flag -----------------------------------------------------------------------------------------------------------


def flags(client):
    return [request for request in review_requests.list_reviews(client) if request["mode"] == "flag"]


def test_a_run_that_files_nothing_because_of_nothing_to_add_raises_one_flag_that_names_what_would_help():
    rows, base = world(3)
    client = LinkedClient(references=rows, relations=base.relations, incoming=base.incoming, sections=("Analysis", "Tools"),
                          feed=[link(rows[0], rows[1], score=0.9)])
    run = run_stories(client, Model())
    assert run["curationFlag"]["status"] == "raised"
    [flag] = flags(client)
    assert flag["raisedBy"] == "idea-pipeline" and flag["subject"] == {"type": "batch", "id": "ideas-curation:example-site"}
    assert flag["reason"] == "No ideas today: 3 accepted References had nothing to connect to, so the ideas would only have summarised them."
    assert flag["ask"].startswith("What would help most: add a reason when you accept (3 of 3 have none); confirm the suggested links waiting in Related (2 have close matches); comment on the ones you care about.")
    assert "Waiting: Reference 1; Reference 2; Reference 3." in flag["ask"]
    for word in ("Draft", "draft", "desk"):
        assert word not in flag["reason"] + flag["ask"]


def test_an_open_flag_is_not_raised_again():
    rows, client = one_reference(reason=False)
    first = run_stories(client, Model())
    second = run_stories(client, Model())
    assert first["curationFlag"]["status"] == "raised" and second["curationFlag"]["status"] == "already_open" and len(flags(client)) == 1


def test_a_run_that_files_ideas_acknowledges_the_open_flag():
    rows, client = one_reference(reason=False)
    run_stories(client, Model())
    editor_accepted(rows[0])
    filed = run_stories(client, Model())
    assert filed["curationFlag"]["status"] == "acknowledged"
    [flag] = flags(client)
    assert flag["state"] == "answered" and flag["answer"]["decision"] == "acknowledge" and "flowing again" in flag["answer"]["feedback"]
    again = run_stories(client, Model())   # the Reference is drafted now and nothing new was accepted: that is the "no candidates" case, and it says so once
    assert again["inputs"]["alreadyDrafted"] == 1 and again["curationFlag"]["status"] == "raised" and [flag["state"] for flag in flags(client)] == ["open", "answered"]


def test_with_no_candidates_at_all_the_flag_asks_for_accepted_references():
    rows, base = world(2, status="pending")
    client = LinkedClient(references=rows, relations=base.relations, sections=("Analysis", "Tools"))
    run = run_stories(client, Model())
    assert run["curationFlag"]["status"] == "raised"
    [flag] = flags(client)
    assert flag["reason"] == "No ideas today: no accepted References are waiting to be written about."
    assert "2 pending References are waiting to be accepted" in flag["ask"]


def test_a_site_without_review_requests_is_not_failed_by_the_flag():
    rows, client = one_reference(reason=False)
    client.reject_review_writes = True
    run = run_stories(client, Model())
    assert run["curationFlag"]["status"] == "not_raised" and "RuntimeError" in run["curationFlag"]["error"]


def test_the_reports_and_records_say_ideas_and_never_draft_or_desk():
    text = review.curation_flag_text({"inputs": {"notAccepted": 4}}, []) + review.curation_flag_text({"inputs": {}}, [{"title": "A", "found": {"acceptReason": False, "suggestedLinks": 1}}])
    assert not any(word in " ".join(text).lower() for word in (" draft", "desk"))


def test_the_time_of_the_fixtures_is_fixed():
    assert NOW == datetime(2026, 10, 23, 12, 0, tzinfo=NOW.tzinfo)


# --- the router's grant covers what the standard reads ----------------------------------------------------------------------------


def test_every_field_a_single_item_run_reads_under_the_standard_is_granted_to_the_router():
    """The standard adds reads (Messages, the link feed, summaries, a neighbour's Reference). Record every AppSync field a run asks of a publication's API on the
    real client with its transport replaced, and check the template grants each one (test_monitoring_stories.py holds the same check for the old reads)."""
    from papyrus_content.graphql_authoring import INDEX_DEFINITIONS, PapyrusGraphQLAuthoringClient
    from papyrus_content.monitoring_stories import run_publication
    import test_monitoring_router as tr
    import test_monitoring_stories as task_tests

    rows, fake = one_reference()
    recorded: set[tuple[str, str]] = set()

    def respond(query, variables=None):
        kind, field = ("Mutation" if query.lstrip().startswith("mutation") else "Query"), task_tests.GRAPHQL_ROOT.match(query).group(1)
        recorded.add((kind, field))
        variables = variables or {}
        if field == "listStoryDrafts":
            return {field: {"status": "ok", "drafts": []}}
        if field == "fileProposal":
            return {field: {"status": "ok", "id": "proposal-1"}}
        if kind == "Mutation":
            return {field: {"id": "x"}}
        if field.startswith("get"):
            return {field: None}
        for index, definition in INDEX_DEFINITIONS.items():
            if definition["field"] == field and index == "referencesByCurationStatusKey":
                return {field: {"items": [r for r in fake.references if variables.get("curationStatusKey", "").endswith("#accepted")], "nextToken": None}}
        return {field: {"items": [], "nextToken": None}}

    client = PapyrusGraphQLAuthoringClient(endpoint=tr.ENDPOINT, header_factory=lambda body: {})
    client.graphql = respond
    publication = {"publicationId": task_tests.PUBLICATION, "corpusKey": task_tests.PUBLICATION, "monitorStories": {"contextPacks": {"enabled": False}}}
    line = run_publication(client, publication, transport=Model(), now=NOW, out_of_time=lambda: False, fetch=lambda url: PAGE, explorer=None)
    assert line["drafted"] == 1 and line["nothingToAdd"] == 0, line
    assert {("Query", "listMessageThreads"), ("Query", "listSemanticRelationsByNewsroomFeedAndCreatedAt")} <= recorded
    assert {("Query", "listReviewRequests"), ("Mutation", "updateReviewRequest")} <= wildcard_grants()   # the curation flag finds its open flag and acknowledges it
    granted = task_tests.granted_fields("AnthUsApiId") | wildcard_grants()
    assert recorded <= granted, sorted(recorded - granted)


def wildcard_grants():
    """The (Query|Mutation, field) pairs the router role may use on any publication API (``apis/*``: the RouterIdeaPolicy)."""
    import re
    import test_monitoring_stories as task_tests

    found = set()
    for resource in task_tests._template()["Resources"].values():
        props = resource.get("Properties") or {}
        if resource["Type"] == "AWS::IAM::ManagedPolicy" and ("Ref", "RouterRole") in (props.get("Roles") or []):
            for statement in props["PolicyDocument"]["Statement"]:
                for entry in statement["Resource"] if isinstance(statement.get("Resource"), list) else [statement.get("Resource")]:
                    match = re.search(r"apis/\*/types/(Query|Mutation)/fields/(\w+)$", str(entry[1] if isinstance(entry, tuple) else entry))
                    if match:
                        found.add((match.group(1), match.group(2)))
    return found


# --- the point check: a draft that says nothing its sources do not is not filed, and each reason is recorded ----------------------------


def verdict(**changes):
    return {**ADDS, **changes}


RESTATES = verdict(verdict="restates", claim="", reason="It repeats the page.")


def test_the_point_check_names_each_reason_a_verdict_keeps_a_draft_out():
    assert point_check.failures(ADDS) == []
    assert point_check.failures(RESTATES) == ["no_point_beyond_source"]
    assert point_check.failures(verdict(claim="  ")) == ["no_point_beyond_source"]   # "adds" with nothing claimed is no claim
    assert point_check.failures(verdict(verdict="unsupported")) == ["point_unsupported"]
    assert point_check.failures(verdict(repeats_itself=True)) == ["repeats_itself"]
    assert point_check.failures(verdict(exposes_process=True)) == ["exposes_process"]
    assert point_check.failures(verdict(verdict="restates", repeats_itself=True, exposes_process=True)) == ["no_point_beyond_source", "repeats_itself", "exposes_process"]
    assert point_check.failures({"verdict": "maybe"}) == ["point_unsupported", "repeats_itself", "exposes_process"]   # anything but a clear answer fails closed
    assert point_check.failures({}) != []


@pytest.mark.parametrize("answer,expected", [
    (RESTATES, ["no_point_beyond_source"]),
    (verdict(verdict="unsupported", claim="Foo is faster than every rival."), ["point_unsupported"]),
    (verdict(repeats_itself=True), ["repeats_itself"]),
    (verdict(exposes_process=True), ["exposes_process"]),
])
def test_a_draft_the_point_check_fails_is_not_filed_and_the_run_records_why(answer, expected):
    rows, client = one_reference()
    run = run_stories(client, Model(verdict=answer))
    assert run["drafts"] == [] and client.filed == []
    [invalid] = run["invalid"]
    assert (invalid["reason"], invalid["failures"], invalid["verdict"]) == ("point_check_failed", expected, answer)
    assert run["pointChecks"][0]["failures"] == expected and run["checkFailures"] == {reason: 1 for reason in expected}
    assert run["curationFlag"]["status"] == "raised"   # nothing was filed, so editors are asked to work on curation


@pytest.mark.parametrize("reply", [{"status": "incomplete"}, {"status": "completed", "output_text": "not json"}, {"status": "completed", "output_text": json.dumps({"claim": "x"})}])
def test_a_point_check_with_no_usable_answer_files_nothing_and_is_not_remembered(reply):
    rows, client = one_reference()

    class Unsure(Model):
        def __call__(self, url, headers, payload):
            if payload["instructions"].startswith("You are a sceptical editor"):
                self.requests.append(payload)
                return reply
            return super().__call__(url, headers, payload)

    memory = retry_memory.DictMemory()
    run = run_stories(client, Unsure(), retry_memory=memory)
    assert run["drafts"] == [] and [entry["reason"] for entry in run["invalid"]] == ["point_check_error"]
    assert memory.records == {}   # no verdict says nothing about the Reference: the next run asks again


def test_a_writer_with_no_point_to_make_is_not_checked_and_is_remembered():
    rows, client = one_reference()
    memory = retry_memory.DictMemory()
    model = Model(story(point="  "))
    run = run_stories(client, model, retry_memory=memory)
    assert model.checks == [] and run["drafts"] == [] and [row["reason"] for row in run["skipped"]] == ["no_point_offered"] and run["noPointOffered"] == 1
    assert memory.records[f"reference:{rows[0]['lineageId']}"]["reasons"] == ["no_point_offered"]


# --- retry memory ----------------------------------------------------------------------------------------------------------------


def comment(rows, text="Claim checking is overdue for us.", number=1):
    return SignalMessage(f"m{number}", "t1", "reference", f"reference#{rows[0]['lineageId']}", "2026-10-30T09:00:00Z", "staff", text)


def knowing(client, rows, *messages, summaries=None):
    return Knowledge(client, summary_of=lambda lineage: (summaries or {}).get(lineage, ""), reference_of={row["lineageId"]: row for row in client.references}.get,
                     inputs=SimpleNamespace(messages=list(messages)))


def test_a_rejected_reference_is_not_written_again_until_the_newsroom_has_something_new_for_it():
    rows, client = one_reference()
    memory = retry_memory.DictMemory()
    first = Model(verdict=RESTATES)
    run = run_stories(client, first, retry_memory=memory)
    assert len(first.drafting) == 1 and len(first.checks) == 1 and run["alreadyRejected"] == 0
    [record] = memory.records.values()
    assert record["subject"] == f"reference:{rows[0]['lineageId']}" and record["reasons"] == ["point_check_failed"] and record["runId"] == run["runId"]
    assert record["connections"] and all(key.startswith("acceptReason:") for key in record["connections"])   # what it was rejected against

    again = Model()
    run = run_stories(client, again, retry_memory=memory)
    assert again.requests == [] and run["usage"]["calls"] == 0 and run["attempted"] == 0   # no model call, and no page fetched
    [skipped] = run["skipped"]
    assert (skipped["reason"], skipped["earlierReasons"]) == ("already_rejected", ["point_check_failed"]) and run["alreadyRejected"] == 1 and run["retriedWithNewConnections"] == []


@pytest.mark.parametrize("new", ["comment", "accept reason", "related Reference", "confirmed link", "editors' explanation"])
def test_each_kind_of_new_connection_makes_a_rejected_reference_worth_another_try(new):
    rows, base = world(2)
    editor_accepted(rows[0])
    summaries = {rows[1]["lineageId"]: "Reference 2 checks quotations against archives."}
    feed = []
    client = LinkedClient(references=rows, relations=base.relations, incoming=base.incoming, sections=("Analysis", "Tools"), feed=feed)
    memory = retry_memory.DictMemory()
    run_stories(client, Model(verdict=RESTATES), retry_memory=memory, knowledge=knowing(client, rows, summaries=summaries), ordered_candidates=[rows[0]["lineageId"]])
    [before] = memory.records.values()

    messages = []
    if new == "comment":
        messages = [comment(rows)]
    elif new == "accept reason":
        rows[0]["curationStatusReason"] = "A different reason: sourcing coverage needs claim checking."
    elif new == "related Reference":
        client.feed.append(link(rows[0], rows[1], score=0.9))
    elif new == "confirmed link":
        client.feed.append(link(rows[0], rows[1], state="current", score=None))
    else:
        client.feed.append(link(rows[0], rows[1], state="current", score=None, note="Both cover claim checking."))
    model = Model()
    run = run_stories(client, model, retry_memory=memory, knowledge=knowing(client, rows, *messages, summaries=summaries), ordered_candidates=[rows[0]["lineageId"]])
    assert len(model.drafting) == 1 and len(run["drafts"]) == 1, run["skipped"]
    [retry] = run["retriedWithNewConnections"]
    assert retry["subject"] == before["subject"] and retry["newConnections"] and retry["earlierReasons"] == ["point_check_failed"]
    assert not set(retry["newConnections"]) & set(before["connections"])


def test_a_suggested_link_that_an_editor_confirms_is_a_new_connection_and_a_vanished_one_is_not():
    rows, base = world(2)
    editor_accepted(rows[0])
    summaries = {rows[1]["lineageId"]: "Reference 2 checks quotations against archives."}
    client = LinkedClient(references=rows, relations=base.relations, incoming=base.incoming, sections=("Analysis", "Tools"), feed=[link(rows[0], rows[1], score=0.9)])
    memory = retry_memory.DictMemory()
    run_stories(client, Model(verdict=RESTATES), retry_memory=memory, knowledge=knowing(client, rows, summaries=summaries), ordered_candidates=[rows[0]["lineageId"]])
    client.feed[:] = [link(rows[0], rows[1], state="current", score=None)]
    confirmed = run_stories(client, Model(verdict=RESTATES), retry_memory=memory, knowledge=knowing(client, rows, summaries=summaries), ordered_candidates=[rows[0]["lineageId"]])
    assert [row["newConnections"] for row in confirmed["retriedWithNewConnections"]] == [[f"neighbour:{rows[1]['lineageId']}:confirmed"]]
    client.feed[:] = []   # the link goes away: that is not news
    gone = Model()
    quiet = run_stories(client, gone, retry_memory=memory, knowledge=knowing(client, rows, summaries=summaries), ordered_candidates=[rows[0]["lineageId"]])
    assert gone.requests == [] and quiet["alreadyRejected"] == 1
    client.feed[:] = [link(rows[0], rows[1], state="current", score=None)]   # and when it comes back it is not news either
    back = Model()
    assert run_stories(client, back, retry_memory=memory, knowledge=knowing(client, rows, summaries=summaries), ordered_candidates=[rows[0]["lineageId"]])["alreadyRejected"] == 1 and back.requests == []


def test_a_reference_waiting_for_something_new_does_not_use_the_run_that_others_need():
    rows, base = world(3)
    for row in rows:
        editor_accepted(row)
    client = LinkedClient(references=rows, relations=base.relations, incoming=base.incoming, sections=("Analysis", "Tools"))
    memory = retry_memory.DictMemory()
    memory.remember(f"reference:{rows[0]['lineageId']}", {"subject": f"reference:{rows[0]['lineageId']}", "reasons": ["point_check_failed"], "connections": [
        f"acceptReason:{retry_memory.digest(REASON)}"]})
    model = Model()
    run = run_stories(client, model, retry_memory=memory, limit=1)
    assert [row["title"] for row in run["drafts"]] == ["Foo checks claims against sources"] and run["alreadyRejected"] == 1
    assert run["attempted"] == 1 and len(model.drafting) == 1   # the rejected one cost nothing and did not take the only attempt


def test_a_dry_run_reads_the_memory_and_writes_nothing_to_it():
    rows, client = one_reference()
    memory = retry_memory.DictMemory()
    run_stories(client, Model(verdict=RESTATES), retry_memory=memory, dry_run=True)
    assert memory.records == {}
    run_stories(client, Model(verdict=RESTATES), retry_memory=memory)
    assert len(memory.records) == 1
    model = Model()
    assert run_stories(client, model, retry_memory=memory, dry_run=True)["alreadyRejected"] == 1 and model.requests == []


def test_a_memory_that_cannot_be_read_or_written_never_stops_a_run():
    rows, client = one_reference()

    class Broken:
        def recall(self, subject):
            raise RuntimeError("no table")

        def remember(self, subject, record):
            raise RuntimeError("no table")

    run = run_stories(client, Model(verdict=RESTATES), retry_memory=Broken())
    assert run["retryMemoryErrors"] == {"recall": "RuntimeError", "remember": "RuntimeError"} and [row["reason"] for row in run["invalid"]] == ["point_check_failed"]


def test_a_run_with_a_json_store_keeps_its_memory_in_files_beside_it(tmp_path):
    from papyrus_content.ideas.store import JsonStore

    rows, client = one_reference()
    store = JsonStore(tmp_path)
    run_stories(client, Model(verdict=RESTATES), json_store=store)
    [path] = (tmp_path / "rejected").glob("*.json")
    assert json.loads(path.read_text())["subject"] == f"reference:{rows[0]['lineageId']}"
    model = Model()
    assert run_stories(client, model, json_store=JsonStore(tmp_path))["alreadyRejected"] == 1 and model.requests == []


def test_the_router_keeps_one_row_per_subject_in_its_own_table():
    saved = {}
    memory = retry_memory.CallbackMemory(lambda subject: saved.get(retry_memory.sort_key("pub", subject)), lambda subject, record: saved.update({retry_memory.sort_key("pub", subject): record}))
    memory.remember("reference:l1", {"subject": "reference:l1", "connections": ["a"]})
    assert memory.recall("reference:l1")["connections"] == ["a"] and memory.recall("reference:l2") is None
    key = retry_memory.sort_key("pub", "pack:cluster:" + "x" * 2000)
    assert key.startswith("IDEA_REJECTED#pub#") and len(key) < 100 and retry_memory.sort_key("other", "reference:l1") != retry_memory.sort_key("pub", "reference:l1")


def test_a_run_whose_every_reference_waits_for_something_new_still_asks_editors_to_curate():
    rows, client = one_reference()
    memory = retry_memory.DictMemory()
    run_stories(client, Model(verdict=RESTATES), retry_memory=memory)
    [first] = flags(client)
    assert "said no more" in first["reason"] and "Waiting: Reference 1" in first["ask"] and "written again as soon as there is something new" in first["ask"]
    second = run_stories(client, Model(), retry_memory=memory)
    assert second["alreadyRejected"] == 1 and second["curationFlag"]["status"] == "already_open" and len(flags(client)) == 1


def test_the_retired_setting_of_the_old_standard_still_loads_and_is_ignored(capsys):
    from papyrus_content.monitoring_stories import validate_monitor_stories

    for old in ("summary", "more-than-summary", "anything"):
        policy = validate_monitor_stories("p", {"minimumStandard": old, "singleItem": True})
        assert "minimumStandard" not in policy and policy["singleItem"] is True
    assert "ignored_retired_config" in capsys.readouterr().out
    with pytest.raises(ValueError, match="unknown keys"):
        validate_monitor_stories("p", {"minimumStandards": "summary"})
