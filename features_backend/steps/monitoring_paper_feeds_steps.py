import json
from pathlib import Path
import re
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_feed as tf  # noqa: E402
from papyrus_content import monitoring_router as mr  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402
from test_monitoring_router import FakeTable  # noqa: E402

PAPER_BOTH = "2611.03424"
HOURS_6 = 6 * 3600


def feed_monitor(context, url, body=None):
    context.feed_table = FakeTable()
    context.feed_table.put_item(tf.feed_config(url))
    context.feed_url, context.feed_body, context.requests = url, body, []


def feed_fetch(context):
    def fetch(url):
        context.requests.append(url)
        return context.feed_body
    return fetch


def collect_feed(context, offset=0):
    context.refusal = None
    try:
        context.result = run_collection(DynamoStore(context.feed_table), "papers", fetch=feed_fetch(context), now=tf.NOW + offset)
    except ValueError as error:      # a config the collector refuses is an error of the invocation, not a receipt
        context.refusal = str(error)


def feed_discoveries(context):
    return {row["sourceId"]: row for row in context.feed_table.by_prefix("DISC#")}


# --- feed monitors ----------------------------------------------------------

@given("a feed monitor for the arXiv artificial intelligence RSS feed")
def step_ai(context):
    feed_monitor(context, tf.AI_FEED)


@given("a feed monitor for the arXiv security RSS feed")
def step_security(context):
    feed_monitor(context, tf.SECURITY_FEED)


@given("a feed monitor for the arXiv API Atom feed")
def step_atom(context):
    feed_monitor(context, tf.ATOM_FEED)


@given("a feed monitor for the METR RSS feed")
def step_metr(context):
    feed_monitor(context, tf.METR_FEED)


@given("the feed holds a blog post, a note, an evaluation, a post that links to a paper and a post that links to a page on the site")
def step_metr_body(context):
    context.feed_body = tf.read("metr-rss.xml")


@given("a feed monitor whose address is on a host outside the allowed list")
def step_outside(context):
    feed_monitor(context, "https://papers.example.test/rss.xml", tf.read("arxiv-ai-rss.xml"))


@given("the feed holds two new papers, a cross-listed paper and two revisions of old papers")
def step_rss_body(context):
    context.feed_body = tf.read("arxiv-ai-rss.xml")


@given("the feed holds two papers with versioned addresses")
def step_atom_body(context):
    context.feed_body = tf.read("arxiv-api-atom.xml")


@given("the feed declares a DOCTYPE with an ENTITY")
def step_doctype(context):
    context.feed_body = tf.read("doctype-rss.xml")


@given("the feed holds no entries")
def step_empty(context):
    context.feed_body = tf.read("empty-rss.xml")


@given("the feed is cut off in the middle of an entry")
def step_malformed(context):
    context.feed_body = tf.read("malformed-rss.xml")


@given("the feed monitor has collected")
def step_collected(context):
    collect_feed(context)


@when("the feed monitor collects")
def step_collect(context):
    collect_feed(context)


@when("the feed monitor collects again six hours later")
def step_collect_later(context):
    collect_feed(context, HOURS_6 + 60)


# --- what was recorded ------------------------------------------------------

@then("three papers are recorded and the pass is complete")
def step_three(context):
    assert context.result["status"] == "complete" and context.result["new"] == 3, context.result
    assert len(feed_discoveries(context)) == 3


@then("two papers are recorded and the pass is complete")
def step_two(context):
    assert context.result["status"] == "complete" and context.result["new"] == 2, context.result


@then("a paper's canonical URL is its arXiv address and its source id is the bare arXiv id")
def step_url_and_id(context):
    row = feed_discoveries(context)["2611_00015"]
    assert row["canonicalUrl"] == "https://arxiv.org/abs/2611.00015" and row["details"]["arxivId"] == "2611.00015"


@then("a paper carries its title, publication date, authors, categories and abstract")
def step_fields(context):
    row = feed_discoveries(context)["2611_00015"]
    assert row["title"].startswith("Output-Aware Block Influence") and row["sourcePublishedAt"] == "2026-11-03T05:00:00Z"
    details = row["details"]
    assert details["title"] == row["title"] and details["publishedAt"] == row["sourcePublishedAt"]
    assert details["authors"][0] == "Kyle Lemoi" and details["categories"] == ["cs.LG", "cs.AI"] and details["abstract"]


