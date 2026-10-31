"""Monitor stories (features_backend/idea-monitor-stories.feature). The backend, the pages and the model are fakes."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from ideas_fixtures import CORPUS, NOW, reference  # noqa: E402
from papyrus_content.ideas import commands, monitor_stories  # noqa: E402
from papyrus_content.ideas.store import JsonStore, ProposalStore  # noqa: E402
from pdf_fixtures import make_pdf  # noqa: E402
from test_monitor_stories import PAGE, MonitorClient, StoryModel, context as site_context, decision, good_story, provenance  # noqa: E402

SITE = "example-site"


def state(context):
    if not hasattr(context, "ms"):
        context.ms = type("State", (), {})()
        context.ms.rows, context.ms.numbers, context.ms.unreadable, context.ms.overrides, context.ms.sources = [], {}, set(), {}, {}
        context.ms.model = None
        context.ms.runs, context.ms.items, context.ms.error = [], [], None
        context.ms.directory = tempfile.TemporaryDirectory()
        context.add_cleanup(context.ms.directory.cleanup)
    return context.ms


def client_of(context) -> MonitorClient:
    held = state(context)
    if not hasattr(held, "client"):
        held.client = MonitorClient(references=held.rows, incoming=held.incoming, relations=held.relations, items=held.items, sections=("Analysis", "Tools"))
    return held.client


@given('a site "{site}" with the sections "{first}" and "{second}"')
def step_site(context, site, first, second):
    held = state(context)
    held.rows, held.incoming, held.relations = [], {}, {}


@given('the site keeps its References in the knowledge corpus "{key}"')
def step_corpus(context, key):
    state(context).corpus = f"knowledge-corpus-{key}"


@given("the monitors of the site delivered these items:")
def step_items(context):
    held = state(context)
    for number, row in enumerate(context.table, start=1):
        number = len(held.rows) + 1
        days = float(row["days ago"])
        status = (row.get("status") or "accepted").strip() if "status" in row.headings else "accepted"
        by = (row.get("accepted by") or "").strip() if "accepted by" in row.headings else ""
        item = reference(number, status=status, days_ago=days, title=row["title"], corpus=getattr(held, "corpus", CORPUS))
        details = {}
        if "likes" in row.headings and row["likes"].strip():
            details["likes"] = int(row["likes"])
        if "summary" in row.headings and row["summary"].strip():
            details["summary"] = row["summary"].strip()
        if "days to accept" in row.headings and row["days to accept"].strip():
            created = datetime.fromisoformat(item["createdAt"].replace("Z", "+00:00"))
            item["curationStatusUpdatedAt"] = (created + timedelta(days=float(row["days to accept"]))).isoformat().replace("+00:00", "Z")
        if by:
            item["curationStatusUpdatedBy"] = by
        held.rows.append(item)
        held.numbers[row["title"]] = number
        held.incoming[item["lineageId"]] = [provenance(item, row["monitor"].strip(), details or None)]
        verdict = row["verdict"].strip()
        if verdict:
            label, score = verdict.split()
            held.relations[item["lineageId"]] = [decision(item, float(score), label)]


@given("a Reference that no monitor delivered arrived {days:d} day ago")
def step_unmonitored(context, days):
    held = state(context)
    item = reference(len(held.rows) + 1, status="accepted", days_ago=days, title="Added by hand")
    held.rows.append(item)
    held.incoming[item["lineageId"]] = []


@given("every linked page can be read")
def step_pages(context):
    state(context).unreadable = set()


PDF_LINES = [["The tool, released on 2026-10-20, reads a draft, finds each claim and links it to the source page it came from.", "It is written in Rust and has 42 contributors."]]


@given('the linked address of "{title}" is a PDF document')
def step_pdf(context, title):
    held = state(context)
    held.sources[held.numbers[title]] = make_pdf(PDF_LINES)


@given('the linked page of "{title}" is a short page that links to its PDF')
def step_wrapper(context, title):
    held = state(context)
    number = held.numbers[title]
    held.sources[number] = "<html><body><h1>Decision</h1><a href='/decision.pdf'>Download the PDF</a></body></html>"
    held.sources[f"{number}/pdf"] = make_pdf(PDF_LINES)


@given('the linked address of "{title}" is a PDF that cannot be read')
def step_broken_pdf(context, title):
    held = state(context)
    held.sources[held.numbers[title]] = b"%PDF-1.4 truncated"


@given('the linked page of "{title}" cannot be read')
def step_unreadable(context, title):
    held = state(context)
    held.unreadable.add(held.numbers[title])


def row_of(context, title):
    held = state(context)
    return held.rows[held.numbers[title] - 1]


@given('the model writes a story for "{title}" whose dek cites nothing')
def step_uncited(context, title):
    row = row_of(context, title)
    story = good_story(row["sourceUri"], number=state(context).numbers[title])
    story["dek"]["cites"] = []
    state(context).overrides[row["sourceUri"]] = story


@given('the model writes a story for "{title}" with the body sentence "{sentence}"')
def step_sentence(context, title, sentence):
    row = row_of(context, title)
    story = good_story(row["sourceUri"], number=state(context).numbers[title])
    story["paragraphs"][0]["sentences"][0]["text"] = sentence
    state(context).overrides[row["sourceUri"]] = story


@given('an item already carries the Reference of "{title}"')
def step_promoted(context, title):
    held = state(context)
    held.items.append({"id": "item-promoted", "metadata": {"frontMatterYaml": f"monitorRecord:\n  referenceId: {row_of(context, title)['id']}\n"}})


@given('"{title}" links to the same address as "{other}"')
def step_same_address(context, title, other):
    row_of(context, title)["sourceUri"] = row_of(context, other)["sourceUri"]


@given('another run files a Proposal for "{title}" after this run has read the existing ones')
def step_concurrent(context, title):
    state(context).concurrent = title


def with_concurrent_run(context, client):
    """The backend as seen by a run that overlaps another: the Proposal appears after the run's first read of the story drafts."""
    held = state(context)
    title = getattr(held, "concurrent", None)
    if title is None or getattr(client, "_overlap_installed", False):
        return
    original, reads = client.graphql, []

    def graphql(query, variables=None):
        if "listStoryDrafts" in query:
            reads.append(1)
            if len(reads) == 2:
                client.filed.append({"id": "prop-concurrent", "state": "draft", "createdAt": "2026-10-23T12:00:01Z", "kind": "story_draft", "title": title,
                                     "targets": json.dumps([{"type": "entity", "id": f"reference:{row_of(context, title)['lineageId']}"}])})
        return original(query, variables)

    client.graphql = graphql
    client._overlap_installed = True


