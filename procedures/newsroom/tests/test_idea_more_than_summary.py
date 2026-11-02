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
from papyrus_content.ideas import connections as rules, monitor_stories as stories, review  # noqa: E402
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


def story(*, dek=("Editors accepted it because claim checking bears on sourcing coverage.", "E1"), body=None, headline=("Foo checks claims against sources", "I1")):
    return {
        "headline": sentence(*headline), "dek": sentence(*dek), "section": "Tools",
        "paragraphs": [{"sentences": [sentence(*entry) for entry in (body or [
            ("Foo is an open tool that checks claims against their sources.", "I1"),
            ("The editors accepted it because claim checking matters to their sourcing coverage.", "I1", "E1"),
        ])]}],
    }


class Model:
    """Answers every request with the same story and records the requests."""

    def __init__(self, answer=None) -> None:
        self.answer = answer or story()
        self.requests: list[dict] = []

    def __call__(self, url, headers, payload):
        self.requests.append(payload)
        return {"status": "completed", "output_text": json.dumps(self.answer), "usage": {"input_tokens": 1000, "output_tokens": 300, "input_tokens_details": {"cached_tokens": 0}}}


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


def link(first, second, *, state="suggested", score=0.8, predicate="related_to"):
    low, high = sorted([first["lineageId"], second["lineageId"]])
    return {"relationState": state, "predicate": predicate, "subjectKind": "reference", "objectKind": "reference", "subjectLineageId": low, "objectLineageId": high,
            "score": score, "createdAt": "2026-10-20T00:00:00Z", "metadata": "{}"}


def run_stories(client, model, *, standard="more-than-summary", pages=lambda url: PAGE, store=None, dry_run=False, **options):
    return stories.draft_monitor_stories(
        client=client, site="example-site", context=context(), json_store=None, transport=model, idea_store=store or FakeIdeaStore(client), review_client=client,
        limit=None, dry_run=dry_run, now=NOW, fetch=pages, minimum_standard=standard, **options,
    )


def reasons(run):
    return [problem["reason"] for entry in run["invalid"] for problem in (entry.get("citationCheck") or {}).get("problems", [])]


# --- the pieces ------------------------------------------------------------------------------------------------------------------


def test_the_minimum_standard_is_one_of_two_and_the_default_is_more_than_a_summary():
    assert rules.DEFAULT_STANDARD == "more-than-summary" and rules.validate_standard("summary") == "summary"
    with pytest.raises(ValueError):
        rules.validate_standard("anything")


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
    unrelated = [entry("dek", "The editors liked a toaster.", "E1"), entry("body", "The editors liked a toaster.", "I1", "E1")]
    assert problems_of(unrelated, connections) == ["connection_ungrounded"]
    related = [entry("dek", "The editors prize claim checking.", "E1"), entry("body", "The editors prize claim checking.", "I1", "E1")]
    assert problems_of(related, connections) == []


def test_the_editors_words_are_reported_only_as_the_editors_view():
    connections = build_connections(REASON, [], [])
    plain = [entry("dek", "Claim checking matters to sourcing coverage.", "E1"), entry("body", "Claim checking matters to sourcing coverage.", "I1", "E1")]
    assert problems_of(plain, connections) == ["editors_view_not_attributed", "editors_view_not_attributed"]


def test_a_message_is_cited_only_with_the_source_or_a_related_reference():
    connections = build_connections(None, [{"text": "Claim checking is overdue."}], [])
    alone = [entry("dek", "A commenter says claim checking is overdue.", "M1"), entry("body", "A commenter says claim checking is overdue.", "M1")]
    assert "message_cited_without_reference" in problems_of(alone, connections)
    joined = [entry("dek", "A commenter says claim checking is overdue.", "M1", "I1"), entry("body", "A commenter says claim checking is overdue.", "M1", "I1")]
    assert problems_of(joined, connections) == []


def test_no_trend_is_claimed_without_counts_but_a_name_is_not_a_claim():
    connections = build_connections(REASON, [], [])
    claim = [entry("dek", "The editors see a trend in claim checking.", "E1"), entry("body", "The editors see claim checking rising.", "I1", "E1")]
    assert problems_of(claim, connections).count("trend_claim_without_signal") == 2
    name = [entry("dek", "Editors accepted Trend Micro for claim checking.", "E1"), entry("body", "Editors accepted Trend Micro for claim checking.", "I1", "E1")]
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


def test_a_confirmed_link_is_a_neighbour_whatever_its_similarity_and_may_carry_the_editors_explanation(monkeypatch):
    rows, base = world(2)
    feed = [link(rows[0], rows[1], state="current", score=None)]
    client = LinkedClient(references=rows, relations=base.relations, feed=feed)
    from papyrus_content.ideas import signal_inputs

    real = signal_inputs.edges_of
    monkeypatch.setattr(signal_inputs, "edges_of", lambda relations: [SimpleNamespace(**vars(edge), explanation="Both cover the same vendor.") for edge in real(relations)])
    knowledge = knowledge_for(client, {rows[1]["lineageId"]: "A summary."})
    [neighbour], _ = knowledge.neighbours_of(rows[0]["lineageId"])
    assert (neighbour.provenance, neighbour.explanation) == ("confirmed", "Both cover the same vendor.")
    handles = [entry.handle for entry in build_connections(None, [], [neighbour]).entries]
    assert handles == ["R1", "X1"]   # the explanation is a connection handle of its own once #1034 supplies it