@then("the abstract has no arXiv header line and no Abstract label, and its LaTeX is unchanged")
def step_abstract(context):
    abstract = feed_discoveries(context)["2611_00015"]["details"]["abstract"]
    assert abstract.startswith("Depth pruning removes") and "Announce Type" not in abstract and "Abstract:" not in abstract
    assert "$BI$" in abstract and "$J-BI$" in abstract


@then("each paper waits for the router and records that it came from a feed")
def step_waits(context):
    rows = list(feed_discoveries(context).values())
    assert rows and all(r["routing"] == "collected" and r["sourceType"] == "feed" for r in rows)


@then("a paper's canonical URL is its arXiv address without the version")
def step_unversioned(context):
    row = feed_discoveries(context)["2611_03558"]
    assert row["canonicalUrl"] == "https://arxiv.org/abs/2611.03558" and row["details"]["abstract"].startswith("We consider")


@then("five items are recorded and the pass is complete")
def step_five(context):
    assert context.result["status"] == "complete" and context.result["new"] == 5, context.result
    assert len(feed_discoveries(context)) == 5


@then("each item's canonical URL is the feed entry's link, even when the link is on another site or not under blog")
def step_metr_urls(context):
    urls = {r["canonicalUrl"] for r in feed_discoveries(context).values()}
    assert urls == {"https://metr.org/blog/2026-11-05-rd-section-anthropic-risk-report-august-2026-review/",
                    "https://metr.org/notes/2026-09-27-implementing-a-basic-blocking-action-monitor/",
                    "https://metr.org/evaluations/gpt-5-1-codex-max-report/",
                    "https://arxiv.org/abs/2503.17354", "https://metr.org/fsp"}


@then("each item carries its title, publication date and the post's content as its abstract")
def step_metr_details(context):
    for row in feed_discoveries(context).values():
        assert row["details"]["title"] and row["details"]["publishedAt"] and "abstract" in row["details"], row


@then("an item's source id comes from the entry's guid")
def step_metr_ids(context):
    assert all(sid.startswith("https___metr_org_blog_") or sid.startswith("https___metr_org_notes_") for sid in feed_discoveries(context))


@then("the new papers and the cross-listed paper are recorded")
def step_kept(context):
    rows = feed_discoveries(context)
    assert set(rows) == {"2611_00015", "2611_03424", "2609_23790"}
    assert {r["details"]["announceType"] for r in rows.values()} == {"new", "cross"}


@then("neither revision is recorded")
def step_revisions(context):
    urls = {r["canonicalUrl"] for r in feed_discoveries(context).values()}
    assert not urls & {"https://arxiv.org/abs/1903.07745", "https://arxiv.org/abs/2303.16880"}


@then("the pass is refused because the host is not allowed, before anything is requested")
def step_refused(context):
    assert context.refusal and "https URL on one of" in context.refusal and "rss.arxiv.org" in context.refusal
    assert context.requests == []


@then("nothing is recorded")
def step_nothing(context):
    assert not context.feed_table.by_prefix("DISC#")


@then("the pass fails with a note that the XML declaration is not supported")
def step_doctype_failed(context):
    assert context.result["status"] == "failed"
    assert "unsupported XML declaration" in json.dumps(context.result["errors"])


@then("the pass is complete and nothing is recorded")
def step_empty_ok(context):
    assert context.result["status"] == "complete" and context.result["new"] == 0 and not context.feed_table.by_prefix("DISC#")


@then("the pass fails with a fetch error")
def step_fetch_error(context):
    assert context.result["status"] == "failed" and context.result["errors"][0]["stage"] == "fetch"


@then("no paper is new and the three papers are reported unchanged")
def step_unchanged(context):
    assert context.result["new"] == 0 and context.result["revised"] == 0 and context.result["unchanged"] == 3, context.result


# --- Hugging Face daily papers ---------------------------------------------------

@given("a Hugging Face papers monitor")
def step_hf_monitor(context):
    context.hf_table = FakeTable()
    context.hf_table.put_item(tf.papers_config(lookbackDays=2, pageSize=2))