def fetch_for(context):
    held = state(context)

    def fetch(url):
        number = int(url.split("example")[1].split(".org")[0])
        if url.endswith(".pdf"):
            return held.sources.get(f"{number}/pdf")
        return None if number in held.unreadable else held.sources.get(number, PAGE)

    return fetch


def run_drafts(context, *, limit=monitor_stories.DEFAULT_LIMIT, dry_run=False, proposals=False, **options):
    held = state(context)
    client = client_of(context)
    if held.model is None:
        held.model = StoryModel(by_url=held.overrides)
    held.model.by_url = held.overrides
    with_concurrent_run(context, client)
    with mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "iam"}):
        run = monitor_stories.draft_monitor_stories(
            client=client, site=SITE, context=site_context(), json_store=JsonStore(Path(held.directory.name)), transport=held.model,
            proposal_store=ProposalStore(client) if proposals else None, review_client=client, limit=limit, dry_run=dry_run, now=NOW,
            fetch=fetch_for(context), **options,
        )
    held.runs.append(run)
    return run


@when('the operator drafts monitor stories reading the statuses "{statuses}"')
def step_statuses(context, statuses):
    run_drafts(context, statuses=statuses.split(","))


@when("the operator drafts monitor stories with the default limit")
def step_default(context):
    run_drafts(context)


@when('the operator drafts monitor stories from the corpus "{key}"')
def step_from_corpus(context, key):
    run_drafts(context, corpus_key=key)


@when("the operator drafts monitor stories with a limit of {limit:d}")
def step_limit(context, limit):
    run_drafts(context, limit=limit)


@when('the operator drafts monitor stories with a limit of {limit:d} and a window of "{window}"')
def step_window(context, limit, window):
    run_drafts(context, limit=limit, since=window)


@when("the operator drafts monitor stories as a dry run with a limit of {limit:d}")
def step_dry_limit(context, limit):
    run_drafts(context, limit=limit, dry_run=True)


