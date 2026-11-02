from __future__ import annotations

import json
import random

from behave import given, step, then, when

from humanus.contracts import validate_payload
from papyrus_content import editorial_checks as editorial


class FakeEditorialStore:
    """The three editorial models, held in memory with the GraphQL store's contract (JSON fields as strings)."""

    def __init__(self) -> None:
        self.policies: dict[str, dict] = {}
        self.settings: dict | None = None
        self.feedback: list[dict] = []
        self.writes = 0
        self.unconfigured_section = False   # the story's section matches no NewsroomSection record
        self.missions = 1               # current publication mission records (the doctrine the judgment lane reads)
        self.items: dict[str, dict] = {}
        self.check_runs: list[dict] = []
        self.story_versions: list[dict] = []

    def list_story_versions(self):
        return [dict(row) for row in self.story_versions]

    def list_policies(self):
        return [dict(record) for record in self.policies.values()]

    def get_editorial_context(self, section):
        """The contract the GraphQL store gets from getEditorialContext with optional publication doctrine."""
        from papyrus_content.editorial_context import build_context
        entries = [{'scope': 'publication', 'kind': 'policy', 'text': 'Synthetic private guidance',
                    'source': {'id': 'synthetic-policy'}}]
        if self.missions == 1:  # none, or more than one current record, means no usable mission (the resolver logs a warning)
            entries.insert(0, {'scope': 'publication', 'kind': 'mission', 'text': 'Synthetic mission',
                               'source': {'id': 'synthetic-mission'}})
        missing_section = bool(section) and self.unconfigured_section
        scope = {'sectionId': None, 'requestedSection': section} if missing_section else {'sectionId': section}
        return build_context({'key': 'synthetic'}, scope, entries, mode='cloud',
                             missing_publication_doctrine=[] if self.missions == 1 else ['mission'],
                             missing_section_configuration=[section] if missing_section else [])

    def publication_key(self):
        return "synthetic"

    def get_item(self, item_id):
        return self.items.get(item_id)

    def put_check_run(self, record):
        self.check_runs = [run for run in self.check_runs if run["id"] != record["id"]] + [record]

    def get_check_run(self, item_id):
        return next((run for run in self.check_runs if run["id"] == item_id), None)

    def list_check_runs_by_lineage(self, lineage_id, limit):
        runs = sorted((run for run in self.check_runs if run["lineageId"] == lineage_id), key=lambda run: -run["versionNumber"])
        return runs[:limit]

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


@given("a site with editorial checks and these policies:")
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


@given("the publication has stored no editorial check settings")
def step_no_settings(context):
    assert context.store.settings is None


@given("the editorial check settings turn editorial checks off")
def step_settings_off(context):
    context.store.settings = {"id": "settings", "settings": json.dumps({"enabled": False})}


@then("the check is refused because editorial checks are turned off")
def step_refused(context):
    assert isinstance(context.check_error, editorial.EditorialChecksDisabled), context.check_error


@then("Humanus was not asked to check")
def step_not_asked(context):
    assert context.services.last_check_request is None


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
    context.check_error = None
    try:
        context.check_result = editorial.handle("checkEditorial", {"body": body, "format": "markus", "section": section}, context.services)
    except (editorial.EditorialChecksDisabled, ValueError) as error:
        context.check_error = error


@then('the check result is a valid Humanus "{schema}" document')
def step_valid(context, schema):
    validate_payload(schema, context.check_result)


@then('the findings are for policies "{keys}"')
def step_findings(context, keys):
    actual = sorted({f["policyId"] for f in context.check_result["findings"]})
    assert actual == sorted(k.strip() for k in keys.split(",")), actual


@then('the "{key}" finding\'s excerpt is "{excerpt}"')
def step_excerpt(context, key, excerpt):
    assert [f["excerpt"] for f in context.check_result["findings"] if f["policyId"] == key] == [excerpt]


@then("Humanus was asked to run the classifier with a {seconds:d} second deadline")
def step_deadline(context, seconds):
    options = context.services.last_check_request["options"]
    assert options["lanes"]["classifier"] is True
    assert options["classifier"]["deadlineSeconds"] == seconds


@then("the classifier lane status is reported")
def step_lane_status(context):
    assert context.check_result["lanes"]["classifier"]["status"] in {"ran", "unavailable", "partial"}


