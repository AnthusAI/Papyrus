"""`papyrus editorial languages` and the describeEditorialLanguages query (features_backend/translation/editorial-languages-setting.feature). In-memory store; no network."""

from __future__ import annotations

import contextlib
import io
import json
import shlex
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content import editorial_checks as editorial  # noqa: E402
from papyrus_content import editorial_commands  # noqa: E402


class SettingsStore:
    """The one EditorialCheckSettings row, held as the GraphQL store holds it (the settings are a JSON string)."""

    def __init__(self, settings: dict) -> None:
        self.row = {"id": "settings", "settings": json.dumps(settings)}
        self.writes = 0
        self.policies: list[dict] = []   # the site's editorial policies (enabling a language imports starter packs)

    def list_policies(self):
        return [dict(policy) for policy in self.policies]

    def create_policy(self, record):
        self.policies.append({"id": f"policy-{len(self.policies) + 1}", **record})

    def update_policy(self, record):
        self.policies = [record if policy["id"] == record["id"] else policy for policy in self.policies]

    def get_settings(self):
        return self.row

    def put_settings(self, values, *, exists):
        assert exists
        self.writes += 1
        self.row = {"id": "settings", "settings": json.dumps(values)}

    @property
    def stored(self) -> dict:
        return json.loads(self.row["settings"])


@given('a site whose stored settings write in "{tags}" with "{primary}" as the primary and the house guidance "{guidance}"')
def step_site(context, tags, primary, guidance):
    languages = {"primary": primary, "enabled": [tag.strip() for tag in tags.split(",")], "futureKey": {"kept": True}}
    context.store = SettingsStore({"guidance": guidance, "languages": languages})


@given('the stored prefix of "{tag}" is "{prefix}"')
def step_stored_prefix(context, tag, prefix):
    settings = context.store.stored
    settings["languages"]["prefixes"] = {tag: prefix}
    context.store.row = {"id": "settings", "settings": json.dumps(settings)}


@given('the stored public languages are "{tags}"')
def step_stored_public(context, tags):
    settings = context.store.stored
    settings["languages"]["public"] = [tag.strip() for tag in tags.split(",")]
    context.store.row = {"id": "settings", "settings": json.dumps(settings)}


@when('the editor runs the languages command "{command}"')
def step_run(context, command):
    words = shlex.split(command)
    assert words[:3] == ["papyrus", "editorial", "languages"], command
    out, err = io.StringIO(), io.StringIO()
    context.refusal = None
    counts = getattr(context, "translations", {})
    context.count_calls = []
    with (mock.patch.object(editorial_commands, "GraphQLEditorialStore", lambda: context.store),
          mock.patch.object(editorial_commands, "translation_counts", lambda tags: context.count_calls.append(list(tags)) or {tag: counts.get(tag, 0) for tag in tags}),
          contextlib.redirect_stdout(out), contextlib.redirect_stderr(err)):
        try:
            editorial_commands.editorial_languages(words[3:])
        except ValueError as error:
            context.refusal = str(error)
    context.stdout = out.getvalue()
    context.output = out.getvalue() + err.getvalue()


def _row(context, tag: str) -> str:
    return next(line for line in context.output.splitlines() if line.startswith(f"{tag}\t"))


@then('the listing says "{tag}" is not public, served under "{prefix}" with the slug policy "{policy}"')
def step_not_public(context, tag, prefix, policy):
    cells = _row(context, tag).split("\t")
    assert cells[1].startswith("not public") and cells[2] == prefix and cells[3] == policy, cells


@then('the listing says "{tag}" is served under "{prefix}" with the slug policy "{policy}"')
def step_served(context, tag, prefix, policy):
    cells = _row(context, tag).split("\t")
    assert cells[2] == prefix and cells[3] == policy, cells


@then('the listing says "{tag}" is public')
def step_public(context, tag):
    assert _row(context, tag).split("\t")[1] == "public", _row(context, tag)


@then("no setting is written")
def step_nothing(context):
    assert context.store.writes == 0