@when("the operator drafts monitor stories and files them as Proposals with a limit of {limit:d}")
def step_files(context, limit):
    run_drafts(context, limit=limit, proposals=True)


@when("the operator drafts monitor stories as a dry run")
def step_dry(context):
    run_drafts(context, dry_run=True, proposals=True)


@when("the operator drafts monitor stories with a cost cap of {cap} dollars")
def step_cap(context, cap):
    run_drafts(context, maximum_cost_usd=float(cap))


@when('an editor declines the Proposal')
def step_decline(context):
    for row in client_of(context).filed:
        row["state"] = "declined"


@when("the operator drafts monitor stories without an OpenAI key")
def step_no_key(context):
    held = state(context)
    try:
        with mock.patch.object(commands, "create_authoring_client", return_value=(client_of(context), {})), mock.patch.object(commands, "resolve_openai_api_key", return_value=None):
            commands.monitor_stories_command(["--site", SITE, "--dry-run", "--out", held.directory.name])
    except ValueError as error:
        held.error = str(error)


def last(context):
    return state(context).runs[-1]


def titles_of(run):
    return [draft["citedItems"][0]["title"] for draft in run["drafts"]]


@then("{count:d} stories are drafted")
def step_count(context, count):
    assert len(last(context)["drafts"]) == count, titles_of(last(context))


@then("{count:d} story is drafted")
def step_one(context, count):
    assert len(last(context)["drafts"]) == count, titles_of(last(context))


@then("{count:d} story is drafted from the stored details")
def step_stored(context, count):
    run = last(context)
    assert [draft["sourceText"] for draft in run["drafts"]] == ["stored details"] * count, run["invalid"]


@then('the drafted stories name the monitors "{first}", "{second}" and "{third}"')
def step_monitors(context, first, second, third):
    assert sorted(draft["monitorId"] for draft in last(context)["drafts"]) == sorted([first, second, third])


@then('the stories drafted are "{first}" and "{second}"')
def step_two(context, first, second):
    assert sorted(titles_of(last(context))) == sorted([first, second]), titles_of(last(context))


@then('the three stories drafted are "{first}", "{second}" and "{third}"')
def step_three(context, first, second, third):
    assert sorted(titles_of(last(context))) == sorted([first, second, third]), titles_of(last(context))


@then('the stories drafted are "{title}"')
def step_one_title(context, title):
    assert titles_of(last(context)) == [title], titles_of(last(context))


@then("the run record counts 1 item judged not relevant and 1 that no monitor delivered")
def step_counts(context):
    inputs = last(context)["inputs"]
    assert (inputs["judgedNotRelevant"], inputs["notMonitored"]) == (1, 1), inputs


@then("the run record has no window")
def step_no_window(context):
    assert last(context)["window"]["since"] is None, last(context)["window"]


@then("the run record learned a freshness of {tau:f} days from {examples:d} examples")
def step_learned(context, tau, examples):
    fresh = last(context)["freshness"]
    assert abs(fresh["tauDays"] - tau) < 0.001 and fresh["examples"] == examples, fresh


@then("the run record has no freshness weight")
def step_no_freshness(context):
    assert last(context)["freshness"]["tauDays"] is None, last(context)["freshness"]


@then("the run record counts {count:d} item skipped for sharing an address with a drafted one")
def step_same_source(context, count):
    assert last(context)["inputs"]["sameSource"] == count, last(context)["inputs"]


@then("no Proposal is filed by this run")
def step_no_filing(context):
    assert [row["id"] for row in client_of(context).filed if row["id"] != "prop-concurrent"] == []
    assert last(context)["drafts"] == []


@then('the run record says "{title}" was already drafted')
def step_already_drafted(context, title):
    assert any(row["reason"] == "already_drafted" and row["title"] == title for row in last(context)["skipped"]), last(context)["skipped"]


@then("the model was asked exactly {count:d} times")
def step_asked(context, count):
    assert len(state(context).model.requests if state(context).model else []) == count


@then("the model was asked exactly {count:d} times in all")
def step_asked_all(context, count):
    assert len(state(context).model.requests) == count


@then("the model was shown the text of the PDF as the source")
def step_shown_pdf(context):
    source = json.loads(state(context).model.requests[0]["input"])["source"]
    assert "reads a draft" in source["page_text"] and "<" not in source["page_text"], source