@given("Hugging Face lists three daily papers picked on two recent days and one earlier day")
def step_hf_rows(context):
    rows = tf.hf_rows()
    assert [r["paper"]["submittedOnDailyAt"][:10] for r in rows] == ["2026-11-03", "2026-11-03", "2026-10-30"]
    context.daily = tf.Daily(rows)


@when("the Hugging Face papers monitor collects")
def step_hf_collect(context):
    context.hf_result = run_collection(DynamoStore(context.hf_table), "papers-huggingface", fetch=context.daily, now=tf.NOW)


def hf_discoveries(context):
    return {row["sourceId"]: row for row in context.hf_table.by_prefix("DISC#")}


@then("the papers inside the window are recorded and the earlier one is not")
def step_hf_window(context):
    assert context.hf_result["new"] == 2 and set(hf_discoveries(context)) == {"2611_03424", "2611_03097"}, context.hf_result


@then("each paper's canonical URL is its arXiv address")
def step_hf_urls(context):
    rows = hf_discoveries(context)
    assert {r["canonicalUrl"] for r in rows.values()} == {"https://arxiv.org/abs/2611.03424", "https://arxiv.org/abs/2611.03097"}
    assert all(r["sourceType"] == "huggingface-papers" and r["routing"] == "collected" for r in rows.values())


@then("a paper keeps its upvotes, comment count, abstract, submitter and organization")
def step_hf_details(context):
    details = hf_discoveries(context)["2611_03424"]["details"]
    assert details["upvotes"] == 15 and details["comments"] == 1 and details["abstract"].startswith("Research taste")
    assert details["submittedBy"] == "zhongshsh" and details["organization"].startswith("Carnegie Mellon")


# --- both sources -------------------------------------------------------------------

@then("the paper both sources list has the same canonical URL and the same source id in both")
def step_same(context):
    from_feed, from_hf = feed_discoveries(context)["2611_03424"], hf_discoveries(context)["2611_03424"]
    assert from_feed["canonicalUrl"] == from_hf["canonicalUrl"] == f"https://arxiv.org/abs/{PAPER_BOTH}"
    assert from_feed["sourceId"] == from_hf["sourceId"]
    assert from_feed["monitorId"] != from_hf["monitorId"]


# --- the decision ---------------------------------------------------------------

@when("the router builds the decision request for a collected paper that has no enrichment summary")
def step_decide(context):
    context.request = mr.build_item(feed_discoveries(context)["2611_00015"])


@then("the request's summary is the paper's abstract")
def step_summary(context):
    assert context.request["values"]["summary"] == feed_discoveries(context)["2611_00015"]["details"]["abstract"]


@then("the request's text is the title, the address and the abstract")
def step_text(context):
    row = feed_discoveries(context)["2611_00015"]
    assert context.request["values"]["text"] == f"{row['title']}\n{row['canonicalUrl']}\n\n{row['details']['abstract']}"


@then("the request names the feed as its source")
def step_source(context):
    assert context.request["values"]["source"] == "feed"


@given("the paper monitors in the monitoring stack template")
def step_stack_template(context):
    text = (Path(__file__).resolve().parents[2] / "infra" / "monitoring" / "papyrus-monitoring.yaml").read_text()
    context.template_blocks = {match.group(1): match.group(0) for match in re.finditer(r"^  (\w+Schedule):\n(?:(?:    .*|)\n)*", text, re.M)}


@then("papers-arxiv-ai, papers-arxiv-security and papers-huggingface each have a schedule running the collector every 6 hours and a schedule running the router hourly, each naming its monitor")
def step_paper_schedules(context):
    for name, monitor_id in (("PapersArxivAi", "papers-arxiv-ai"), ("PapersArxivSecurity", "papers-arxiv-security"), ("PapersHuggingface", "papers-huggingface")):
        collect, route = context.template_blocks[f"{name}CollectSchedule"], context.template_blocks[f"{name}RouteSchedule"]
        assert "rate(6 hours)" in collect and "CollectorFunction.Arn" in collect and f'"monitorId":"{monitor_id}"' in collect
        assert re.search(r"cron\(\d+ \* \* \* \? \*\)", route) and "RouterFunction.Arn" in route and f'"monitorId":"{monitor_id}"' in route