@then('the stored public languages are "{tags}"')
def step_stored_public_is(context, tags):
    assert context.store.stored["languages"]["public"] == [tag.strip() for tag in tags.split(",")], context.store.stored


@then('the stored house guidance is still "{guidance}"')
def step_guidance(context, guidance):
    assert context.store.stored["guidance"] == guidance


@then('the stored languages still hold the key "{key}" untouched')
def step_key(context, key):
    assert context.store.stored["languages"][key] == {"kept": True}


@then('the stored prefix of "{tag}" is "{prefix}" and its slug policy is "{policy}"')
def step_prefix_slug(context, tag, prefix, policy):
    languages = context.store.stored["languages"]
    assert languages["prefixes"] == {tag: prefix} and languages["slugs"] == {tag: policy}, languages


@then('"{tag}" has no stored prefix and no stored slug policy')
def step_none_stored(context, tag):
    languages = context.store.stored["languages"]
    assert tag not in languages.get("prefixes", {}) and tag not in languages.get("slugs", {}), languages


@then('"{tag}" has no stored prefix')
def step_no_prefix(context, tag):
    assert tag not in context.store.stored["languages"].get("prefixes", {}), context.store.stored


@then("the stored languages hold no public list")
def step_no_public(context):
    assert "public" not in context.store.stored["languages"], context.store.stored


@then('the languages command is refused saying "{message}"')
def step_refused(context, message):
    assert context.refusal and message in context.refusal, context.refusal


def _describe(context, languages):
    services = editorial.Services(store=context.store, decision_model=None)
    context.described = editorial.handle("describeEditorialLanguages", {"languages": json.dumps(languages)}, services)


@when('the console form describes the languages with "{first}" and "{second}" both enabled')
def step_describe_clash(context, first, second):
    _describe(context, {"primary": "en", "enabled": ["en", first, second]})


@when("the console form describes the stored languages")
def step_describe_stored(context):
    _describe(context, context.store.stored["languages"])


@then('the console form is told "{message}"')
def step_told(context, message):
    assert context.described["ok"] is False and message in context.described["message"], context.described


def _language(context, tag):
    return next(row for row in context.described["languages"] if row["tag"] == tag)


@then('the console form is told the default prefix of "{tag}" is "{prefix}" and its default slug policy is "{policy}"')
def step_defaults(context, tag, prefix, policy):
    row = _language(context, tag)
    assert row["defaultPrefix"] == prefix and row["defaultSlugPolicy"] == policy, row


@then('the console form is told the default slug policy of "{tag}" is "{policy}"')
def step_default_slug(context, tag, policy):
    assert _language(context, tag)["defaultSlugPolicy"] == policy


@then("the listing says translating on publish is off")
def step_auto_off(context):
    assert "translate on publish\toff" in context.output.splitlines(), context.output


@then('the listing says translating on publish is on with the automation "{automation}"')
def step_auto_on(context, automation):
    line = next(line for line in context.output.splitlines() if line.startswith("translate on publish\t"))
    assert line.split("\t")[1].startswith(f"on, automation {automation}"), line


@then("the command is refused saying to name the Automation that runs the translation procedure")
def step_refused_automation(context):
    assert context.refusal and "names the Automation that runs the translation procedure" in context.refusal, context.refusal


@then("the command is refused saying the site has no language to translate into")
def step_refused_no_language(context):
    assert context.refusal and "has none" in context.refusal and "other than the primary" in context.refusal, context.refusal


@given('the stored auto setting has the key "{key}"')
def step_stored_auto_key(context, key):
    settings = context.store.stored
    settings["languages"]["auto"] = {"enabled": False, key: True}
    context.store.row = {"id": "settings", "settings": json.dumps(settings)}


@then('the command is refused naming the key "{key}"')
def step_refused_key(context, key):
    assert context.refusal and key in context.refusal, context.refusal


def _auto(context):
    return context.store.stored["languages"]["auto"]


@then('the stored auto setting is on, with the automation "{automation}", publishing clean translations')
def step_stored_on_publishing(context, automation):
    assert _auto(context)["enabled"] is True and _auto(context)["automation"] == automation and _auto(context).get("publish", True) is True, _auto(context)


