import contextlib
import io
import json
from unittest import mock

import yaml
from behave import given, then, when

from papyrus_content import story_writing as writing

GOOD = "ref-goodref"


def fake_pack(profile):
    return {"system": f"ROLE {profile}", "user": "THE STORY AND ITS RESEARCH", "contextHash": "abcdef1234567890", "warnings": []}


@given("a Story with research and two attached References, one of them rejected by an editor")
def step_story(context):
    context.answer = None
    context.calls = []
    context.saved = []
    context.links = []
    context.marked = []
    context.error = None
    links = [{"referenceLineageId": "goodref", "role": "consulted"}, {"referenceLineageId": "badref", "role": "consulted"}]
    rows = {"goodref": {"id": "goodref-v1", "curationStatus": "pending", "title": "A good source", "sourceUri": "https://example.org/good", "sourcePublishedAt": "2026-03-04T00:00:00Z"},
            "badref": {"id": "badref-v1", "curationStatus": "rejected", "title": "A bad source", "sourceUri": "https://example.org/bad"}}
    context.links_on_story = links

    def llm(system, user, schema):
        context.calls.append({"system": system, "user": user, "schema": schema})
        return context.answer

    def save(client, lineage, **kwargs):
        context.saved.append(kwargs)
        return {"id": "story-v3", "versionNumber": 3}

    context.llm = llm
    context.patches = [
        mock.patch.object(writing, "build_context_pack", side_effect=lambda client, profile, **_: fake_pack(profile)),
        mock.patch.object(writing, "story_references", side_effect=lambda client, lineage: context.links_on_story),
        mock.patch.object(writing, "current_reference", side_effect=lambda client, lineage: rows.get(lineage)),
        mock.patch.object(writing, "current_story_version", return_value={"stage": "reporting", "metadata": json.dumps({"frontMatterYaml": "title: Old\nkeep: this\n"})}),
        mock.patch.object(writing, "save_story_version", side_effect=save),
        mock.patch.object(writing, "mark_story_outline", side_effect=lambda client, record, actor: context.marked.append(record["id"])),
        mock.patch.object(writing, "link_reference_to_story", side_effect=lambda client, lineage, reference, **kwargs: context.links.append((reference, kwargs))),
    ]
    for patch in context.patches:
        patch.start()
    context.add_cleanup(lambda: [patch.stop() for patch in context.patches])


def draft_answer(body, gaps=()):
    return {"title": "New title", "deck": "New deck", "blurb": "New blurb", "body": body, "evidence_gaps": list(gaps)}


@given("the model answers with an outline, saying the research is thin in one place")
def step_outline_answer(context):
    context.answer = {"enough": True, "why": "The cases are documented.", "outline": "## The point\n\nThe claim.", "still_thin": ["Find the appeal's status"]}


@given("the model answers with a draft citing the accepted Reference")
def step_draft_answer(context):
    context.answer = draft_answer("A claim [@R1].")


@given("the model answers with a draft citing a key that does not exist")
def step_draft_unknown(context):
    context.answer = draft_answer("A claim [@made-up].")


@given("the model answers with a draft that cites nothing")
def step_draft_none(context):
    context.answer = draft_answer("A claim with no citation.")


@given("the model answers with a draft citing the accepted Reference and one evidence gap")
def step_draft_gap(context):
    context.answer = draft_answer("A claim [@R1].", ["No second source for the date"])


def run(context, write, apply=True):
    try:
        context.result = write(object(), "story", llm=context.llm, apply=apply)
    except ValueError as error:
        context.error = str(error)


@when("the outline is written")
def step_write_outline(context):
    run(context, writing.write_outline)


@when("the outline is written as a dry run")
def step_outline_dry(context):
    run(context, writing.write_outline, apply=False)


@when("the draft is written")
def step_write_draft(context):
    run(context, writing.write_draft)


@then("the model was given the editor's role and the Story's research")
def step_editor_given(context):
    call = context.calls[0]
    assert "ROLE editor" in call["system"] and "THE STORY AND ITS RESEARCH" in call["user"], call


@then('a new version is saved with the outline as its body and the thin place under "Still thin"')
def step_outline_saved(context):
    body = context.saved[0]["body_markus"]
    assert body.startswith("## The point") and "## Still thin\n\n- Find the appeal's status" in body, body