@then("the model was shown the text of the linked page as the source")
def step_shown(context):
    source = json.loads(state(context).model.requests[0]["input"])["source"]
    assert "reads a draft" in source["page_text"] and source["handle"] == "I1", source


@then('the model was told the source is from the "{monitor}" monitor and was not shown the relevance score')
def step_not_shown(context, monitor):
    shown = json.loads(state(context).model.requests[0]["input"])
    assert shown["source"]["monitor"] == monitor
    assert "0.8" not in json.dumps(shown)


@then('"{title}" is skipped because there is no source text')
def step_skipped(context, title):
    assert [(row["title"], row["reason"]) for row in last(context)["skipped"]] == [(title, "no_source_text")]


@then("no Proposal is filed")
def step_none_filed(context):
    assert client_of(context).filed == []


@then('the run record says the dek failed with "{reason}"')
def step_dek(context, reason):
    problems = last(context)["invalid"][0]["citationCheck"]["problems"]
    assert any(problem["where"] == "dek" and problem["reason"] == reason for problem in problems), problems


@then('the run record says a sentence failed with "{reason}"')
def step_failed(context, reason):
    problems = last(context)["invalid"][0]["citationCheck"]["problems"]
    assert any(problem["reason"].startswith(reason) for problem in problems), problems


@then('the Proposals filed are for "{first}" and "{second}"')
def step_filed_two(context, first, second):
    assert titles_filed(context) == [first, second], titles_filed(context)


def titles_filed(context):
    held = state(context)
    by_lineage = {row["lineageId"]: row["title"] for row in held.rows}
    return [by_lineage[json.loads(filed["targets"])[0]["id"].removeprefix("reference:")] for filed in client_of(context).filed]


@then('the Proposals filed are for "{title}"')
def step_filed_for(context, title):
    assert titles_filed(context) == [title], titles_filed(context)


@then('1 "story_draft" Proposal is filed and it is proposed by AI and still in the draft state')
def step_proposal(context):
    filed = client_of(context).filed
    assert len(filed) == 1 and filed[0]["kind"] == "story_draft" and filed[0]["state"] == "draft"
    assert last(context)["drafts"][0]["proposedBy"] == "AI"


@then("the Proposal body cites the address of the item")
def step_body(context):
    filed = client_of(context).filed[0]
    url = row_of(context, next(iter(state(context).numbers)))["sourceUri"]
    assert url in filed["body"] and "## Source" in filed["body"] and " [1]" in filed["body"]


@then('the Proposal evidence names the "{monitor}" monitor and the address of the item')
def step_evidence(context, monitor):
    evidence = json.loads(client_of(context).filed[0]["evidence"])
    url = row_of(context, next(iter(state(context).numbers)))["sourceUri"]
    assert evidence == {"signals": 1, "source": f"{monitor} monitor: {url}"}, evidence


@then("the Proposal targets the Reference it is about")
def step_targets(context):
    lineage = state(context).rows[0]["lineageId"]
    assert json.loads(client_of(context).filed[0]["targets"]) == [{"type": "entity", "id": f"reference:{lineage}"}]


@then('model "{model}" was the only model asked')
def step_model(context, model):
    assert {request["model"] for request in state(context).model.requests} == {model}


@then("one soft review request covers the run")
def step_review(context):
    review = last(context)["review"]
    assert review["status"] == "requested" and len(client_of(context).reviews) == 1, review


@then("no review was requested")
def step_no_review(context):
    assert last(context)["review"]["requested"] is False and client_of(context).reviews == {}


@then("the run record says it stopped for cost")
def step_stopped(context):
    assert "--max-cost-usd" in last(context)["stoppedForCost"]


@then("the operator is told the command needs OPENAI_API_KEY")
def step_key(context):
    assert state(context).error and "OPENAI_API_KEY" in state(context).error


@then("the run record counts {count:d} pending item that was not read because it was not accepted")
def step_not_accepted(context, count):
    assert last(context)["inputs"]["notAccepted"] == count, last(context)["inputs"]


@then("the run record counts {count:d} pending items that were not read because they were not accepted")
def step_not_accepted_plural(context, count):
    step_not_accepted(context, count)
