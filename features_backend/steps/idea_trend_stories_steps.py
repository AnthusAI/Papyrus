from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from ideas_fixtures import AS_OF, NOW, SITE_BASE, FakeClient, FakeTrendModel, history_entry, read_item_page, release_draft, sentence, snapshot_files, trend_draft  # noqa: E402
from papyrus_content import review_requests  # noqa: E402
from papyrus_content.ideas import trends  # noqa: E402
from papyrus_content.ideas.store import JsonStore, ProposalStore  # noqa: E402


class ListingClient(FakeClient):
    listed: list = []
    denied = False

    def graphql(self, query, variables=None):
        if "listProposals" in query:
            if self.denied:
                raise RuntimeError("Not Authorized to access listProposals on type Query")
            return {"listProposals": {"items": self.listed, "nextToken": None}}
        return super().graphql(query, variables)


def directory_of(context) -> Path:
    if not hasattr(context, "trend_directory"):
        context.trend_directory = tempfile.TemporaryDirectory()
        context.add_cleanup(context.trend_directory.cleanup)
    return Path(context.trend_directory.name)


def write(path: Path, document) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    return str(path)


def filed(context) -> list[dict]:
    return [row for row in context.trend_client.proposals if "kind" in row]


@given('a weekly knowledge snapshot for the week of "{week}" with two named clusters and four entities')
def step_snapshot(context, week):
    assert week == AS_OF
    context.trend_client = ListingClient(sections=("Analysis", "News"))
    context.trend_client.listed = []
    context.trend_client.denied = False
    context.trend_drafts = []
    context.trend_snapshot = trends.load_snapshot(write(directory_of(context) / "history" / "2026-10-19.json", history_entry()))


@given('the site has the sections "{first}" and "{second}"')
def step_trend_sections(context, first, second):
    assert {first, second} == {section["title"] for section in context.trend_client.sections}


@given('the site publishes its snapshot as files with an archived earlier week in which "{name}" held {count:d} items')
def step_published_files(context, name, count):
    files, root = snapshot_files(), directory_of(context) / "published"
    write(root / "index.json", files["index"])
    write(root / "clusters.json", files["clusters"])
    write(root / "history" / "index.json", {"entries": [{"asOf": "2026-10-12", "file": "2026-10-12.json"}, {"asOf": AS_OF, "file": "2026-10-19.json"}]})
    write(root / "history" / "2026-10-12.json", {"clusters": [{"uid": "cl-fb1252e1da52", "itemCount": count}]})
    assert name == "Decision models"
    context.trend_snapshot = trends.load_snapshot(str(root))


@given("the site publishes the pages of the releases behind its rising entities")
def step_release_pages(context):
    context.trend_snapshot = {**context.trend_snapshot, "siteBase": SITE_BASE}
    context.trend_fetch_text = read_item_page


@given("an editor can read an earlier story draft Proposal with the same targets")
def step_earlier_proposal(context):
    targets = [{"type": "entity", "id": "platform--hugging-face"}, {"type": "entity", "id": "licence--apache-2-0"}]
    context.trend_client.listed = [{"id": "prop-" + "b" * 32, "kind": "story_draft", "title": "Another angle", "summary": "x", "state": "draft", "targets": json.dumps(targets), "createdAt": "2026-10-20T00:00:00Z"}]


@given("the operator signs in with IAM and cannot read Proposals")
def step_iam(context):
    context.trend_client.denied = True
    patcher = mock.patch.dict(os.environ, {"PAPYRUS_GRAPHQL_AUTH": "iam"})
    patcher.start()
    context.add_cleanup(patcher.stop)


@when("the operator reads the signals of the snapshot")
def step_read_signals(context):
    context.trend_signals = trends.build_signals(context.trend_snapshot, getattr(context, "trend_fetch_text", None))


@when("the model drafts a trend story citing Hugging Face and Apache-2.0")
def step_good_draft(context):
    context.trend_drafts.append(trend_draft())


@when("the model drafts a trend story with a body sentence that cites nothing")
def step_uncited(context):
    draft = trend_draft("Unsupported headline")
    draft["paragraphs"][0]["sentences"].append(sentence("Everyone agrees this matters."))
    context.trend_drafts.append(draft)


@when("the model drafts a trend story with two body sentences that cite one signal")
def step_thin(context):
    context.trend_drafts.append(trend_draft("Thin headline", cites=("S3", "S3"), body=[{"sentences": [sentence("The signal records 15 items.", "S3")]}, {"sentences": [sentence("The weekly count peaked at 7.", "S3")]}]))


@then("the failed draft in the run record keeps its headline, dek, body and citations")
def step_kept(context):
    kept = context.trend_run["invalid"][0]["draft"]
    assert kept["headline"]["text"] == "Thin headline" and kept["dek"]["cites"] and len(kept["paragraphs"]) == 2, kept


