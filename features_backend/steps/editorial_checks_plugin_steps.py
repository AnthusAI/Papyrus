from __future__ import annotations

import json
import random

from behave import given, then, when

from limatus.contracts import validate_payload
from papyrus_content import editorial_checks as editorial


class FakeEditorialStore:
    """The plugin's three models, held in memory with the GraphQL store's contract (JSON fields as strings)."""

    def __init__(self) -> None:
        self.policies: dict[str, dict] = {}
        self.settings: dict | None = None
        self.feedback: list[dict] = []
        self.writes = 0

    def list_policies(self):
        return [dict(record) for record in self.policies.values()]

    def get_editorial_context(self, section):
        from papyrus_content.editorial_context import build_context
        return build_context({'key': 'synthetic'}, {'sectionId': section},
                             [{'scope': 'publication', 'kind': 'policy', 'text': 'Synthetic private guidance',
                               'source': {'id': 'synthetic-policy'}}], mode='cloud')

    def get_settings(self):
        return self.settings

    def list_feedback(self):
        return list(self.feedback)

    def create_policy(self, record):
        self.writes += 1
        self.policies[record["id"]] = json.loads(json.dumps(editorial.policy_input(record)))

    def update_policy(self, record):
        self.writes += 1
        self.policies[record["id"]] = json.loads(json.dumps(editorial.policy_input(record)))


class FakeGenerator:
    def __init__(self) -> None:
        self.reply: dict = {"options": []}

    def generate(self, **_kwargs):
        return self.reply


def _phrase_policy(key: str, scope: str, severity: str, enabled: bool, phrase: str) -> dict:
    policy = {
        "id": key,
        "version": 1,
        "title": key,
        "guidance": f"Avoid {phrase}.",
        "severity": severity,
        "enabled": enabled,
        "detectors": [{"id": f"{key}-phrase", "lane": "rules", "kind": "phrase", "phrases": [phrase]}],
    }
    return editorial.record_from_policy(policy, scope=scope, source="test")


def _services(context):
    return editorial.Services(store=context.store, decision_model=None, generator=context.generator)


@given("a site with the editorial checks plugin and these policies:")
def step_site_policies(context):
    context.store = FakeEditorialStore()
    context.generator = FakeGenerator()
    for row in context.table:
        context.store.create_policy(
            _phrase_policy(row["key"], row["scope"], row["severity"], row["enabled"] == "yes", row["phrase"])
        )
    context.store.writes = 0


@given('the "{section}" section also has a "{key}" policy for "{phrase}"')
def step_section_override(context, section, key, phrase):
    context.store.create_policy(_phrase_policy(key, section, "warn", True, phrase))


@given("the editorial check settings turn the classifier on with a {seconds:d} second deadline")
def step_settings(context, seconds):
    context.store.settings = {"id": "settings", "settings": json.dumps({"lanes": {"rules": True, "classifier": True}, "deadlineSeconds": seconds})}


@given('editors have recorded {count:d} decisions with text on policy "{key}"')
def step_feedback_with_text(context, count, key):
    for index in range(count):
        context.store.feedback.append(
            {"policyId": key, "detectorId": "judge", "lane": "classifier", "probability": 0.9, "decision": "dismissed" if index % 2 else "accepted", "text": f"Sentence number {index}."}
        )


@when('an editor checks "{body}" in section "{section}"')
def step_check(context, body, section):
    context.services = _services(context)
    context.body = body
    context.check_result = editorial.handle("checkEditorial", {"body": body, "format": "markus", "section": section}, context.services)


@then('the check result is a valid Limatus "{schema}" document')
def step_valid(context, schema):
    validate_payload(schema, context.check_result)


@then('the findings are for policies "{keys}"')
def step_findings(context, keys):
    actual = sorted({f["policyId"] for f in context.check_result["findings"]})
    assert actual == sorted(k.strip() for k in keys.split(",")), actual


@then('the "{key}" finding\'s excerpt is "{excerpt}"')
def step_excerpt(context, key, excerpt):
    assert [f["excerpt"] for f in context.check_result["findings"] if f["policyId"] == key] == [excerpt]


@then("Limatus was asked to run the classifier with a {seconds:d} second deadline")
def step_deadline(context, seconds):
    options = context.services.last_check_request["options"]
    assert options["lanes"]["classifier"] is True
    assert options["classifier"]["deadlineSeconds"] == seconds