@then("Humanus received {count:d} past decisions as examples")
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


@when('AppSync invokes the function with the field in "{place}"')
def step_event_shape(context, place):
    event = {"arguments": {"itemId": "x"}}
    if place == "the info object":
        event["info"] = {"fieldName": "checkItemVersion"}
    else:
        event["typeName"] = "Mutation"
        event["fieldName"] = "checkItemVersion"
    context.routed_field = editorial.event_field_name(event)


@then('the function routes to "{field}"')
def step_routes(context, field):
    assert context.routed_field == field, context.routed_field


@given("the publication has no current mission")
def step_no_mission(context):
    context.store.missions = 0


@given("the publication has one current mission")
def step_one_mission(context):
    context.store.missions = 1


@given("the publication has {count:d} current missions")
def step_many_missions(context, count):
    context.store.missions = count


@given("the section has no NewsroomSection record")
def step_no_section_record(context):
    context.store.unconfigured_section = True


@then('the section is recorded as skipped because there is "{text}"')
def step_section_skipped(context, text):
    lane = context.check_result["lanes"]["section"]
    assert lane["status"] == "skipped" and lane["reason"].startswith("no section configuration for ") and text in lane["reason"], lane


@then("the stored check run records the section lane as skipped")
def step_run_section_skipped(context):
    assert len(context.store.check_runs) == 1, context.store.check_runs
    lane = context.store.check_runs[0]["lanes"]["section"]
    assert lane["status"] == "skipped" and "no section configuration for engineering" in lane["reason"], lane


@then("Humanus was asked to run without the classifier")
def step_no_classifier(context):
    lanes = context.services.last_check_request["options"]["lanes"]
    assert lanes["rules"] is True and lanes["classifier"] is False, lanes


@then("the classifier lane is skipped because the publication has no mission")
def step_classifier_skipped(context):
    lane = context.check_result["lanes"]["classifier"]
    assert lane["status"] == "skipped" and "mission" in lane["reason"], lane


def _saved_version(context, number, body, *, section="engineering", content_hash=None):
    item_id = f"story-v{number}"
    context.store.items[item_id] = {"id": item_id, "lineageId": "story", "versionNumber": number, "section": section,
                                    "bodyMarkus": body, "contentHash": content_hash or f"hash-of:{section}:{body}"}
    return item_id


def _check_saved(context, item_id):
    context.services = _services(context)  # a new request: nothing asked of Humanus yet
    context.version_result = editorial.handle("checkItemVersion", {"itemId": item_id}, context.services)


@when('the saved version of a story with "{body}" is checked')
def step_check_version(context, body):
    _check_saved(context, _saved_version(context, 1, body))


@step('version {number:d} of the story is saved with "{body}" and checked')
def step_save_and_check(context, number, body):
    _check_saved(context, _saved_version(context, number, body))


@step('version {number:d} of the story is saved in section "{section}" with "{body}" and checked')
def step_save_in_section_and_check(context, number, section, body):
    _check_saved(context, _saved_version(context, number, body, section=section))


@step("version {number:d} of the story is saved with the same content as version {earlier:d} and checked")
def step_save_same_content(context, number, earlier):
    previous = context.store.items[f"story-v{earlier}"]
    _check_saved(context, _saved_version(context, number, previous["bodyMarkus"], section=previous["section"], content_hash=previous["contentHash"]))


@step("version {number:d} of the story is checked again")
def step_check_again(context, number):
    _check_saved(context, f"story-v{number}")


@given("the stored check of version {number:d} did not finish its judgment lane")
def step_unfinished_lane(context, number):
    context.store.check_runs = [
        {**run, "lanes": {**(run.get("lanes") or {}), "classifier": {"status": "partial", "reason": "the check ran out of time"}}} if run["id"] == f"story-v{number}" else run
        for run in context.store.check_runs
    ]


@then("version {number:d} has a stored check with {count:d} finding for policy \"{policy}\"")
def step_stored_findings(context, number, count, policy):
    run = context.store.get_check_run(f"story-v{number}")
    assert run is not None, context.store.check_runs
    matching = [f for f in run["findings"] if f["policyId"] == policy]
    assert len(matching) == count, run["findings"]


