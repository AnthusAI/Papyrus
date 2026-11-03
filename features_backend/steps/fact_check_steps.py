import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
from test_multi_search_research import FakeLlm, FakeProvider, hit  # noqa: E402
from papyrus_content import fact_check, newsroom_context_pack  # noqa: E402
from papyrus_content import multi_search_research as ms  # noqa: E402
from papyrus_content.assignments_workflow import cited_source_urls, normalize_proposal_url, normalize_research_packet_bundle, research_packet_body  # noqa: E402


def quoted(text):
    return re.findall(r'"([^"]+)"', text)


def state(context):
    if not hasattr(context, "fc_sources"):
        context.fc_sources, context.fc_claims, context.fc_judge, context.fc_script = {}, [], None, {}
    return context


# --- the check on its own ---------------------------------------------------------------------------------------------------------

@given('the source "{source_id}" says "{text}"')
def step_source(context, source_id, text):
    state(context).fc_sources[source_id] = text


@given('a claim "{claim}" citing {ids}')
def step_claim(context, claim, ids):
    state(context).fc_claims.append({"claim": claim, "sources": quoted(ids)})


@given("a claim '{claim}' citing {ids}")
def step_claim_single_quoted(context, claim, ids):
    state(context).fc_claims.append({"claim": claim, "sources": quoted(ids)})


def scripted_judge(context):
    script = context.fc_script

    def judge(claim, cited):
        if claim in script.get("fails_on", ()):
            raise RuntimeError("model unavailable")
        return {"verdict": script["verdict"], "quote": script["quote"], "explanation": "Because the source says so.",
                "attribution_lost": script.get("attribution_lost", False)}

    context.fc_judge = judge


@given('the judge says "{verdict}" quoting "{quote}"')
def step_judge(context, verdict, quote):
    state(context).fc_script = {"verdict": verdict, "quote": quote}
    scripted_judge(context)


@given('the judge says "{verdict}" with no quote')
def step_judge_no_quote(context, verdict):
    state(context).fc_script = {"verdict": verdict, "quote": ""}
    scripted_judge(context)


@given('the judge says "{verdict}" quoting "{quote}" and reports the attribution lost')
def step_judge_attribution(context, verdict, quote):
    state(context).fc_script = {"verdict": verdict, "quote": quote, "attribution_lost": True}
    scripted_judge(context)


@given('the judge supports every claim quoting "{quote}"')
def step_judge_every(context, quote):
    state(context).fc_script = {"verdict": "supported", "quote": quote}
    scripted_judge(context)


@given('the judge fails on the claim "{claim}" and supports the others quoting "{quote}"')
def step_judge_fails_on(context, claim, quote):
    state(context).fc_script = {"verdict": "supported", "quote": quote, "fails_on": [claim]}
    scripted_judge(context)


@when("the claims are fact checked")
def step_check(context):
    context.fc_report = fact_check.check_claims(context.fc_claims, context.fc_sources, judge=context.fc_judge, urls={k: k for k in context.fc_sources})


@when("the claims are fact checked without a judge")
def step_check_without_judge(context):
    context.fc_report = fact_check.check_claims(state(context).fc_claims, context.fc_sources, judge=None, urls={k: k for k in context.fc_sources})


def result(context, number):
    return context.fc_report["claims"][number - 1]


def unmatched_terms(row):
    return [entry["term"] for entry in row["literal"]["unmatched"]]


def assert_unverified_for_terms(row, verdict, terms):
    assert row["verdict"] == verdict, row
    assert unmatched_terms(row) == [t.strip() for t in terms.split(";")], row["literal"]
    assert any(reason.startswith("unmatched_terms") for reason in row["reasons"]), row["reasons"]


@then('the claim is "{verdict}" because of unmatched terms "{terms}"')
def step_unmatched(context, verdict, terms):
    assert_unverified_for_terms(result(context, 1), verdict, terms)


@then('claim {number:d} is "{verdict}" because of unmatched terms "{terms}"')
def step_unmatched_numbered(context, number, verdict, terms):
    assert_unverified_for_terms(result(context, number), verdict, terms)


@then('the claim is "{verdict}" because of "{reason}"')
def step_reason(context, verdict, reason):
    row = result(context, 1)
    assert row["verdict"] == verdict and reason in row["reasons"], row


@then("the claim has no unmatched terms")
def step_no_unmatched(context):
    assert unmatched_terms(result(context, 1)) == [], result(context, 1)["literal"]