@then("the classifier lane status is reported")
def step_lane_status(context):
    assert context.check_result["lanes"]["classifier"]["status"] in {"ran", "unavailable", "partial"}


@then("Limatus received {count:d} past decisions as examples")
def step_examples(context, count):
    assert len(context.services.last_check_request["options"]["classifier"]["examples"]) == count


@given('the rewrite model will propose "{replacement}"')
def step_propose(context, replacement):
    context.generator.reply = {"options": [{"replacement": replacement, "rationale": "Clearer.", "factVerificationRequired": False, "unresolvedQuestions": []}]}


@when('the editor asks for rewrites of the "{key}" finding')
def step_suggest_finding(context, key):
    finding = next(f for f in context.check_result["findings"] if f["policyId"] == key)
    context.suggest_result = editorial.handle(
        "suggestEditorialRewrite",
        {"body": context.body, "format": "markus", "section": "engineering", "finding": json.dumps(finding)},
        _services(context),
    )


@when('the editor selects "{selected}" in "{body}" and asks for rewrites with the note "{note}"')
def step_suggest_selection(context, selected, body, note):
    start = body.index(selected)
    context.suggest_result = editorial.handle(
        "suggestEditorialRewrite",
        {"body": body, "format": "markus", "section": "engineering", "selection": json.dumps({"start": start, "end": start + len(selected)}), "note": note},
        _services(context),
    )


@then('there is 1 rewrite option "{replacement}"')
def step_one_option(context, replacement):
    assert [o["replacement"] for o in context.suggest_result["options"]] == [replacement], context.suggest_result


@when('an admin imports the starter pack "{name}"')
def step_import(context, name):
    context.import_result = editorial.handle("importEditorialStarterPack", {"name": name}, _services(context))


@then('{count:d} policies were created with scope "{scope}"')
def step_created(context, count, scope):
    assert context.import_result["created"] == count, context.import_result
    starters = [r for r in context.store.policies.values() if r["source"].startswith("starter:")]
    assert len(starters) == count and all(r["scope"] == scope for r in starters)


@then('importing "{name}" again creates {count:d} policies')
def step_import_again(context, name, count):
    assert editorial.handle("importEditorialStarterPack", {"name": name}, _services(context))["created"] == count


@when('an admin tries a policy with phrase "{phrase}" on "{text}"')
def step_try(context, phrase, text):
    policy = editorial.policy_from_record(json.loads(json.dumps(editorial.policy_input(_phrase_policy("draft", "publication", "warn", True, phrase)))))
    context.try_result = editorial.handle("tryEditorialPolicy", {"policy": json.dumps(policy), "text": text}, _services(context))


@then('the try result has 1 finding with excerpt "{excerpt}"')
def step_try_finding(context, excerpt):
    assert [f["excerpt"] for f in context.try_result["findings"]] == [excerpt]


@then("no policy was saved")
def step_nothing_saved(context):
    assert context.store.writes == 0


@given('the rewrite model will draft the question "{question}"')
def step_draft_reply(context, question):
    context.generator.reply = {"detectors": [{"id": "hype", "scope": "sentence", "questionType": "noul", "instructions": question, "violationAnswer": "yes", "why": "Hype."}]}


@when('an admin drafts questions for "{title}" with guidance "{guidance}"')
def step_draft(context, title, guidance):
    context.draft_result = editorial.handle("draftEditorialQuestions", {"title": title, "guidance": guidance}, _services(context))


@then("the draft has 1 sentence detector")
def step_draft_result(context):
    assert [d["scope"] for d in context.draft_result["detectors"]] == ["sentence"]


@given('policy "{key}" also has a sentence classifier detector "{detector_id}"')
def step_add_classifier(context, key, detector_id):
    record = context.store.policies[editorial.policy_record_id(key, "publication")]
    detectors = json.loads(record["detectors"])
    detectors.append({"id": detector_id, "lane": "classifier", "scope": "sentence", "question": {"type": "noul", "instructions": "Hype?"}, "violation": {"answer": "yes"}, "threshold": 0.8})
    record["detectors"] = json.dumps(detectors)


@given('editors have recorded {count:d} decisions on "{key}" detector "{detector_id}"')
def step_labels(context, count, key, detector_id):
    rng = random.Random(3)
    for _ in range(count):
        p = round(rng.random(), 2)
        context.store.feedback.append({"policyId": key, "detectorId": detector_id, "lane": "classifier", "probability": p, "decision": "accepted" if rng.random() < 0.5 + (p - 0.5) * 0.3 else "dismissed", "text": None})