@then('version {number:d} has a stored finding for policy "{policy}" with severity "{severity}"')
def step_stored_severity(context, number, policy, severity):
    run = context.store.get_check_run(f"story-v{number}")
    assert any(f["policyId"] == policy and f["severity"] == severity for f in run["findings"]), run["findings"]


@then("the check was skipped as unchanged")
def step_skipped_unchanged(context):
    assert context.version_result.get("skipped") == "unchanged", context.version_result


@then("Humanus was not asked again")
def step_not_asked_again(context):
    assert context.services.last_check_request is None, "Humanus was asked to check identical content again"


@then("Humanus was asked to check")
def step_asked_to_check(context):
    assert context.services.last_check_request is not None
    assert context.version_result.get("skipped") is None, context.version_result


@then("the stored check run records the classifier lane as skipped")
def step_run_skipped(context):
    assert len(context.store.check_runs) == 1, context.store.check_runs
    lane = context.store.check_runs[0]["lanes"]["classifier"]
    assert lane["status"] == "skipped" and "mission" in lane["reason"], lane


@then('the check fails with "{text}"')
def step_check_fails(context, text):
    assert context.check_error is not None and text in str(context.check_error), context.check_error


# --- papyrus editorial policies add / export ----------------------------------------


def _run_policies(context, **options):
    import argparse
    import contextlib
    import io

    from papyrus_content.editorial_commands import editorial_policies_pack

    args = argparse.Namespace(**{"dry_run": False, "publication": None, "actor": None, **options})
    out = io.StringIO()
    context.policies_error = None
    context.store.writes = 0
    try:
        with contextlib.redirect_stdout(out):
            editorial_policies_pack(context.store, args)
    except ValueError as error:
        context.policies_error = str(error)
    context.policies_output = out.getvalue()


@given("a site with no editorial policies")
def step_no_policies(context):
    context.store.policies.clear()


@given('a policy-pack file with a classifier question')
def step_classifier_pack(context):
    import shutil
    import tempfile
    from pathlib import Path

    context.pack_dir = Path(tempfile.mkdtemp())
    context.pack_path = context.pack_dir / "pack.json"
    shutil.copy("features_backend/fixtures/editorial-checks/classifier-pack.json", context.pack_path)


@step("the pack's threshold is changed to {threshold:g}")
def step_change_threshold(context, threshold):
    pack = json.loads(context.pack_path.read_text())
    pack["policies"][0]["detectors"][0]["threshold"] = threshold
    context.pack_path.write_text(json.dumps(pack))


@step("the pack's threshold is 7")
def step_bad_threshold(context):
    pack = json.loads(context.pack_path.read_text())
    pack["policies"][0]["detectors"][0]["threshold"] = 7
    context.pack_path.write_text(json.dumps(pack))


@when("an operator adds the pack with papyrus editorial policies add")
def step_add_pack(context):
    _run_policies(context, action="add", file=str(context.pack_path), actor="ryan")


@when("an operator dry-runs adding the pack")
def step_dry_run_pack(context):
    _run_policies(context, action="add", file=str(context.pack_path), dry_run=True)


@when('an operator adds the pack for publication "{publication}"')
def step_add_pack_publication(context, publication):
    _run_policies(context, action="add", file=str(context.pack_path), publication=publication)


@when("an operator exports the policies and the site loses them and adds the export")
def step_export_round_trip(context):
    exported = context.pack_dir / "export.yml"
    _run_policies(context, action="export", file=str(exported), pack_id="site-policies", pack_version=None)
    assert context.policies_error is None, context.policies_error
    context.before = {key: json.loads(r["detectors"]) for key, r in context.store.policies.items()}
    context.store.policies.clear()
    _run_policies(context, action="add", file=str(exported))


@then('policy "{key}" is stored as version {version:d} with source "{source}"')
def step_stored_with_source(context, key, version, source):
    record = context.store.policies[editorial.policy_record_id(key, "publication")]
    assert record["version"] == version and record["source"] == source, record