@then("claim {number:d} has no unmatched terms")
def step_no_unmatched_numbered(context, number):
    assert unmatched_terms(result(context, number)) == [], result(context, number)["literal"]


@then('the claim comes out "{verdict}"')
def step_comes_out(context, verdict):
    assert result(context, 1)["verdict"] == verdict, result(context, 1)


@then('claim {number:d} comes out "{verdict}"')
def step_comes_out_numbered(context, number, verdict):
    assert result(context, number)["verdict"] == verdict, result(context, number)


@then('all claims come out "{verdict}"')
def step_all_come_out(context, verdict):
    assert [row["verdict"] for row in context.fc_report["claims"]] == [verdict] * len(context.fc_claims)


@then('the judge verdict recorded for the claim is "{verdict}"')
def step_judge_recorded(context, verdict):
    assert result(context, 1)["judge"]["verdict"] == verdict and result(context, 1)["judge"]["quoteVerified"] is False


@then("the counts are {verified:d} verified, {unverified:d} unverified, {unchecked:d} unchecked")
def step_counts(context, verified, unverified, unchecked):
    counts = context.fc_report["counts"]
    assert (counts["verified"], counts["unverified"], counts["unchecked"]) == (verified, unverified, unchecked), counts


@then('claim {number:d} has a domain count of {domains:d} and single source is "{flag}"')
def step_strength(context, number, domains, flag):
    strength = result(context, number)["sourceStrength"]
    assert strength == {"domains": domains, "singleSource": flag == "yes"}, strength


@then('the source carrying the most claims is "{source_id}"')
def step_load(context, source_id):
    assert context.fc_report["sourceLoad"][0]["source"] == source_id, context.fc_report["sourceLoad"]


# --- a research run ---------------------------------------------------------------------------------------------------------------

def page_url(number):
    return f"https://page{number}.example.org/article"


@given("a research run whose pages say {pages}")
def step_pages(context, pages):
    context.run = SimpleNamespace(pages=quoted(pages), claims=[], disagreements=[], summary="The pages were read.", rewrite=None, judge_fails=False)


@given("the writer produced the claims {claims}")
def step_writer_claims(context, claims):
    context.run.claims = [{"claim": text, "sources": [number]} for number, text in enumerate(quoted(claims), start=1)]


@given("the writer produced the disagreement \"{topic}\" with the positions {positions}")
def step_writer_disagreement(context, topic, positions):
    rows = re.findall(r'"([^"]+)" from page (\d+)', positions)
    context.run.disagreements = [{"topic": topic, "positions": [{"position": text, "sources": [int(number)]} for text, number in rows]}]


@given('the writer\'s summary says "{text}"')
def step_writer_summary(context, text):
    context.run.summary = text


@given('the writer rewrites the summary as "{text}"')
def step_writer_rewrite(context, text):
    context.run.rewrite = text


@given("the judge fails on every call")
def step_judge_fails(context):
    context.run.judge_fails = True


class RunLlm(FakeLlm):
    def __call__(self, system, user, schema):
        if schema["name"] == "verified_summary" and self.rewrite is not None:
            self.calls.append((schema["name"], user))
            return {"summary": self.rewrite, "recommended_angle": ""}
        return super().__call__(system, user, schema)


@when("the research run is made")
def step_run(context):
    run = context.run
    synthesis = {"summary": run.summary, "recommended_angle": "", "claims": run.claims, "disagreements": run.disagreements, "open_questions": []}
    llm = RunLlm(synthesis=synthesis, fail="fact_check_judgement" if run.judge_fails else None)
    llm.rewrite = run.rewrite if run.rewrite is not None else run.pages[0]
    hits = [hit(page_url(number), f"Page {number}", text) for number, text in enumerate(run.pages, start=1)]
    provider = FakeProvider("gemini", {query["query"]: hits for query in llm.plan["queries"]})
    context.llm = llm
    context.packet = ms.run_multi_search("brief", llm=llm, providers={"gemini": provider})["packet"]


@then('the packet claims are exactly "{claim}"')
def step_packet_claims(context, claim):
    assert [row["claim"] for row in context.packet["claims"]] == [claim], context.packet["claims"]


@then("the packet has no claims")
def step_packet_no_claims(context):
    assert not context.packet["claims"], context.packet["claims"]


