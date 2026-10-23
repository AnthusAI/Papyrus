from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from ideas_fixtures import CORPUS, NOW, FakeClient, FakeModel, entity, idea, reference, relevance, story  # noqa: E402,F401
from papyrus_content.ideas import digest as digest_module  # noqa: E402
from papyrus_content.ideas.context import load_context  # noqa: E402
from papyrus_content.ideas.pipeline import RunRefused, synthesize  # noqa: E402
from papyrus_content.ideas.store import JsonStore, ProposalStore  # noqa: E402

PUBLISHED = "Prompt injection breaks AI agents"
DECK = "A study shows agents obey instructions hidden in web pages."


def client_of(context) -> FakeClient:
    return context.idea_client


def directory_of(context) -> Path:
    if not hasattr(context, "idea_directory"):
        context.idea_directory = tempfile.TemporaryDirectory()
        context.add_cleanup(context.idea_directory.cleanup)
    return Path(context.idea_directory.name)


def build_digest(context, statuses=None):
    return digest_module.make_digest(client_of(context), publication="example-site", corpus_ids=[CORPUS], since="7d", statuses=statuses, now=NOW)


@given("a site with five accepted references that arrived in the last week")
def step_references(context):
    context.idea_client = FakeClient(references=[reference(n) for n in range(1, 6)], sections=("Analysis", "News"), stories=[story(PUBLISHED, deck=DECK)])
    context.model_ideas = []
    context.feedback = []
    context.tokens = (1000, 400)
    context.cost_cap = 0.5


@given('the site has a mission, the sections "Analysis" and "News", and a published story "{title}"')
def step_site(context, title):
    assert client_of(context).stories[0]["title"] == title


@given('two of the references carry the "include" relevance label')
def step_labels(context):
    rows = client_of(context).references[:2]
    client_of(context).relations = {row["lineageId"]: [relevance(row)] for row in rows}


@given("one more reference is pending review")
def step_pending(context):
    client_of(context).references.append(reference(6, status="pending"))


@when("the operator builds a digest for the last {days:d} days")
def step_digest(context, days):
    context.digest = build_digest(context)


@when("the operator builds a digest for the last {days:d} days again")
def step_digest_again(context, days):
    context.second_digest = build_digest(context)


@when("the operator builds a digest for the last {days:d} days including pending references")
def step_digest_pending(context, days):
    context.digest = build_digest(context, ["accepted", "pending"])


@then("the digest lists {count:d} references")
def step_count(context, count):
    assert len(context.digest["references"]) == count, context.digest["counts"]


@then('the digest has a group of {first:d} references labelled "{first_label}" and a group of {second:d} labelled "{second_label}"')
def step_groups(context, first, first_label, second, second_label):
    groups = [(g["count"], g["label"]) for g in context.digest["groups"]]
    assert groups == [(first, first_label), (second, second_label)] or groups == [(second, second_label), (first, first_label)], groups


@then("every reference in the digest names its title, source, status and why it was included")
def step_fields(context):
    for entry in context.digest["references"]:
        assert all(entry.get(key) for key in ("title", "source", "status", "whyIncluded")), entry


@then("the pending reference is marked as not yet reviewed")
def step_pending_marked(context):
    pending = [e for e in context.digest["references"] if e["status"] == "pending"]
    assert len(pending) == 1 and "Not yet reviewed" in pending[0]["whyIncluded"]


@then("both digests have the same id and the same content")
def step_same(context):
    first, second = context.digest, context.second_digest
    assert first["digestId"] == second["digestId"]
    assert first["references"] == second["references"] and first["groups"] == second["groups"]


HANDLES = {"the first two references": ["R1", "R2"], "different references": None}


def propose(context, title, handles, **extra):
    context.model_ideas.append(idea(title, handles, **extra))


@when('the model proposes the idea "{title}" citing the first two references')
def step_idea_two(context, title):
    propose(context, title, ["R1", "R2"])


@when('the model proposes the idea "{title}" citing only the first reference')
def step_idea_one(context, title):
    propose(context, title, ["R1"])


@when('the model proposes the idea "{title}" citing the first reference and a reference that does not exist')
def step_idea_unknown(context, title):
    propose(context, title, ["R1", "R99"])


@when('the model proposes the idea "{title}" that restates the published story')
def step_idea_restated(context, title):
    propose(context, title, ["R1", "R2"], angle="Agents obey instructions hidden in web pages, a study shows.")


@when('the model proposes the ideas "{first}" and "{second}" citing different references')
def step_two_ideas(context, first, second):
    propose(context, first, ["R1", "R2"], angle="Rotating access keys after an incident.")
    propose(context, second, ["R3", "R4"], angle="What a signature on a model file proves.")


