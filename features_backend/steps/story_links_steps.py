"""An editor links a story to related stories (features_backend/story-links.feature).

Runs the real `papyrus stories link-story` and `stories show` commands against `SignedInSite`, a stand-in that refuses what AppSync refuses a
signed-in token. No network, login or AWS.
"""
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
from story_reference_role_site import SignedInSite  # noqa: E402
from test_story_cli_live_test_edges import run  # noqa: E402

LINEAGES = {"A big story": "item-big", "First post": "item-post-1", "Second post": "item-post-2"}
GROUPS = {"editor": ["editor"], "administrator": ["admin"], "viewer": ["viewer"]}


def _story(lineage: str, title: str, kind: str, stage: str, slug: str) -> dict:
    return {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "headline": title, "title": title,
            "stage": stage, "slug": slug, "type": kind, "section": "news"}


def _relations(context) -> list[dict]:
    return list(context.site.tables.get("SemanticRelation", {}).values())


@given('a site with a published article "A big story", a published post "First post" and a draft post "Second post"')
def _site(context):
    context.site = SignedInSite({
        "Item": [_story("item-big", "A big story", "article", "published", "big"), _story("item-post-1", "First post", "post", "published", "post-1"),
                 _story("item-post-2", "Second post", "post", "draft", "post-2")],
        "PublishedItem": [{"id": "published-item-big"}, {"id": "published-item-post-1"}],
    }, groups=["editor"], label="Ada Example")


def _link_command(context, command: str, who: str, name: str) -> None:
    words = shlex.split(command)
    assert words[:3] == ["papyrus", "stories", "link-story"], command
    context.site.groups = GROUPS[who]
    context.site.label = name
    context.out, context.err, context.failure = run(story_commands.stories_link_story, context.site, *words[3:], signed_in=True, label=name)


@given('the editor has already linked "{one}" and "{other}"')
def _linked(context, one, other):
    _link_command(context, f"papyrus stories link-story --story {LINEAGES[one]} --to {LINEAGES[other]}", "editor", "Ada Example")
    assert context.failure is None, context.failure


@given('the editor has already noted a link from "{one}" to "{other}" saying "{note}"')
def _linked_with_note(context, one, other, note):
    _link_command(context, f"papyrus stories link-story --story {LINEAGES[one]} --to {LINEAGES[other]} --note {shlex.quote(note)}", "editor", "Ada Example")
    assert context.failure is None, context.failure


@when('a signed-in {who} "{name}" asks the CLI: "{command}"')
def _runs(context, who, name, command):
    _link_command(context, command, who, name)


@when('an editor shows the story "{slug}"')
def _show(context, slug):
    lineage = {"big": "item-big", "post-1": "item-post-1", "post-2": "item-post-2"}[slug]
    context.out, context.err, context.failure = run(story_commands.stories_show, context.site, "--story", lineage, signed_in=True, label="Ada Example")
    assert context.failure is None, context.failure


@then("the link command succeeds")
def _succeeds(context):
    assert context.failure is None, f"{context.failure!r}\n{context.out}\n{context.err}"


@then('the link command fails with "{message}"')
def _fails(context, message):
    assert context.failure is not None and message in str(context.failure), f"{context.failure!r}\n{context.out}"


@then("the link command printed no write line")
def _no_write(context):
    assert "\twrite" not in context.out, context.out


@then('it printed a "{outcome}" line for "{title}" as a {kind} at stage {stage}')
def _line_typed(context, outcome, title, kind, stage):
    wanted = [title, f"type {kind}", f"stage {stage}", outcome]
    assert any(line.split("\t")[5:] == wanted for line in context.out.splitlines()), context.out


@then('it printed a "{outcome}" line for "{title}" and no "{other}" line')
def _line_only(context, outcome, title, other):
    lines = [line.split("\t") for line in context.out.splitlines()]
    assert any(line[5] == title and line[-1] == outcome for line in lines), context.out
    assert not any(line[-1] == other for line in lines), context.out


@then('it printed an "{outcome}" line for "{title}" and no "{other}" line')
def _line_only_an(context, outcome, title, other):
    _line_only(context, outcome, title, other)