@then('the packet holds the unverified claim "{claim}" with the reason "{reason}"')
def step_packet_unverified(context, claim, reason):
    rows = [row for row in context.packet["unverifiedClaims"] if row["claim"] == claim]
    assert rows and any(entry.startswith(reason) for entry in rows[0]["reasons"]), context.packet.get("unverifiedClaims")
    assert rows[0]["sources"], rows[0]


@then('the packet summary does not contain "{text}"')
def step_summary_without(context, text):
    assert text not in context.packet["summary"] and text not in context.packet["recommended_angle"], context.packet["summary"]


@then('the summary model was shown "{shown}" and not "{hidden}"')
def step_summary_input(context, shown, hidden):
    user = next(user for name, user in context.llm.calls if name == "verified_summary")
    assert shown in user and hidden not in user, user


@then('the packet summary is "{text}"')
def step_summary_is(context, text):
    assert context.packet["summary"] == text, context.packet["summary"]


@then("the packet carries its fact check counts of {verified:d} verified and {unverified:d} unverified")
def step_packet_counts(context, verified, unverified):
    counts = context.packet["factCheck"]["counts"]
    assert (counts["verified"], counts["unverified"]) == (verified, unverified), counts


@then("the packet carries its fact check counts of {verified:d} verified and {unverified:d} unverified and {unchecked:d} unchecked")
def step_packet_counts_unchecked(context, verified, unverified, unchecked):
    counts = context.packet["factCheck"]["counts"]
    assert (counts["verified"], counts["unverified"], counts["unchecked"]) == (verified, unverified, unchecked), counts


def body_of(context):
    bundle = normalize_research_packet_bundle(context.packet, assignment={"corpusId": "c"}, assignment_meta={}, research_mode="source_discovery")
    return research_packet_body(bundle)


@then('the research packet body lists "{heading}" after the claims')
def step_body(context, heading):
    body = body_of(context)
    assert body.index("Claims:") < body.index(heading), body


@then('the position "{text}" is not labelled')
def step_position_plain(context, text):
    positions = [p for d in context.packet["disagreements"] for p in d["positions"] if p["position"] == text]
    assert positions and "unverified" not in positions[0], positions


@then('the position "{text}" is labelled unverified because of "{reason}"')
def step_position_labelled(context, text, reason):
    positions = [p for d in context.packet["disagreements"] for p in d["positions"] if p["position"] == text]
    assert positions and positions[0]["unverified"] is True and reason in positions[0]["reasons"], positions


@then('the research packet body marks the position "{text}" as could not verify')
def step_body_position(context, text):
    line = next(line for line in body_of(context).splitlines() if text in line)
    assert "could not verify" in line, line


@then("the cited-only intake would consider only page 1")
def step_intake(context):
    assert cited_source_urls(context.packet) == {normalize_proposal_url(page_url(1))}, cited_source_urls(context.packet)


# --- a later reporter -------------------------------------------------------------------------------------------------------------

@given('a Story whose earlier research packet has the verified claim "{claim}" and the unverified claim "{unverified}"')
def step_story_packet(context, claim, unverified):
    packet = {"summary": "Checked.", "claims": [{"claim": claim, "sources": [1]}], "unverifiedClaims": [{"claim": unverified, "sources": [2], "reasons": ["unmatched_terms: Ohio"]}]}
    context.pack_entry = {"message": {"id": "message-1", "createdAt": "2026-11-01T00:00:00Z"}, "packet": packet}


@when("the earlier research layer of the context pack is built")
def step_pack(context):
    store = mock.Mock()
    store.list_by_index.return_value = [{"id": "assignment-1", "instructions": "Look at it"}]
    situation = SimpleNamespace(store=store, lineage="story-1")
    with mock.patch("papyrus_content.assignments_workflow.load_assignment_research_packet_entries", return_value=[context.pack_entry]), \
         mock.patch.object(newsroom_context_pack, "_assignment_metadata", return_value={}):
        entries, _ = newsroom_context_pack.prior_research_layer(situation)
    context.pack_text = entries[0]["text"]


@then('it lists "{claim}" under "{heading}"')
def step_pack_lists(context, claim, heading):
    text = context.pack_text
    assert heading in text and text.index(heading) < text.index(claim), text
    following = [h for h in ("Claims:", "Unverified, do not rely on:", "Open questions:") if h in text and text.index(h) > text.index(heading)]
    assert not following or text.index(claim) < min(text.index(h) for h in following), text