@given('a reviewer declined the idea "{title}"')
def step_declined(context, title):
    context.feedback = [{"title": title, "verdict": "decline", "note": "Key rotation for cloud accounts: too basic."}]


@when("the model reports {input_tokens:d} input tokens and {output_tokens:d} output tokens")
def step_tokens(context, input_tokens, output_tokens):
    context.tokens = (input_tokens, output_tokens)


def run(context, **options):
    if context.digest_for_run is None:
        context.digest_for_run = build_digest(context)
    context.model = FakeModel(context.model_ideas, *context.tokens)
    store = JsonStore(directory_of(context) / "ideas")
    proposal_store = ProposalStore(client_of(context)) if options.pop("proposals", False) else None
    try:
        context.run = synthesize(
            digest=context.digest_for_run, context=load_context(client_of(context), now=NOW), json_store=store, transport=context.model,
            proposal_store=proposal_store, feedback=context.feedback, now=NOW, maximum_cost_usd=options.get("cost_cap", context.cost_cap),
        )
        context.refused = None
    except RunRefused as error:
        context.refused = error


@when("the operator synthesizes ideas from the digest")
def step_synthesize(context):
    context.digest_for_run = None
    run(context)


@when("the operator synthesizes ideas from the digest with the reviewer feedback")
def step_synthesize_feedback(context):
    context.digest_for_run = None
    run(context)


@when("the operator synthesizes ideas from the digest into the site's proposals")
def step_synthesize_proposals(context):
    context.digest_for_run = None
    run(context, proposals=True)


@when("the operator synthesizes ideas with a cost cap of a millionth of a dollar")
def step_synthesize_cap(context):
    context.digest_for_run = None
    run(context, cost_cap=0.000001)


@then("{count:d} idea is created")
@then("{count:d} ideas are created")
def step_created(context, count):
    assert context.run["ideasCreated"] == count, context.run


@then("the idea is a draft story proposed by AI that cites those two references")
def step_idea_shape(context):
    created = context.run["ideas"][0]
    assert (created["kind"], created["state"], created["proposedBy"]) == ("story_draft", "draft", "AI")
    ids = [entry["id"] for entry in context.digest_for_run["references"][:2]]
    assert sorted(created["citedReferenceIds"]) == sorted(ids), created["citedReferenceIds"]


@then("the idea is private and nothing is written to a public data directory")
def step_private(context):
    assert context.run["ideas"][0]["private"] is True
    written = [path for path in directory_of(context).rglob("*") if path.is_file()]
    assert written and all("_data" not in path.parts for path in written)
    assert not any("proposals" in path.name for path in written)


@then("the run reports the idea as dropped for having fewer than two citations")
def step_few(context):
    assert [row["reason"] for row in context.run["invalid"]] == ["fewer_than_two_citations"]


@then("the run reports the idea as dropped for citing an unknown reference")
def step_unknown(context):
    assert context.run["invalid"][0]["reason"].startswith("cites_unknown_references")


@then('the run reports {count:d} near-duplicate of the published story "{title}"')
def step_duplicate(context, count, title):
    duplicates = context.run["duplicates"]
    assert len(duplicates) == count and duplicates[0]["similarTo"]["title"] == title and duplicates[0]["similarTo"]["kind"] == "story", duplicates


@then("the model was shown the reviewer feedback")
def step_feedback_shown(context):
    assert context.model.model_input["reviewer_feedback"] == context.feedback


@then("{count:d} draft story proposals are filed")
def step_filed(context, count):
    filed = [row for row in client_of(context).proposals if "kind" in row]
    assert len(filed) == count and all(row["kind"] == "story_draft" for row in filed), filed


@then("no request to publish proposals is made")
def step_no_publish(context):
    assert "publish" not in json.dumps(client_of(context).calls).lower()


@then("the run records {references:d} references, {stories:d} story and the model name")
def step_inputs(context, references, stories):
    inputs = context.run["inputs"]
    assert (inputs["references"], inputs["stories"], context.run["model"]) == (references, stories, "gpt-6-luna")


@then("the run records the cost of the model call in dollars from the recorded price")
def step_cost(context):
    usage = context.run["usage"]
    expected = round((usage["inputTokens"] * 0.10 + usage["outputTokens"] * 0.50) / 1_000_000, 6)
    assert usage["costUsd"] == expected and usage["costUsd"] > 0, usage


@then("the run is refused before any model call")
def step_refused(context):
    assert context.refused is not None and context.model.requests == []


@then("the run records a pending review of {count:d} idea that was not requested from anyone")
def step_review(context, count):
    review = context.run["review"]
    assert (review["status"], review["requested"], review["ideas"]) == ("pending", False, count), review
