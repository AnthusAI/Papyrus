import json
from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_web as tw  # noqa: E402
from papyrus_content import monitoring_web_queries as wq  # noqa: E402
from papyrus_content.monitoring_web import searchable  # noqa: E402


def draft(context, **kwargs):
    context.proposal, context.asker, context.backend = tw.propose(context.table_, context.asker, **kwargs)
    return context.proposal


def execute(context, approved_by=None):
    draft(context)
    wq.execute(context.table_, context.proposal, approved_by=approved_by, now_iso="2026-11-02T00:00:00Z")


@given("a publication with two enabled sections and one disabled section")
def step_sections(context):
    context.table_, context.asker, context.sections = tw.web_table("old topic"), tw.Asker(), tw.SECTIONS


@when("the queries are drafted")
def step_drafted(context):
    if getattr(context, "tenants", None) is not None:      # the p-apyr-us monitor: keep what the factory was asked for
        backend = tw.FakeBackend(tw.SECTIONS, context.tenants)
        context.proposal = wq.propose("p-apyr-us", tw.PUBLICATIONS, context.table_, context.asker, client_factory=backend.factory,
                                      resolve=lambda client, **kw: tw.PACK)
        return
    draft(context, sections=getattr(context, "sections", tw.SECTIONS))


@then("there is one drafted query for each enabled section and one for the site, three in all")
def step_three(context):
    assert [(q["scope"], q.get("sectionId")) for q in context.proposal["queries"]] == [
        ("section", "agent-security"), ("section", "evaluation"), ("site", None)]


@then("each section's query was drafted from that section's mission, policy, guidance and kill criteria")
def step_from_text(context):
    first = context.asker.prompts[0]
    assert all(text in first for text in ("Show how agents get attacked.", "Primary sources.", "Prefer incident write-ups.", "Vendor hype."))


@then("the disabled section has no query")
def step_disabled(context):
    assert "old" not in [q.get("sectionId") for q in context.proposal["queries"]]
    assert "Retired topic" not in " ".join(context.asker.prompts)


@given("a model that answers a section once with prose and then with a single query")
def step_model(context):
    context.table_ = tw.web_table("old topic")
    context.asker = tw.Asker(["not json", json.dumps({"query": "kept", "rationale": "r"})])


@then("the drafter asked again and kept the single query")
def step_asked_again(context):
    assert context.proposal["queries"][0]["text"] == "kept" and len(context.asker.prompts) == 4


