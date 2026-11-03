"""Editors rate a Reference with stars and the idea pipeline reads the rating (features_backend/reference-stars.feature). Backend and model are fakes."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import os  # noqa: E402

os.environ.setdefault("PAPYRUS_GRAPHQL_AUTH", "iam")

from papyrus_content import reference_stars, reference_vote  # noqa: E402
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient  # noqa: E402
from papyrus_content.ideas import rated_outcomes, retry_memory, review  # noqa: E402
from papyrus_content.ideas.context_packs import build_packs, drop_lowest_ranked, rank_packs  # noqa: E402
from papyrus_content.ideas.item_signals import ordered_lineage_ids, ordered_queue, score_items  # noqa: E402
from papyrus_content.ideas.signal_inputs import load_signal_inputs  # noqa: E402
from test_idea_context_packs import LOOKUPS, NOW, acceptance_votes, inputs, vote  # noqa: E402
from test_idea_more_than_summary import Model, one_reference, run_stories  # noqa: E402
from test_item_signals import background, candidate, lively_thread  # noqa: E402
from test_reference_stars import _Reader, rated, with_ratings  # noqa: E402
from test_monitor_stories import world  # noqa: E402

STAMP = "2026-11-02T10:00:00Z"
RESTATES = {"verdict": "restates", "claim": "", "repeats_itself": False, "exposes_process": False, "reason": "It restates the source."}


def held(context) -> SimpleNamespace:
    if not hasattr(context, "stars"):
        context.stars = SimpleNamespace(row={}, error=None, queue=None, ids=None, plain=None, packs=None, pack=None, member=None, rows=None, client=None, model=None, run=None, memory=None, signals=None, pending=None)
    return context.stars


def rate(row, stars, who="an editor"):
    row.update(reference_stars.star_fields(stars, rated_by=who, rated_at=STAMP))


@given("an editor rated a Reference {stars:d} stars")
def _rated(context, stars):
    held(context).row = {"id": "r1", "curationStatus": "accepted", "curationActorKind": "human", "curationStatusUpdatedBy": "an editor", "curationStatusReason": "Fits."}
    rate(held(context).row, stars)
    held(context).before = {key: value for key, value in held(context).row.items() if not key.startswith("star")}


@when("the editor rates it {stars:d} stars")
def _rate_again(context, stars):
    rate(held(context).row, stars, "another editor")


@when("the editor clears the rating")
def _clear(context):
    held(context).row.update(reference_stars.star_fields(None))


@then("the Reference records {stars:d} stars with who rated and when")
def _records(context, stars):
    assert reference_stars.latest_stars(held(context).row) == {"stars": stars, "ratedAt": STAMP, "ratedBy": "another editor"}


@then("the Reference's vote and curation status are exactly as they were")
def _vote_untouched(context):
    state = held(context)
    assert {key: value for key, value in state.row.items() if not key.startswith("star")} == state.before


@then("the Reference records no stars, no rater and no time")
def _none(context):
    assert reference_stars.latest_stars(held(context).row) is None and (held(context).row["starRatedAt"], held(context).row["starRatedBy"]) == (None, None)


@when("an editor rates a Reference {stars:d} stars")
def _refused(context, stars):
    try:
        reference_stars.star_fields(stars)
    except ValueError as error:
        held(context).error = str(error)


@then("the rating is refused with the range one to five")
def _range(context):
    assert "from 1 to 5" in held(context).error


@given("a pending Reference rated {stars:d} stars")
def _pending(context, stars):
    state = held(context)
    rows, state.client = world(1, status="pending")
    rows[0].update(predictedAcceptProbability=0.2, curationStatusKey="knowledge-corpus-example-site#pending")
    rate(rows[0], stars)
    state.rows = rows
    state.row = rows[0]


@then("the Reference has no vote for the Cyclotron to learn from")
def _no_vote(context):
    assert reference_vote.latest_vote(held(context).row) is None


@then("a vote carries no stars")
def _vote_no_stars(context):
    assert "starRating" not in reference_vote.vote_fields(reference_vote.HUMAN)


@given("the site has a Reference with a lively thread and a Reference with five stars and a message and a Reference the Cyclotron scores very high")
def _three(context):
    state = held(context)
    messages = lively_thread("lively") + lively_thread("starred", count=1)
    state.signals = with_ratings(inputs(messages=messages, votes=[vote("starred", 3), vote("lively", 2), *background()]), rated("starred", 5))
    state.candidates = [candidate("high-score", "hn", 0.99), candidate("lively"), candidate("starred")]


@given("a Reference rated {stars:d} stars with no other evidence")
def _alone(context, stars):
    state = held(context)
    state.signals = with_ratings(inputs(votes=background()), rated("loved", stars))
    state.candidates = [candidate("loved"), candidate("unrated")]


@given("a site whose best-scored Reference an editor rated 1 star")
def _doubted(context):
    state = held(context)
    state.candidates = [candidate(f"ref-{number}", "hn", 0.01 * number) for number in range(1, 41)]
    state.plain = ordered_lineage_ids(ordered_queue([], score_items(inputs(), state.candidates)))
    state.signals = with_ratings(inputs(), rated("ref-40", 1))


@when("the idea queue is ordered")
def _order(context):
    state = held(context)
    state.ids = ordered_lineage_ids(ordered_queue([], score_items(state.signals, state.candidates)))


@then("the Reference with five stars and a message is first")
def _first(context):
    assert held(context).ids[0] == "starred"


@then("the Reference is in the queue")
def _in_queue(context):
    assert held(context).ids == ["loved"]


@then("that Reference is last in the queue")
def _last(context):
    assert held(context).ids[-1] == "ref-40"


@then("every Reference is still in the queue")
def _all(context):
    assert sorted(held(context).ids) == sorted(held(context).plain)


@given("a pack whose last member an editor rated 5 stars")
def _pack(context):
    state = held(context)
    base = inputs(votes=[*acceptance_votes(), *background()])
    plain = rank_packs(build_packs(base, LOOKUPS, now=NOW))
    state.pack = plain[-1]
    state.member = state.pack.accepted_lineage_ids[-1]
    state.signals = with_ratings(base, rated(state.member, 5))


@when("the packs are ranked and the pack is trimmed by one member")
def _rank_pack(context):
    state = held(context)
    state.packs = rank_packs(build_packs(state.signals, LOOKUPS, now=NOW))
    mine = next(pack for pack in state.packs if pack.pack_id == state.pack.pack_id)
    state.trimmed = drop_lowest_ranked(mine)


@then("the pack is offered first")
def _pack_first(context):
    assert held(context).packs[0].pack_id == held(context).pack.pack_id


@then("the five star member is still in the pack")
def _member(context):
    assert held(context).member in held(context).trimmed.accepted_lineage_ids


@given("an accepted Reference with an editor's reason and {stars:d} stars")
def _accepted_starred(context, stars):
    state = held(context)
    state.rows, state.client = one_reference()
    rate(state.rows[0], stars)
    state.model = Model()


@when("the run drafts ideas for the rated Reference")
def _draft(context):
    state = held(context)
    state.model = state.model or Model()
    state.run = run_stories(state.client, state.model, retry_memory=state.memory)


@then("the writer's input says the editors gave {stars:d} of 5 stars")
def _input(context, stars):
    held(context).drafting = json.loads(held(context).model.drafting[0]["input"])
    assert held(context).drafting["editor_rating"] == {"stars": stars, "of": 5}


@then("no connection handle carries the stars")
def _no_handle(context):
    assert all("stars" not in entry for entry in held(context).drafting["what_the_newsroom_knows"])


@then("the writer's instructions say the rating is never reported")
def _never_reported(context):
    instructions = held(context).model.drafting[0]["instructions"]
    assert "editor_rating" in instructions and "never reported" in instructions


@given("an accepted Reference whose idea was rejected for adding nothing")
def _rejected(context):
    state = held(context)
    state.rows, state.client = one_reference()
    state.memory = retry_memory.DictMemory()
    state.model = Model(verdict=RESTATES)
    state.run = run_stories(state.client, state.model, retry_memory=state.memory)
    state.model = Model()


@when("an editor rates it {stars:d} stars")
def _rate_it(context, stars):
    rate(held(context).rows[0], stars)


@then("the run records that it tried again because of the new rating")
def _retried(context):
    assert [row["newConnections"] for row in held(context).run["retriedWithNewConnections"]] == [["stars:5"]]


@given("an accepted Reference rated {stars:d} stars that the newsroom knows nothing about beyond its source")
def _nothing_known(context, stars):
    state = held(context)
    state.rows, state.client = one_reference(reason=False)
    rate(state.rows[0], stars)
    state.model = Model()


@then("the run record lists it as rated and without an idea because there was nothing to add")
def _listed(context):
    [row] = held(context).run["ratedNoIdea"]
    assert (row["stars"], row["reason"]) == (5, "nothing_to_add")


@then("the curation flag names it and says why")
def _flag(context):
    run = {**held(context).run, "inputs": {"candidates": 0, "notAccepted": 0}}
    _, ask = review.curation_flag_text(run, [])
    assert "You rated 1 Reference highly" in ask and "5 stars" in ask


@when("the signals are read")
def _read(context):
    state = held(context)
    state.signals = load_signal_inputs(_Reader(state.rows), site="example-site", now=NOW)


@then("its stars are available in the pending context")
def _pending_context(context):
    [pending] = held(context).signals.pending_context
    assert pending.stars == 5


@then("the run drafts no idea from it")
def _no_idea(context):
    state = held(context)
    assert run_stories(state.client, Model())["drafts"] == []


class _SchemaWithoutStars:
    """Stands in for the connection to a site on an older version: AppSync refuses a query naming a star field."""

    def __init__(self):
        self.queries = []
        self.refusals = 0

    def request(self, _method, _path, body=None, headers=None):
        self.queries.append(json.loads(body)["query"])

    def getresponse(self):
        refused = "starRating" in self.queries[-1]
        self.refusals += refused
        answer = ({"errors": [{"message": "Validation error of type FieldUndefined: Field 'starRating' in type 'Reference' is undefined"}]}
                  if refused else {"data": {"listReferences": {"items": [{"id": "reference-1"}]}}})
        return SimpleNamespace(status=200, reason="OK", read=lambda: json.dumps(answer).encode("utf-8"))

    def close(self):
        pass


@given("a site whose schema has no star fields on a Reference")
def step_site_without_star_fields(context):
    context.old_site = _SchemaWithoutStars()
    context.old_site_client = PapyrusGraphQLAuthoringClient(endpoint="https://example.test/graphql", header_factory=lambda _payload: {},
                                                            tenant_id="old-site")
    context.old_site_client._connection = context.old_site


@when("the router reads that site's References twice")
def step_read_old_site_twice(context):
    query = "query { listReferences { items { id starRating starRatedAt starRatedBy updatedAt } } }"
    context.old_site_reads = [context.old_site_client.graphql(query), context.old_site_client.graphql(query)]


@then("both reads return the References")
def step_both_reads_return(context):
    assert [read["listReferences"]["items"] for read in context.old_site_reads] == [[{"id": "reference-1"}]] * 2


@then("only the first read was refused for naming the star fields")
def step_only_first_refused(context):
    assert context.old_site.refusals == 1
    assert len(context.old_site.queries) == 3 and "starRat" not in context.old_site.queries[-1]
