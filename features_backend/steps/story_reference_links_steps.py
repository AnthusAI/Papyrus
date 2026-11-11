"""An editor points a story to a Reference (features_backend/story-reference-links.feature): thin steps over the helpers of the unit tests."""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_commands  # noqa: E402
from papyrus_content.concept_tags import audit_story_links  # noqa: E402
from papyrus_content.reference_links import link_item_reference_see_also  # noqa: E402
from papyrus_content.story_signals_mcp import call_story_signal_tool  # noqa: E402
from test_story_cli_live_test_edges import run  # noqa: E402
from test_story_reference_links import link, rows, site  # noqa: E402


@given('a site with a story "A big story" and accepted, pending and rejected References')
def _site(context):
    context.site = site()


def _ask(context, command: str) -> None:
    words = shlex.split(command)
    assert words[:3] == ["papyrus", "stories", "link-story"], command
    context.before = json.dumps(context.site.tables.get("SemanticRelation", {}), sort_keys=True)
    context.out, context.err, context.failure = link(context.site, *words[3:])


@given('the editor has already pointed the story to "{reference}"')
def _pointed(context, reference):
    _ask(context, f"papyrus stories link-story --story big --reference {reference}")
    assert context.failure is None, context.failure


@given("a person rejected that link")
def _rejected(context):
    row = rows(context.site)[0]
    row.update({"relationState": "rejected", "subjectStateKey": "item#item-big#rejected", "objectStateKey": f"reference#{row['objectLineageId']}#rejected"})
    context.before = json.dumps(context.site.tables["SemanticRelation"], sort_keys=True)


@given('the Reference "{reference}" was later rejected and a hand-written "supersedes" edge points at it')
def _later(context, reference):
    context.site.tables["Reference"][reference]["curationStatus"] = "rejected"
    good = rows(context.site)[0]
    context.site.tables["SemanticRelation"]["hand"] = {**good, "id": "hand", "predicate": "supersedes"}


@when('a signed-in editor asks the CLI: "{command}"')
def _runs(context, command):
    _ask(context, command)


@when('an editor shows the story')
def _show(context):
    context.out, context.err, context.failure = run(story_commands.stories_show, context.site, "--story", "item-big", signed_in=True, label="Grace Editor")


@when('the writer is asked to link the story to "{reference}" again')
def _again(context, reference):
    context.result = link_item_reference_see_also(context.site, "item-big", reference, "human", actor="Grace Editor")


@when('an agent calls papyrus_link_stories with see_also_references "{reference}"')
def _agent(context, reference):
    context.done = call_story_signal_tool("papyrus_link_stories", {"story": "big", "see_also_references": [reference]}, context.site, actor="Grace Editor")


@when("the story links are checked")
def _check(context):
    context.findings = audit_story_links(context.site, ["item-big"])


@then('it printed a "write" line for "{title}" with host "{host}" and status "{status}"')
def _line(context, title, host, status):
    fields = context.out.splitlines()[0].split("\t")
    assert fields[5:] == [title, f"host {host}", f"status {status}", "write"], fields


@then('there are 2 see-also edges from the story to References, each recorded as added by "{who}"')
def _edges(context, who):
    found = [row for row in rows(context.site) if row["objectKind"] == "reference"]
    assert len(found) == 2 and all(row["predicate"] == "see_also" and json.loads(row["metadata"])["addedBy"] == who for row in found)


@then("the command stopped saying the Reference is pending and nothing was written")
def _pending(context):
    assert "pending" in str(context.failure) and rows(context.site) == [] and "write" not in context.out


@then("the command stopped saying the Reference was not found and nothing was written")
def _missing(context):
    assert "not found" in str(context.failure) and rows(context.site) == [] and "write" not in context.out


@then('it printed an "exists" line and wrote nothing')
def _exists(context):
    assert context.out.rstrip().endswith("\texists") and json.dumps(context.site.tables["SemanticRelation"], sort_keys=True) == context.before


@then('the outcome is "rejected" and the stored link is unchanged')
def _unchanged(context):
    assert context.result["outcome"] == "rejected" and json.dumps(context.site.tables["SemanticRelation"], sort_keys=True) == context.before


@then('the output lists the see-also Reference "{title}"')
def _listed(context, title):
    assert any(line.startswith("stories\tshow\tsee-also-reference") and title in line for line in context.out.splitlines()), context.out


@then("the agent's link is written as derived")
def _derived(context):
    assert context.done["referenceLinks"][0]["outcome"] == "write" and json.loads(rows(context.site)[0]["metadata"])["provenance"] == "derived"


@then('an agent call with "{one}" and "{other}" is refused and writes nothing more')
def _refused(context, one, other):
    try:
        call_story_signal_tool("papyrus_link_stories", {"story": "big", "see_also_references": [one, other]}, context.site, actor="Grace Editor")
    except ValueError as error:
        assert "pending" in str(error)
    else:
        raise AssertionError("expected a refusal")
    assert len(rows(context.site)) == 1


@then('it reports a "{first}" problem and a "{second}" problem and nothing else')
def _problems(context, first, second):
    assert sorted(finding["problem"] for finding in context.findings) == sorted([first, second]), context.findings