@when("an admin recalibrates the policies")
def step_recalibrate(context):
    context.recalibration = editorial.handle("recalibrateEditorialPolicies", {}, _services(context))


@then('policy "{key}" detector "{detector_id}" has an "{method}" calibration')
def step_calibrated(context, key, detector_id, method):
    record = context.store.policies[editorial.policy_record_id(key, "publication")]
    detector = next(d for d in json.loads(record["detectors"]) if d["id"] == detector_id)
    assert detector["calibration"]["method"] == method, detector


@then('policy "{key}" is now version {version:d}')
def step_version(context, key, version):
    assert context.store.policies[editorial.policy_record_id(key, "publication")]["version"] == version


# --- papyrus editorial (CLI) ------------------------------------------------------


@when('an operator imports the style profile "{profile}"')
def step_import_profile(context, profile):
    from pathlib import Path

    from papyrus_content.editorial_commands import import_style_profile

    context.profile_path = Path(profile).resolve()
    context.store.policies.clear()
    context.import_counts = import_style_profile(context.store, context.profile_path, replace=False)


@then('the site has the policies "{keys}" with scope "{scope}"')
def step_imported_policies(context, keys, scope):
    stored = {(r["policyKey"], r["scope"]) for r in context.store.policies.values()}
    for key in (k.strip() for k in keys.split(",")):
        assert (key, scope) in stored, stored
    assert all(r["source"] == "style-profile:fixture-publication" for r in context.store.policies.values())


@then("importing the same profile again creates {count:d} policies")
def step_import_again_profile(context, count):
    from papyrus_content.editorial_commands import import_style_profile

    counts = import_style_profile(context.store, context.profile_path, replace=False)
    assert counts["created"] == count and counts["skipped"] == context.import_counts["created"], counts


@given('a policy-pack file whose policy "{key}" flags "{phrase}"')
def step_pack_file(context, key, phrase):
    import tempfile

    pack = {
        "schemaVersion": 1,
        "packId": "file",
        "version": "1",
        "policies": [editorial.policy_from_record(_phrase_policy(key, "publication", "warn", True, phrase))],
    }
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(pack, handle)
    handle.close()
    context.pack_path = handle.name


@when('an operator runs papyrus editorial check on a draft saying "{text}"')
def step_cli_check(context, text):
    import contextlib
    import io
    import tempfile

    from papyrus_content.editorial_commands import editorial_check

    draft = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
    draft.write(text)
    draft.close()
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        editorial_check(["--draft", draft.name, "--pack", context.pack_path])
    context.cli_result = json.loads(output.getvalue())


@then('the printed check result has a "{key}" finding on "{excerpt}"')
def step_cli_finding(context, key, excerpt):
    assert [(f["policyId"], f["excerpt"]) for f in context.cli_result["findings"]] == [(key, excerpt)], context.cli_result["findings"]


# --- provider keys ------------------------------------------------------------------

PLACEHOLDER = "<value will be resolved during runtime>"


@given('the function environment has Amplify secret placeholders for "{first}" and "{second}"')
def step_secret_placeholders(context, first, second):
    context.function_env = {
        first: PLACEHOLDER,
        second: PLACEHOLDER,
        "AMPLIFY_SSM_ENV_CONFIG": json.dumps({first: {"path": f"/amplify/app/branch/{first}"}, second: {"path": f"/amplify/app/branch/{second}"}}),
    }


@given('SSM holds a value for "{name}" only')
def step_ssm_holds(context, name):
    context.ssm_values = {f"/amplify/app/branch/{name}": "stored-test-value"}


@when("the function prepares its provider keys")
def step_prepare_keys(context):
    def read(parameter_name):
        if parameter_name not in context.ssm_values:
            raise RuntimeError(f"ParameterNotFound: {parameter_name}")
        return context.ssm_values[parameter_name]

    editorial.load_provider_keys(context.function_env, read_parameter=read)


@then('"{name}" is the value stored in SSM')
def step_key_resolved(context, name):
    assert context.function_env.get(name) == "stored-test-value", context.function_env


@then('"{name}" is not set, so rewrite suggestions report that they are not configured')
def step_key_unset(context, name):
    assert name not in context.function_env, context.function_env