@then("that version is marked as the outline")
def step_marked(context):
    assert context.marked == ["story-v3"]


@then("the change reason says it is by AI and names the pack it came from")
def step_reason(context):
    saved = context.saved[0]
    assert saved["actor"] == "AI" and "by AI" in saved["change_reason"] and "abcdef123456" in saved["change_reason"], saved


@then("the Story's stage did not change")
def step_stage_same(context):
    assert not context.saved[0].get("stage")


@then("no version is saved")
def step_none_saved(context):
    assert not context.saved and not context.links and not context.marked


@then("the result still holds the outline")
def step_result_outline(context):
    assert "The claim." in context.result["body"]


@then("the model was given the copywriter's role and the citation key of the accepted Reference")
def step_copywriter_given(context):
    call = context.calls[0]
    assert "ROLE copywriter" in call["system"] and "R1: A good source" in call["user"] and "https://example.org/good" in call["user"], call


@then("the model was not given a citation key for the rejected Reference")
def step_rejected_not_given(context):
    assert "badref" not in context.calls[0]["user"] and "example.org/bad" not in context.calls[0]["user"]


@then("a new version is saved with the draft as its body and the bibliography at its end")
def step_draft_saved(context):
    body = context.saved[0]["body_markus"]
    assert body.startswith(f"A claim [@{GOOD}]") and body.endswith(writing.BIBLIOGRAPHY), body


@then("its front matter holds the title, deck, blurb and the citation of the accepted Reference")
def step_front(context):
    front = yaml.safe_load(context.saved[0]["front_matter_yaml"])
    assert (front["title"], front["deck"], front["blurb"], front["keep"]) == ("New title", "New deck", "New blurb", "this"), front
    assert front["citations"] == {GOOD: {"type": "webpage", "title": "A good source", "URL": "https://example.org/good", "issued": {"date-parts": [[2026, 3, 4]]}}}, front


@then("the cited Reference is marked as cited with its key")
def step_cited(context):
    assert context.links == [("goodref-v1", {"role": "cited", "actor": "AI", "citation_key": GOOD})], context.links


@then("the Story moves to copywriting")
def step_moved(context):
    assert context.saved[0]["stage"] == "copywriting" and context.result["moved"]


@then("the draft is refused naming the key")
def step_refused_key(context):
    assert context.error and "made-up" in context.error, context.error


@then("the draft is refused saying it cites nothing")
def step_refused_nothing(context):
    assert context.error and "cites nothing" in context.error, context.error


@then("the result lists the evidence gap")
def step_gap_listed(context):
    assert context.result["evidenceGaps"] == ["No second source for the date"]


@then("the change reason holds the evidence gap")
def step_gap_reason(context):
    assert "No second source for the date" in context.saved[0]["change_reason"]


@when("the citation keys are read twice")
def step_keys_twice(context):
    context.first = writing.citable_references(object(), "story")
    context.second = writing.citable_references(object(), "story")
    context.links_on_story = [{"referenceLineageId": "goodref", "role": "cited", "citationKey": "smith-2026"}]
    context.kept = writing.citable_references(object(), "story")


@then("they are the same both times")
def step_keys_same(context):
    assert list(context.first) == list(context.second) == [GOOD], context.first


@then("a key a link already has is kept")
def step_key_kept(context):
    assert list(context.kept) == ["smith-2026"]


@given("the outline step is not done")
def step_outline_missing(context):
    context.assessment = {"steps": [{"key": "outline", "title": "Write the outline", "state": "not_done"}, {"key": "research", "title": "Research", "state": "done"}]}


@when("the missing steps are checked for a draft")
def step_check_missing(context):
    stderr = io.StringIO()
    with mock.patch.object(writing, "story_facts", return_value={}), mock.patch.object(writing, "assess", return_value=context.assessment), contextlib.redirect_stderr(stderr):
        writing.warn_missing_steps(object(), "story", ("research", "outline"))
    context.warned = stderr.getvalue()


@then("a warning names the outline step")
def step_warned(context):
    assert "'outline'" in context.warned and "'research'" not in context.warned, context.warned


@then("nothing is refused")
def step_not_refused(context):
    assert context.error is None