@when("the model drafts a trend story with a body sentence citing a signal that does not exist")
def step_unknown(context):
    draft = trend_draft()
    draft["paragraphs"][1]["sentences"][0] = sentence("The two are mentioned together in 5 items.", "S3", "S99")
    context.trend_drafts.append(draft)


@when("the model drafts a trend story stating 40 items for Hugging Face")
def step_number(context):
    draft = trend_draft()
    draft["paragraphs"][0]["sentences"][0] = sentence("Hugging Face appeared in 40 items over the last four weeks.", "S3")
    context.trend_drafts.append(draft)


@when("the model drafts a trend story about the Zed-7B release that cites the release and the two entities")
def step_release_draft(context):
    context.trend_drafts.append(release_draft())


@when("the model drafts a trend story that gives the Zed-7B release the date of another release")
def step_release_wrong_date(context):
    draft = release_draft()
    draft["paragraphs"][0]["sentences"][0] = sentence("Zed released Zed-7B on 2026-10-14.", "I1")
    context.trend_drafts.append(draft)


@when("the model drafts a trend story that cites two releases but only one signal")
def step_releases_one_signal(context):
    draft = release_draft()
    draft["dek"] = sentence("Zed's release on 2026-10-17 is the news.", "I1")
    draft["paragraphs"] = [{"sentences": [sentence("Zed released Zed-7B under Apache-2.0.", "I1"), sentence("The card lists its evaluation limits.", "I2"), sentence("Hugging Face appeared in 15 items.", "S3")]}]
    context.trend_drafts.append(draft)


def run_trends(context, *, dry_run=False, reviews=False):
    client = context.trend_client
    context.trend_model = FakeTrendModel(context.trend_drafts)
    context.trend_root = directory_of(context) / "ideas"
    context.trend_run = trends.draft_trends(
        snapshot=context.trend_snapshot, site="example-site", context={"sections": [{"title": "Analysis"}, {"title": "News"}], "stories": [], "mission": "Explain.", "policy": "Be careful."},
        json_store=JsonStore(context.trend_root), transport=context.trend_model, proposal_store=ProposalStore(client), review_client=client if reviews else None, dry_run=dry_run, now=NOW,
        fetch_text=getattr(context, "trend_fetch_text", None))


@when("the operator drafts trend stories and files them as Proposals")
def step_run(context):
    run_trends(context)


@when("the operator drafts trend stories and files them as Proposals with review requests")
def step_run_reviews(context):
    run_trends(context, reviews=True)


@when("the operator dry-runs the trend drafts")
def step_dry_run(context):
    run_trends(context, dry_run=True, reviews=True)


@then("the signals are the two clusters, then the three trending entities, then the one new entity")
def step_signal_order(context):
    assert [s["id"] for s in context.trend_signals] == [
        "cluster:cl-fb1252e1da52", "cluster:cl-aaaa00000001", "entity:platform--hugging-face", "entity:licence--apache-2-0", "entity:task--routing", "entity:task--typed-decisions"]


@then("each signal names its weekly counts for the {weeks:d} weeks ending {end}")
def step_signal_weeks(context, weeks, end):
    for signal in context.trend_signals:
        assert len(signal["series"]) == weeks and signal["weeks"][-1] == end, signal


@then('{count:d} trend draft is filed as a "{kind}" Proposal')
@then('{count:d} trend drafts are filed as a "{kind}" Proposal')
def step_filed(context, count, kind):
    rows = filed(context)
    assert len(rows) == count and all(row["kind"] == kind for row in rows), context.trend_run


@then("{count:d} trend drafts are filed")
def step_filed_none(context, count):
    assert len(filed(context)) == count, context.trend_run
    assert context.trend_run["ideasCreated"] == count


@then("the draft is proposed by AI and still in the draft state")
def step_ai_draft(context):
    record = context.trend_run["drafts"][0]
    assert (record["proposer"], record["proposedBy"], record["state"]) == ("ai", "AI", "draft"), record


@then('the Proposal targets the entities "{first}" and "{second}"')
def step_targets(context, first, second):
    assert json.loads(filed(context)[0]["targets"]) == [{"type": "entity", "id": first}, {"type": "entity", "id": second}]


@then("every sentence of the draft is recorded with the signals it rests on")
def step_sentences(context):
    sentences = context.trend_run["drafts"][0]["sentences"]
    assert len(sentences) >= 5 and all(entry["signalIds"] for entry in sentences), sentences


@then('the model asked for was "{model}"')
def step_model(context, model):
    assert context.trend_model.requests[0]["model"] == model


@then("the Proposal evidence holds a line chart of Hugging Face with the counts {counts}")
def step_figure(context, counts):
    figure = json.loads(filed(context)[0]["evidence"])["figure"]
    assert figure["type"] == "line" and figure["unit"] == "items per week"
    assert [s["label"] for s in figure["series"]] == ["Hugging Face"]
    assert figure["series"][0]["values"] == [int(n) for n in counts.split(", ")], figure
    context.trend_figure = figure


