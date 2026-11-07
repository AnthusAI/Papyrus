"""The four lenses (features_backend/audience-lenses.feature). Nothing here calls a model or the network."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import audience_lenses as lenses  # noqa: E402
from papyrus_content import story_commands  # noqa: E402
from papyrus_content.newsroom_context_pack import HEADINGS  # noqa: E402

LAYER = "audience_lenses"


def names(text):
    return [name.strip() for name in text.split(",")]


def all_checks():
    return [check for lens in lenses.LENSES for check in lens.checks]


def lens_text(context, role):
    pack = next(pack for pack, profile in zip(context.packs, ("reporter", "copywriter", "editor")) if profile == role)
    return layer_of(pack)


def layer_of(pack):
    heading = f"## {HEADINGS[LAYER]}\n\n"
    assert heading in pack["user"], pack["user"][:400]
    return pack["user"].split(heading, 1)[1].split("\n\n## ", 1)[0]


def single_lens_text(context):
    return layer_of(context.pack)


@then('the lenses are, in order, "{keys}"')
def lens_keys(context, keys):
    assert [lens.key for lens in lenses.LENSES] == names(keys)


@then('their steps are "{steps}"')
def lens_steps(context, steps):
    assert [lens.step for lens in lenses.LENSES] == names(steps)


@then("every check has a method of code, the decision model, the writing model or a person")
def check_methods(context):
    assert all(check.method in lenses.METHODS for check in all_checks())


@then("every check made by code, the decision model or the writing model has a severity of info, warn or error")
def check_severities(context):
    bad = [check.key for check in all_checks() if check.method != lenses.HUMAN and check.severity not in lenses.SEVERITIES]
    assert not bad, bad


@then("every check made by the decision model has a question")
def jev_questions(context):
    assert all(check.question for check in all_checks() if check.method == lenses.JEV)


@then('the checks whose default severity is error are "{keys}"')
def error_checks(context, keys):
    assert [check.key for check in all_checks() if check.severity == lenses.ERROR] == names(keys)


@then("the checks P10 and C6 report the same fact and mirror each other")
def mirrored(context):
    assert "C6" in lenses.CHECK_BY_KEY["P10"].mirrors and "P10" in lenses.CHECK_BY_KEY["C6"].mirrors


@then("the table in docs/four-lens-review.md is exactly the one generated from the definition")
def doc_matches(context):
    text = (REPO_ROOT / "docs" / "four-lens-review.md").read_text(encoding="utf-8")
    assert lenses.docs_with_table(text) == text, "run: python -m papyrus_content.audience_lenses"


@then("the table has a row for every check")
def doc_rows(context):
    text = (REPO_ROOT / "docs" / "four-lens-review.md").read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip() for line in text.splitlines() if re.match(r"\| [PASC]\d+ \|", line)}
    missing = [check.key for check in all_checks() if check.key not in rows]
    assert not missing, missing


@then("each pack has an audience lenses layer")
def each_has_layer(context):
    for pack in context.packs:
        assert LAYER in {row["name"] for row in pack["layers"]}


@then("no pack left the audience lenses layer out when it was short of room")
def never_shed(context):
    from papyrus_content.newsroom_context_pack import CORE_LAYERS

    assert LAYER in CORE_LAYERS


@then('the copywriter\'s lens text names "{phrase}"')
def copywriter_names(context, phrase):
    assert phrase in lens_text(context, "copywriter")


@then('the editor\'s lens text names "{phrase}"')
def editor_names(context, phrase):
    assert phrase in lens_text(context, "editor")


@then('the reporter\'s lens text names "{phrase}"')
def reporter_names(context, phrase):
    assert phrase in lens_text(context, "reporter")


@then('the reporter\'s lens text does not name "{phrase}"')
def reporter_not_names(context, phrase):
    assert phrase not in lens_text(context, "reporter")


@then("the lens text says an agent may complete a lens step")
def agent_may(context):
    assert "An agent may complete a lens step" in single_lens_text(context)


@then("the lens text says only a person gives the final approval")
def person_approves(context):
    assert "Only a person gives the final approval" in single_lens_text(context)


@then("the lens text names the three problems that must be fixed before a step can close")
def three_problems(context):
    text = single_lens_text(context)
    for phrase in ("no alt text", "third-party image with no credit", "Markdown copy that differs"):
        assert phrase in text, phrase


@then("the system text tells the copywriter never to stuff keywords or write a misleading teaser")
def system_trade_off(context):
    assert "Never stuff keywords" in context.pack["system"] and "promises more than the Story delivers" in context.pack["system"]


@then("the lens text says accuracy and natural writing beat every lens")
def accuracy_wins(context):
    assert "Accuracy and natural writing beat every lens" in single_lens_text(context)


@then("the lens text names all four lenses")
def all_four(context):
    text = single_lens_text(context)
    for lens in lenses.LENSES:
        assert lens.step in text or lens.title in text, lens.key


@then("the pack holds no audience lenses layer")
def no_layer(context):
    assert LAYER not in {row["name"] for row in context.pack["layers"]}


@given('the checklist records the step "{step}" as done')
def checklist_done(context, step):
    context.lens_states = {**getattr(context, "lens_states", {}), step: "done"}
    if not hasattr(context, "lens_patch"):
        context.lens_patch = patch.object(story_commands, "lens_step_states", lambda _client, _lineage: dict(context.lens_states))
        context.lens_patch.start()
        context.add_cleanup(context.lens_patch.stop)


def lens_lines(context):
    return [line.split("\t") for line in context.output.splitlines() if line.startswith("lens\t")]


@then("the procedure output has a lens line for each of the four steps")
def four_lens_lines(context):
    assert [line[1] for line in lens_lines(context)] == list(lenses.LENS_STEP_KEYS), context.output


@then("each lens line says it is not checked yet")
def not_checked(context):
    assert all(line[2] == "not checked yet" for line in lens_lines(context)), context.output


@then('the procedure output has no lens line for "{step}"')
def no_lens_line(context, step):
    assert step not in {line[1] for line in lens_lines(context)}, context.output


@then('the procedure output has a lens line for "{step}"')
def has_lens_line(context, step):
    assert step in {line[1] for line in lens_lines(context)}, context.output


@then("the JSON result lists the four lenses with their audiences")
def json_lenses(context):
    payload = json.loads(context.output)
    assert [row["step"] for row in payload["lenses"]] == list(lenses.LENS_STEP_KEYS)
    assert all(row["audience"] for row in payload["lenses"])