def test_without_the_explanation_field_a_confirmed_link_is_still_a_neighbour():
    rows, base = world(2)
    client = LinkedClient(references=rows, relations=base.relations, feed=[link(rows[0], rows[1], state="current", score=None)])
    [neighbour], _ = knowledge_for(client, {rows[1]["lineageId"]: "A summary."}).neighbours_of(rows[0]["lineageId"])
    assert neighbour.explanation is None   # before PR #1034 the edge carries no words


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


def test_an_accepted_reference_with_the_editors_reason_is_filed_citing_it_as_their_view():
    rows, client = one_reference()
    model = Model()
    run = run_stories(client, model)
    assert [draft["title"] for draft in run["drafts"]] == ["Foo checks claims against sources"]
    filed = client.filed[0]
    assert json.loads(filed["evidence"])["connections"] == ["acceptReason"] and json.loads(filed["evidence"])["minimumStandard"] == "more-than-summary"
    assert json.loads(filed["targets"]) == [{"type": "entity", "id": f"reference:{rows[0]['lineageId']}"}]
    assert "## What editors said" in filed["body"] and REASON in filed["body"]
    knows = json.loads(model.requests[0]["input"])["what_the_newsroom_knows"]
    assert knows[0]["handle"] == "E1" and knows[0]["text"] == REASON and "not a fact" in knows[0]["note"]
    assert run["connectionsUsed"] == {"acceptReason": 1} and run["nothingToAdd"] == 0
    assert "adds to what the newsroom already knows" in model.requests[0]["instructions"]


def test_a_summary_of_the_source_is_not_filed():
    rows, client = one_reference()
    summary = story(dek=("Foo links each claim in a draft to the source page it came from.", "I1"),
                    body=[("Foo is an open tool that checks claims against their sources.", "I1"), ("It was written in Rust.", "I1")])
    run = run_stories(client, Model(summary))
    assert run["drafts"] == [] and client.filed == []
    assert "dek_without_connection" in reasons(run) and "only_the_source_cited" in reasons(run)
    assert run["checkFailures"] == {"dek_without_connection": 1, "only_the_source_cited": 1}


def test_the_old_standard_still_files_a_summary_so_the_replay_can_compare():
    rows, client = one_reference(reason=False)
    summary = story(dek=("Foo links each claim to its source page.", "I1"), body=[("Foo is an open tool.", "I1"), ("It was written in Rust.", "I1")])
    model = Model(summary)
    run = run_stories(client, model, standard="summary")
    assert len(run["drafts"]) == 1 and run["drafts"][0]["evidence"]["connections"] == [] and run["drafts"][0]["evidence"]["minimumStandard"] == "summary"
    assert "what_the_newsroom_knows" not in json.loads(model.requests[0]["input"]) and model.requests[0]["instructions"].startswith("You draft one short news story")
    assert "adds to what the newsroom already knows" not in model.requests[0]["instructions"]


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
        ("Foo is a tool that checks claims.", "I1"), ("A commenter says claim checking is overdue for the newsroom.", "M1", "I1")])
    assert run_stories(client, Model(describing), pages=lambda url: None, knowledge=knowledge)["checkFailures"] == {"describes_unread_page": 1}
    bearing = story(dek=("A commenter says claim checking is overdue.", "M1", "I1"), body=[
        ("A commenter says claim checking is overdue for the newsroom.", "M1", "I1"), ("The editors accepted it because claim checking matters to their sourcing coverage.", "E1", "I1")])
    run = run_stories(client, Model(bearing), pages=lambda url: None, knowledge=knowledge)
    assert len(run["drafts"]) == 1 and run["drafts"][0]["evidence"]["connections"] == ["acceptReason", "message:M1"]
    assert run["connectionsUsed"] == {"acceptReason+message": 1}


def test_an_unreadable_page_proceeds_with_a_real_related_reference():
    rows, base = world(2, details=UNREADABLE)
    editor_accepted(rows[0])
    client = LinkedClient(references=rows, relations=base.relations, incoming=base.incoming, sections=("Analysis", "Tools"), feed=[link(rows[0], rows[1], score=0.9)])
    knowledge = knowledge_for(client, {rows[1]["lineageId"]: "Reference 2 checks quotations against archives."})
    bearing = story(dek=("The editors link it to a tool that checks quotations against archives.", "E1", "R1"), body=[
        ("Reference 2 checks quotations against archives, which is close to what this item is called.", "R1"),
        ("The editors accepted it because claim checking matters to their sourcing coverage.", "E1", "I1")])
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


def test_the_old_standard_raises_no_curation_flag():
    rows, client = one_reference(reason=False)
    assert run_stories(client, Model(), standard="summary")["curationFlag"] == {"status": "not_applicable"} and flags(client) == []


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