@then('the stored auto setting is on, with the automation "{automation}", saving translations for a person to publish')
def step_stored_on_saving(context, automation):
    assert _auto(context)["enabled"] is True and _auto(context)["automation"] == automation and _auto(context)["publish"] is False, _auto(context)


@then('the stored auto setting is off, with the automation "{automation}" kept')
def step_stored_off(context, automation):
    assert _auto(context)["enabled"] is False and _auto(context)["automation"] == automation and _auto(context)["publish"] is False, _auto(context)


def _segments(text: str) -> dict:
    found = {}
    for part in text.split(";"):
        tag, _, rest = part.strip().partition(":")
        found[tag.strip().strip('"')] = {segment.split(" is ")[0].strip(): segment.split(" is ")[1].strip().strip('"') for segment in rest.split(",")}
    return found


@then("the stored segments are {text}")
def step_stored_segments(context, text):
    assert context.store.stored["languages"]["segments"] == _segments(text), context.store.stored["languages"].get("segments")


@then('the listing shows the segment "{text}" for "{tag}"')
def step_segment_listing(context, text, tag):
    assert any(line == f"segment\t{tag}\t{text}" for line in context.output.splitlines()), context.output


# --- enabling and disabling a language (features_backend/translation/editorial-languages-enable.feature) ---


@given('the stored languages write in "{tags}" with "{primary}" as the primary')
def step_stored_languages(context, tags, primary):
    settings = context.store.stored
    settings["languages"] = {**settings["languages"], "primary": primary, "enabled": [tag.strip() for tag in tags.split(",")]}
    context.store.row = {"id": "settings", "settings": json.dumps(settings)}


@given('the stored languages write in "{tags}" with "{primary}" as the primary and "{tag}" has {count:d} translated Stor{plural}')
def step_stored_with_translations(context, tags, primary, tag, count, plural):
    step_stored_languages(context, tags, primary)
    context.translations = {tag: count}


@given('the editor has run the languages command "{command}"')
def step_has_run(context, command):
    step_run(context, command)
    assert context.refusal is None, context.refusal
    context.store.writes = 0


@then('the stored enabled languages are "{tags}"')
def step_enabled_are(context, tags):
    assert context.store.stored["languages"]["enabled"] == [tag.strip() for tag in tags.split(",")], context.store.stored


def _starter_packs(context) -> set[str]:
    return {policy["source"].removeprefix("starter:") for policy in context.store.policies if str(policy.get("source", "")).startswith("starter:")}


@then('the site has the starter packs "{names}"')
def step_has_packs(context, names):
    wanted = {name.strip() for name in names.split(",")}
    assert wanted <= _starter_packs(context), (wanted, _starter_packs(context))
    assert wanted <= set(context.store.stored["defaultStarterPacks"]), context.store.stored


@then("the site has no starter packs")
def step_no_packs(context):
    assert not context.store.policies and "defaultStarterPacks" not in context.store.stored, (context.store.policies, context.store.stored)


@then('the command output says "{text}"')
def step_output_says(context, text):
    assert text in context.output, context.output


@then('the JSON output lists "{tag}" as enabled and as not public')
def step_json_enabled(context, tag):
    document = json.loads(context.stdout)
    assert document["enabled"] == [tag] and tag in document["languages"]["enabled"], document
    row = next(row for row in document["serving"]["languages"] if row["tag"] == tag)
    assert row["public"] is False and document["written"] is True, document


@then('the JSON output lists the starter pack "{name}" as not applied before')
def step_json_pack(context, name):
    assert json.loads(context.stdout)["starterPacks"][name]["alreadyApplied"] is False, context.stdout


@then('the JSON output has next commands naming "{tag}"')
def step_json_next(context, tag):
    assert any(f"--language {tag}" in line for line in json.loads(context.stdout)["next"]), context.stdout


@then("no translation count was asked for")
def step_no_count(context):
    assert context.count_calls == [], context.count_calls