@then('it warned that "{title}" is not published yet and the public See also block shows published stories only')
def _warned(context, title):
    assert f"{title} is not published yet" in context.err and "shows published stories only" in context.err, context.err


@then("there are {count:d} links, each recorded as added by \"{name}\"")
def _links_added_by(context, count, name):
    rows = _relations(context)
    assert len(rows) == count, rows
    assert all(json.loads(row["metadata"])["addedBy"] == name for row in rows), rows


@then("there is {count:d} link")
@then("there are {count:d} links")
def _links(context, count):
    assert len(_relations(context)) == count, _relations(context)


@then("there is still {count:d} link")
def _still(context, count):
    assert len(_relations(context)) == count, _relations(context)


@then('the related stories listed are "{title}" as {kind} at stage {stage} with the note "{note}"')
def _related(context, title, kind, stage, note):
    kind = kind.split(" ", 1)[-1]
    rows = [line.split("\t") for line in context.out.splitlines() if line.startswith("stories\tshow\trelated\t")]
    assert len(rows) == 1, context.out
    row = rows[0]
    assert (row[4], row[5], row[6], row[-1]) == (title, f"type {kind}", f"stage {stage}", note), row


@then("the written link is the one official relation {name}, with its seeded relation type")
def _official(context, name):
    rows = _relations(context)
    assert rows and all((r["predicate"], r["relationTypeKey"], r["relationTypeId"]) == (name, name, "semantic-relation-type-see-also") for r in rows), rows


@given('someone wrote a link from "{one}" to "{other}" by hand under the name "{name}"')
def _by_hand(context, one, other, name):
    context.site.tables.setdefault("SemanticRelation", {})["hand-written"] = {
        "id": "hand-written", "predicate": name, "subjectKind": "item", "objectKind": "item", "subjectLineageId": LINEAGES[one], "objectLineageId": LINEAGES[other],
        "subjectStateKey": f"item#{LINEAGES[one]}#current", "objectStateKey": f"item#{LINEAGES[other]}#current", "metadata": "{}"}


@when('an editor shows the story "{slug}" as JSON')
def _show_json(context, slug):
    lineage = {"big": "item-big", "post-1": "item-post-1", "post-2": "item-post-2"}[slug]
    context.out, context.err, context.failure = run(story_commands.stories_show, context.site, "--story", lineage, "--json", signed_in=True, label="Ada Example")
    assert context.failure is None, context.failure
    context.shown = json.loads(context.out)


@then('the JSON lists no related stories and flags the relation "{name}" as not official')
def _flagged(context, name):
    assert context.shown["related"] == [], context.shown
    assert [entry["predicate"] for entry in context.shown["unofficialRelations"]] == [name], context.shown


# ---- features_backend/link-rerender.feature: the page re-render is a recording stand-in ----

@given("the page re-render is a recording stand-in")
def _recording_rerender(context):
    from unittest import mock

    from papyrus_content import story_rerender

    context.rerender_asked, context.rerender_failing = [], set()

    def request(_client, lineage, **_kw):
        context.rerender_asked.append(lineage)
        if lineage in context.rerender_failing:
            return {"ok": False, "rendered": {"ok": False, "errors": ["render failed"]}}
        return {"ok": True, "rendered": {"ok": True}}

    patcher = mock.patch.object(story_rerender, "request_story_rerender", request)
    patcher.start()
    context.add_cleanup(patcher.stop)


@given('the re-render of "{lineage}" fails')
def _rerender_fails(context, lineage):
    context.rerender_failing.add(lineage)


@then('the stories re-rendered were "{lineages}"')
def _rerendered(context, lineages):
    assert context.rerender_asked == [part for part in lineages.split(", ") if part], context.rerender_asked
    context.rerender_asked.clear()


@then("no story was re-rendered")
def _none_rerendered(context):
    assert context.rerender_asked == [], context.rerender_asked
    context.rerender_asked.clear()


@then('it printed "rerender" lines saying "no purge" and the closing line "{closing}"')
def _rerender_lines(context, closing):
    lines = context.out.splitlines()
    assert any(line.startswith("rerender\t") and "\tno purge\t" in line for line in lines), context.out
    assert lines[-1] == closing, lines[-1]


@then('the warning names the manual command "{command}"')
def _manual_command(context, command):
    assert command in context.err, context.err