@then('policy "{key}" keeps its classifier question, "{answer}" violation, threshold {threshold:g}, review threshold {review:g} and message')
def step_classifier_saved(context, key, answer, threshold, review):
    detector = json.loads(context.store.policies[editorial.policy_record_id(key, "publication")]["detectors"])[0]
    assert detector["lane"] == "classifier" and detector["scope"] == "document", detector
    assert detector["question"]["type"] == "noul" and detector["question"]["instructions"].startswith("Does this document"), detector
    assert detector["violation"] == {"answer": answer} and detector["threshold"] == threshold and detector["reviewAt"] == review, detector
    assert detector["message"] == "States a claim without a source.", detector


@then("the policy command wrote {count:d} policies")
def step_wrote(context, count):
    assert context.policies_error is None, context.policies_error
    assert context.store.writes == count, (context.store.writes, context.policies_output)


@then('the plan says "{text}"')
def step_plan_says(context, text):
    assert text.replace("\\t", "\t") in context.policies_output, context.policies_output


@then('the policy command is refused with "{text}"')
def step_refused(context, text):
    assert context.policies_error and text in context.policies_error, context.policies_error
    assert context.store.writes == 0


@then("the site has the same detectors as before")
def step_same_detectors(context):
    after = {key: json.loads(r["detectors"]) for key, r in context.store.policies.items()}
    assert after == context.before, (after, context.before)


# --- cross-story boilerplate ---------------------------------------------------------------------------------------------


CLOSING = (
    "We run this for clients at scale and we keep the source open so every client owns the whole thing "
    "and can read exactly how it works before they ever pay us"
)


def _site_story(context, lineage, body, *, number=1, state="current", slug=None):
    context.store.story_versions.append({
        "id": f"{lineage}-v{number}", "lineageId": lineage, "versionNumber": number, "versionState": state,
        "slug": slug or lineage, "bodyMarkus": body,
    })


@given('the site has a current story "{slug}" that ends with the standard closing')
def step_other_story_closing(context, slug):
    _site_story(context, slug, f"Something unique about {slug} goes here and nowhere else.\n\n{CLOSING}.")


@given('the site has a current story "{slug}" that says "{body}"')
def step_other_story_says(context, slug, body):
    _site_story(context, slug, body)


@given('the site has a superseded version of the story "{slug}" that ends with the standard closing')
def step_superseded_story(context, slug):
    _site_story(context, slug, f"Older text.\n\n{CLOSING}.", state="superseded")


@when('the saved version of the story "{slug}" ends with the standard closing and is checked')
def step_check_story_with_closing(context, slug):
    context.slug = slug
    item_id = _saved_version(context, 1, f"A different opening for {slug} appears here.\n\n{CLOSING}.")
    context.store.items[item_id].update({"lineageId": slug, "id": f"{slug}-v1"})
    context.store.items[f"{slug}-v1"] = context.store.items.pop(item_id)
    _check_saved(context, f"{slug}-v1")


@when('version 2 of the story "{slug}" is saved with its own earlier closing and checked')
def step_check_own_earlier(context, slug):
    _site_story(context, slug, f"Earlier opening.\n\n{CLOSING}.", number=1)
    item = _saved_version(context, 2, f"Newer opening.\n\n{CLOSING}.")
    context.store.items[f"{slug}-v2"] = {**context.store.items.pop(item), "id": f"{slug}-v2", "lineageId": slug}
    _check_saved(context, f"{slug}-v2")


@when('the saved version of the story "{slug}" with "{body}" is checked')
def step_check_story_with_body(context, slug, body):
    item = _saved_version(context, 1, body)
    context.store.items[f"{slug}-v1"] = {**context.store.items.pop(item), "id": f"{slug}-v1", "lineageId": slug}
    _check_saved(context, f"{slug}-v1")


@then('the story "{slug}" has a stored "cross-story-boilerplate" finding naming "{other}"')
def step_xstory_names(context, slug, other):
    run = context.store.get_check_run(f"{slug}-v1")
    found = [f for f in run["findings"] if f["policyId"] == "cross-story-boilerplate"]
    assert found and all(f["severity"] == "warn" for f in found), run["findings"]
    assert any(other in f["message"] for f in found), found


@then('the story "{slug}" has no stored "cross-story-boilerplate" finding')
def step_no_xstory(context, slug):
    run = context.store.get_check_run(f"{slug}-v{2 if context.store.get_check_run(f'{slug}-v2') else 1}")
    assert not [f for f in run["findings"] if f["policyId"] == "cross-story-boilerplate"], run["findings"]