@then("an answer with two queries, or none, is refused")
def step_refused(context):
    for bad in (json.dumps([{"query": "a"}, {"query": "b"}]), json.dumps([]), json.dumps({"query": ""})):
        try:
            wq.parse_query(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


@given("a publication with a section that has a policy but no mission and a section with only a title")
def step_no_mission(context):
    context.table_, context.asker = tw.web_table(), tw.Asker()
    context.sections = [{"id": "a", "title": "A", "enabled": True, "sortOrder": 1, "editorialMission": "", "editorialPolicy": "Policy only."},
                        {"id": "b", "title": "B", "enabled": True, "sortOrder": 2, "editorialMission": "", "editorialPolicy": ""}]


@then("both sections still get a query, because the count stays sections plus one")
def step_count(context):
    assert len(context.proposal["queries"]) == 3


@then("each of the two queries is flagged so an editor can check it")
def step_flags(context):
    assert [q["flags"] for q in context.proposal["queries"]] == [["no-section-mission"], ["title-only"], []]


@given("the p-apyr-us web monitor, which finds for the Machines on Machines backend")
def step_mom(context):
    context.table_, context.asker, context.tenants = tw.web_table(monitor="web-p-apyr-us"), tw.Asker(), []


@then("its sections are read for the machines-on-machines tenant and its doctrine from that backend")
def step_tenant(context):
    assert context.tenants == [None, "machines-on-machines"]


@given("a web monitor with two old topic queries, one of them with a high-water mark")
def step_old_two(context):
    context.table_, context.asker = tw.web_table("old topic one", "old topic two"), tw.Asker()
    tw.set_high_water(context.table_, "old topic one", tw.NOW)


@given("a web monitor with two old topic queries")
def step_old_two_plain(context):
    context.table_, context.asker = tw.web_table("old topic one", "old topic two"), tw.Asker()


@when("the new queries are executed without an approver")
def step_exec_unapproved(context):
    execute(context)


@when("the new queries are executed with an approver")
def step_exec_approved(context):
    execute(context, approved_by="Ryan")


@then("both old queries are retired, with a history entry, and keep their high-water mark and their approver")
def step_retired(context):
    stored = tw.queries_of(context.table_)
    old = stored["old topic one"]
    assert stored["old topic two"]["status"] == old["status"] == "retired"
    assert old["highWater"] == tw.NOW and old["approvedBy"] == tw.APPROVER
    assert [h["change"] for h in old["history"]] == ["created", "retired"]


@then("the new queries record their origin, who drafted them, and their section or the site")
def step_new_fields(context):
    stored = tw.queries_of(context.table_)
    section, site = stored["Agent Security news"], stored["site news"]
    assert (section["origin"], section["createdBy"], section["scope"], section["sectionId"]) == ("drafted", "gpt-6-luna", "section", "agent-security")
    assert site["scope"] == "site" and "sectionId" not in site and section["rationale"]


@then("none of the new queries is searched yet")
def step_none_searched(context):
    assert [r for r in tw.rows(context.table_, "QUERY#") if searchable(r)] == []


@then("exactly the section queries and the site query are searched")
def step_searched(context):
    assert sorted(r["text"] for r in tw.rows(context.table_, "QUERY#") if searchable(r)) == ["Agent Security news", "Evaluation news", "site news"]


@then("the old queries are not searched")
def step_old_not_searched(context):
    assert all(not searchable(r) for r in tw.rows(context.table_, "QUERY#") if r["text"].startswith("old topic"))


@given("a web monitor with an old topic query and an editor-written query")
def step_old_and_editor(context):
    context.table_, context.asker = tw.web_table("old topic"), tw.Asker()
    tw.add_queries(context.table_, tw.MONITOR, "my own query")
    context.table_.put_item({**tw.queries_of(context.table_)["my own query"], "origin": "editor", "createdBy": "Ryan"})
    context.before = {k: dict(v) for k, v in context.table_.items.items()}


@when("the plan is made without executing")
def step_plan(context):
    draft(context)
    context.lines = wq.describe(context.proposal, executing=False, approved=True)


@then("it lists the old query to retire and the new queries to add")
def step_lists(context):
    assert [r["text"] for r in context.proposal["retire"]] == ["old topic"] and len(context.proposal["queries"]) == 3
    assert any(line.startswith("  retire") for line in context.lines) and sum(line.startswith("  add") for line in context.lines) == 3


@then("the editor-written query is kept")
def step_editor_kept(context):
    assert [r["text"] for r in context.proposal["keep"]] == ["my own query"]


@then("it reports the paid searches a day that the monitor will make")
def step_report(context):
    assert "4 active queries, about 4 paid searches a day" in context.lines[-1]


@then("the table is unchanged")
def step_unchanged(context):
    assert context.table_.items == context.before


@given("a web monitor whose per-section queries have been executed and approved")
def step_done(context):
    context.table_, context.asker = tw.web_table("old topic"), tw.Asker()
    execute(context, approved_by="Ryan")
    context.asker = tw.Asker()


@when("the plan is made again")
def step_again(context):
    draft(context)


@then("nothing is retired or added and the model is not asked")
def step_nothing(context):
    assert context.proposal["queries"] == [] and context.proposal["retire"] == [] and context.asker.prompts == []


@when("a section is renamed and another section is added")
def step_rename(context):
    context.sections = [{**tw.SECTIONS[0], "title": "Agent Safety"}, tw.SECTIONS[1],
                        {"id": "labor", "title": "Labor", "enabled": True, "sortOrder": 4, "editorialMission": "Work.", "editorialPolicy": "x"}]
    draft(context, sections=context.sections)


@then("only the new section gets a query, and the renamed section keeps its own")
def step_only_new(context):
    assert [q["sectionId"] for q in context.proposal["queries"]] == ["labor"] and context.proposal["retire"] == []
    assert len(context.asker.prompts) == 1


@when("one section is disabled and the plan is made")
def step_disable(context):
    draft(context, sections=tw.SECTIONS[:1])


@then("that section's drafted query is retired")
def step_orphan(context):
    assert [r["text"] for r in context.proposal["retire"]] == ["Evaluation news"]


@given("a web monitor with an editor-written query")
def step_editor_only(context):
    context.table_, context.asker = tw.web_table(), tw.Asker()
    context.table_.put_item({**tw.queries_of(context.table_)["ai agents"], "origin": "editor", "createdBy": "Ryan"})


@when("the plan is made with and without the request to retire editor queries")
def step_editor_plans(context):
    context.default, context.asked = draft(context), draft(context, retire_editor=True)


@then("the editor-written query is kept unless it is asked for")
def step_editor_default(context):
    assert context.default["retire"] == [] and [r["text"] for r in context.asked["retire"]] == ["ai agents"]


@given("a web monitor with an active approved query, a paused query and a retired query")
def step_statuses(context):
    context.table_, context.tavily = tw.web_table("active query", "paused query", "retired query"), tw.FakeTavily()
    for text, status in (("paused query", "paused"), ("retired query", "retired")):
        context.table_.put_item({**tw.queries_of(context.table_)[text], "status": status})


@then("Tavily was asked only the active approved query")
def step_only_active(context):
    assert {c["query"] for c in context.tavily.calls} == {"active query"}


@given("a web monitor whose new section query has never been searched")
def step_never(context):
    context.table_, context.asker = tw.web_table("old topic"), tw.Asker()
    execute(context, approved_by="Ryan")
    context.tavily = tw.FakeTavily()


@given("Tavily holds forty matching articles over the last five days")
def step_forty(context):
    context.tavily.articles = [tw.article(n, tw.day(-(n % 5)), query="Agent Security news") for n in range(40)]


@then("Tavily was asked that query once, with no date range and its usual page size")
def step_once(context):
    asked = [c for c in context.tavily.calls if c["query"] == "Agent Security news"]
    assert len(asked) == 1 and "start_date" not in asked[0] and asked[0]["max_results"] == tw.TAVILY_PAGE_LIMIT


@then("the query's high-water mark is set to the start of that pass")
def step_mark(context):
    assert tw.queries_of(context.table_)["Agent Security news"]["highWater"] == tw.NOW