@then("the chart's weeks run from {first} to {last}")
def step_figure_weeks(context, first, last):
    assert (context.trend_figure["x"][0], context.trend_figure["x"][-1]) == (first, last)


@then("the body lists the signals cited under the sentences that cite them")
def step_body(context):
    body = filed(context)[0]["body"]
    assert "[1]" in body and "## Signals cited" in body and "`entity:platform--hugging-face`" in body


@then('the run record says that sentence failed with "{reason}"')
def step_failed(context, reason):
    problems = context.trend_run["invalid"][0]["citationCheck"]["problems"]
    assert reason in [p["reason"] for p in problems], problems
    assert context.trend_run["invalid"][0]["reason"] == "citation_check_failed"


@then("no Proposal is moved out of the draft state")
def step_not_moved(context):
    assert "transitionProposal" not in json.dumps(context.trend_client.calls)


@then("no request to publish Proposals is made")
def step_not_published(context):
    assert "publish" not in json.dumps(context.trend_client.calls).lower()


@then('one soft review "{reason}" is open for the run\'s batch')
def step_review(context, reason):
    (request,) = review_requests.list_reviews(context.trend_client, sweep=False)
    assert request["mode"] == "soft_review" and request["subject"] == {"type": "batch", "id": context.trend_run["runId"]}
    assert request["reason"] == reason, request["reason"]
    context.trend_request = request


@then("the review links the filed Proposal")
def step_review_links(context):
    assert any(link["type"] == "proposal" and link["id"] == context.trend_run["drafts"][0]["proposalId"] for link in context.trend_request["links"])


@then("the dry run lists {passed:d} draft that passed and {failed:d} that failed the citation check")
def step_dry_counts(context, passed, failed):
    run = context.trend_run
    assert [d["citationCheck"]["status"] for d in run["drafts"]] == ["passed"] * passed
    assert [i["citationCheck"]["status"] for i in run["invalid"]] == ["failed"] * failed


@then("no Proposal is filed, no file is stored and no review is raised")
def step_dry_nothing(context):
    assert filed(context) == [] and not context.trend_root.exists() and context.trend_client.reviews == {}
    assert context.trend_run["review"]["status"] == "skipped"


@then("the run record says the draft has the same targets as the earlier Proposal")
def step_same_targets(context):
    duplicate = context.trend_run["duplicates"][0]
    assert duplicate["reason"] == "same_targets" and duplicate["sameTargetsAs"]["kind"] == "proposal", duplicate


@then("the run record says earlier Proposals could not be read with IAM")
def step_iam_note(context):
    assert "cannot be read with IAM" in context.trend_run["proposalDedupe"]


@then('the cluster "{name}" carries the {count:d} items of the earlier archived week')
def step_archive(context, name, count):
    cluster = next(s for s in context.trend_signals if s["name"] == name)
    assert (cluster["itemCountInPreviousArchive"], cluster["previousArchiveWeek"]) == (count, "2026-10-12")


def entity_signal(context, name):
    return next(s for s in context.trend_signals if s["name"] == name)


@then("Hugging Face carries {count:d} releases from the last four weeks, newest first, each with a title, a summary, a date and a site address")
def step_items(context, count):
    items = entity_signal(context, "Hugging Face")["items"]
    assert len(items) == count and [i["date"] for i in items] == sorted((i["date"] for i in items), reverse=True), items
    assert all(i["title"] and i["summary"] and i["date"] and i["url"].startswith(SITE_BASE) for i in items), items


@then("Apache-2.0 carries only the release inside the window and not the older one")
def step_window(context):
    assert [i["date"] for i in entity_signal(context, "Apache-2.0")["items"]] == ["2026-10-17"]


@then("the clusters carry no releases because the snapshot lists no members for them")
def step_cluster_items(context):
    assert all("items" not in s for s in context.trend_signals if s["kind"] == "cluster")


@then("the model was shown the releases with their summaries and dates")
def step_shown(context):
    sent = json.dumps(context.trend_model.requests[0])
    assert "A 7B coding model with 32k context" in sent and "2026-10-17" in sent and "2026-10-14" in sent, sent


@then("the body marks the cited signals first and then the cited releases")
def step_marks(context):
    body = filed(context)[0]["body"]
    assert "under Apache-2.0. [3]" in body and "1. Hugging Face" in body and "2. Apache-2.0" in body, body


@then('the body lists the cited releases under "Sources" with their titles, dates and addresses')
def step_sources(context):
    body = filed(context)[0]["body"]
    assert "## Sources" in body
    assert "3. Zed releases Zed-7B, a small coding model under Apache-2.0 (2026-10-17) https://site.example/posts/zed-7b/" in body, body