@then('the "cross-story-boilerplate" finding does not name "{other}"')
def step_xstory_not_naming(context, other):
    for run in context.store.check_runs:
        for finding in run["findings"]:
            if finding["policyId"] == "cross-story-boilerplate":
                assert other not in finding["message"], finding


# --- command-line findings and whole-story judgments ---------------------------------------------------------------------

def _finding(**values):
    return {"id": "f-0", "policyId": "p", "severity": "warn", "status": "review", "message": "m", "excerpt": "", "segmentId": "s1", **values}


@given('a stored check of version 1 with a violation of "{violation}" on "{excerpt}" and a judgment for review of "{review}" on "{reviewed}"')
def step_stored_check(context, violation, excerpt, review, reviewed):
    context.stored_run = {"findings": [
        _finding(id="f-review", policyId=review, status="review", probability=0.53, message="Is this measured or modeled?", excerpt=reviewed),
        _finding(id="f-violation", policyId=violation, severity="error", status="violation", probability=0.91, message="Avoid hype.", excerpt=excerpt),
    ], "violations": 1, "reviews": 1}


def _run_check_version(context, flags):
    import contextlib
    import io
    from unittest import mock

    from papyrus_content import editorial_commands as commands

    summary = {"itemId": "story-v1", "violations": 1, "reviews": 1}
    output = io.StringIO()
    with mock.patch.object(commands, "request_item_check", return_value=summary), \
            mock.patch.object(commands, "read_item_check_run", return_value=context.stored_run), \
            contextlib.redirect_stdout(output):
        commands.editorial_check_version(["--item", "story-v1", *flags])
    context.printed = output.getvalue()


@when("an operator runs papyrus editorial check-version on version 1")
def step_check_version_cli(context):
    _run_check_version(context, [])


@when("an operator runs papyrus editorial check-version on version 1 with --json")
def step_check_version_json(context):
    _run_check_version(context, ["--json"])


@then('the printed summary says "{violations}" and "{reviews}"')
def step_printed_summary(context, violations, reviews):
    first = context.printed.splitlines()[0]
    assert violations in first and reviews in first, first


@then("each finding is printed with its policy, severity, probability, message, excerpt and id")
def step_printed_findings(context):
    for expected in ("no-hype", "error", "p=0.91", "Avoid hype.", "game-changing", "f-violation",
                     "measured-or-model", "warn", "p=0.53", "Is this measured or modeled?", "Sales doubled.", "f-review"):
        assert expected in context.printed, (expected, context.printed)


@then("the violation is printed before the finding for review")
def step_violation_first(context):
    assert context.printed.index("f-violation") < context.printed.index("f-review"), context.printed


@then("the printed JSON lists both findings with their ids, probabilities and excerpts")
def step_printed_json(context):
    payload = json.loads(context.printed)
    assert [(f["id"], f["probability"], f["excerpt"]) for f in payload["findings"]] == [
        ("f-review", 0.53, "Sales doubled."), ("f-violation", 0.91, "game-changing")], payload
    assert payload["summary"]["violations"] == 1


@given('Humanus returns a judgment finding for the whole story and one for the sentence "{sentence}"')
def step_humanus_judgments(context, sentence):
    from unittest import mock

    result = {"findings": [
        _finding(id="f-doc", segmentId="doc", message="Claims are measured or modeled.", excerpt=""),
        _finding(id="f-sentence", segmentId="s1", message="Claim lacks a source.", excerpt=sentence),
    ], "lanes": {}}
    patcher = mock.patch.object(editorial.humanus, "check", return_value=result)
    patcher.start()
    context.add_cleanup(patcher.stop)


@then('the whole-story finding\'s message starts with "{prefix}"')
def step_whole_story_message(context, prefix):
    finding = next(f for f in context.check_result["findings"] if f["id"] == "f-doc")
    assert finding["message"].startswith(prefix) and finding["excerpt"] == "", finding


@then('the sentence finding keeps its excerpt "{excerpt}" and its message unchanged')
def step_sentence_unchanged(context, excerpt):
    finding = next(f for f in context.check_result["findings"] if f["id"] == "f-sentence")
    assert finding["excerpt"] == excerpt and finding["message"] == "Claim lacks a source.", finding
