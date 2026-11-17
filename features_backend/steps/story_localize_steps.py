"""A published Story is translated by one procedure (features_backend/story-localize.feature).

The run goes through `localize.run.localize_story` on the shared in-memory fake backend, with the site's reads (settings, glossary, policies,
spend history) given as the Machines on Machines starters and the attachments kept in memory. The translator, judge and repairer are scripted;
nothing here reaches a network."""

from __future__ import annotations

import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content.localize import desired_state, record as localize_record  # noqa: E402
from papyrus_content.localize.checks import BlockChecker, starter_pack  # noqa: E402
from papyrus_content.localize.engine import LocalizeRequest  # noqa: E402
from papyrus_content.localize.models import ModelUnavailable  # noqa: E402
from papyrus_content.localize.run import localize_story  # noqa: E402
from papyrus_content.translation_glossary import starter_glossary  # noqa: E402

STORY = "story-waymo"
LINEAGE = "story-waymo--es-419"
P1 = "Waymo cars may crash 68 percent less often, the company says."
P2 = "The [report](https://example.test/report) covers 12 cities."
IMAGE = '::image{src="assets/waymo.png" alt="A driverless car" credit="Image: Jane Doe, CC BY 2.0"}'
TITLE, DECK = "Waymo crashes fall", "A report from twelve cities."
SPANISH = {
    TITLE: "Bajan los choques de Waymo",
    DECK: "Un informe de doce ciudades.",
    "Waymo cars may crash 68 percent less often, the company says.": "Los autos de Waymo pueden chocar un 68 % menos, según la empresa.",
    "The [report]⟦1⟧ covers 12 cities.": "El [informe]⟦1⟧ abarca 12 ciudades.",
    '::image{src="⟦1⟧" alt="A driverless car" credit="⟦2⟧"}': '::image{src="⟦1⟧" alt="Un auto sin conductor" credit="⟦2⟧"}',
    "Waymo cars may crash 70 percent less often, the company says.": "Los autos de Waymo pueden chocar un 70 % menos, según la empresa.",
    "A short summary of the report.": "Un breve resumen del informe.",
    "A white car on a road.": "Un auto blanco en una carretera.",
    "It is worth noting that the report covers 12 cities.": "Cabe destacar que el informe abarca 12 ciudades.",
}
USAGE = {"input_tokens": 1000, "output_tokens": 500}


class Scripted:
    """The translator, judge and repairer: tables of what each answers, and a record of every request."""

    model = "gpt-6-luna"

    def __init__(self, world):
        self.world = world
        self.spend = None
        self.translate_requests: list[dict] = []
        self.refine_requests: list[dict] = []
        self.judge_calls = 0

    def bind(self, spend):
        self.spend = spend
        return self

    def translate(self, request):
        self.translate_requests.append(request)
        self.spend.add("translate", self.model, USAGE)
        table = {**SPANISH, **self.world.translations}
        first = getattr(self.world, "first_answers", {})
        return {"blocks": [{"id": block["id"], "text": first.pop(block["text"], None) or table.get(block["text"], block["text"])} for block in request["blocks"]]}

    def refine(self, request):
        self.refine_requests.append(request)
        self.spend.add("refine", self.model, USAGE)
        return {"blocks": [{"id": block["id"], "text": self.world.repair(block["current"])} for block in request["blocks"]]}

    def judge(self, prompt):
        self.judge_calls += 1
        if self.world.judge_down:
            raise ModelUnavailable("the model service could not be reached (URLError)")
        self.spend.add("judge", self.model, {"input_tokens": 300, "output_tokens": 40})
        match = re.search(r"SOURCE \(en\):\n(.*)\n\nTRANSLATION \([^)]*\):\n(.*)$", prompt["user"], re.S)
        source, target = match.group(1), match.group(2)
        issues = []
        if "the company says" in source and "según" not in target:
            issues.append({"category": "attribution-changed", "sourceQuote": "the company says", "targetQuote": target.split(",")[0],
                           "explanation": "The attribution to the company was dropped."})
        if " may " in source and "pueden" not in target:
            issues.append({"category": "certainty-changed", "sourceQuote": "may", "targetQuote": target.split(" ")[0],
                           "explanation": "The hedge 'may' was dropped."})
        return {"issues": issues}


@given('the published English Story "{story}" version {number:d} in the Machines on Machines newsroom')
def step_story(context, story, number):
    context.client = FakeAuthoringClient()
    context.files: dict[str, bytes] = {}
    context.translations: dict[str, str] = {}
    context.repair = lambda text: text
    context.judge_down = False
    context.ceiling = None
    context.paragraphs = [P1, P2, IMAGE]
    _publish(context, number)


def _publish(context, number: int) -> None:
    body = "\n\n".join(context.paragraphs) + "\n"
    row = {"id": f"{STORY}-v{number}", "lineageId": STORY, "versionNumber": number, "versionState": "current", "type": "article", "status": "published",
           "stage": "published", "slug": "waymo-crashes-fall", "section": "machines", "title": TITLE, "headline": TITLE, "deck": DECK, "bodyMarkus": body,
           "contentHash": f"hash-v{number}", "language": "en", "languageGroupId": STORY, "updatedAt": "2026-11-13T00:00:00Z",
           "metadata": json.dumps({"frontMatterYaml": f"title: {TITLE}\ndeck: {DECK}\n"})}
    context.client.tables.setdefault("Item", {})[row["id"]] = row
    context.primary = row


@given('a scripted translator, judge and repairer for "{language}"')
def step_models(context, language):
    context.language = language
    context.models = Scripted(context)


def _collect(context):
    def collect(client, *, story, language, judge, procedure_version, ceiling_usd=None, decision_model=None, automation_id=None, procedure_key=None):
        source = localize_record.source_version(context.primary, "en")
        lineage = f"{story}--{language}"
        current, previous = localize_record.previous_alignment(client, lineage)
        source, previous, variants = localize_record.with_image_variants(client, context.primary, source, current, previous)
        glossary = starter_glossary(language)
        checker = BlockChecker(source_language="en", target_language=language, glossary=glossary, copy_edit_pack=starter_pack(language, getattr(context, "register", None)), judge=judge,
                               lanes={"rules": True, "classifier": False})
        if getattr(context, "blind_note_structure", False):
            checker.faithfulness = _blind_to_note_structure(checker.faithfulness)
        english = BlockChecker(source_language="en", target_language="en", glossary=glossary, copy_edit_pack=starter_pack("en"), judge=None,
                               lanes={"rules": True, "classifier": False})
        key = localize_record.run_key(source, language, procedure_version=procedure_version, checker_versions=checker.versions)
        return LocalizeRequest(source=source, language=language, localization_lineage=lineage, run_key=key, glossary=glossary, checker=checker,
                               slug_policy="translated", previous=previous, ceiling_usd=context.ceiling, procedure_version=procedure_version,
                               source_checker=lambda text: english.copy_edit(text)[0], image_variants=variants)
    return collect


def _blind_to_note_structure(faithfulness):
    """The block check as it was on the held run: it did not report the structure of a note container, so only the whole-body check saw it."""
    def check(source, target):
        findings, lanes = faithfulness(source, target)
        if source.startswith(":::note"):
            findings = [f for f in findings if f.policy != "structure"]
        return findings, lanes
    return check


def _upload(context):
    def upload(client, attachment, body):
        client.tables.setdefault("ModelAttachment", {})[attachment["id"]] = dict(attachment)
        context.files[attachment["storagePath"]] = bytes(body)
        return attachment
    return upload


def _run(context):
    context.models.translate_requests.clear()
    context.models.refine_requests.clear()
    context.client.calls.clear()
    context.error = None
    with mock.patch("papyrus_content.localize.run.collect", _collect(context)), \
            mock.patch("papyrus_content.model_attachments.upload_attachment_body", _upload(context)), \
            mock.patch("papyrus_content.model_attachments.download_attachment_buffer", lambda client, row: context.files.get(row["storagePath"])):
        try:
            context.output = localize_story(context.client, story=STORY, language=context.language, models=context.models.bind)
        except Exception as error:   # noqa: BLE001 - the scenario reads the failure
            context.error = error
            context.output = None


@when('the translation run for "{language}" runs')
def step_run(context, language):
    _run(context)


@given('the translation run for "{language}" has finished')
def step_finished(context, language):
    _run(context)
    assert context.output and context.output["outcome"] in ("saved", "held"), (context.output, context.error)


@when("the same run is started again")
def step_again(context):
    context.versions_before = len(_versions(context))
    context.judge_before = context.models.judge_calls
    _run(context)


def _versions(context):
    return sorted((row for row in context.client.tables.get("Item", {}).values() if row.get("lineageId") == LINEAGE), key=lambda r: r["versionNumber"])


def _latest(context):
    versions = _versions(context)
    assert versions, "no translation was saved"
    return versions[-1]


def _provenance(context, row=None):
    row = row or _latest(context)
    attachment = context.client.tables["ModelAttachment"][next(key for key, value in context.client.tables["ModelAttachment"].items()
                                                                if value["ownerId"] == row["id"] and value["role"] == "localization_provenance")]
    return json.loads(context.files[attachment["storagePath"]])


@then("the run is saved, not held")
def step_saved(context):
    assert context.error is None, context.error
    assert context.output["outcome"] == "saved" and context.output["hold"] is False, context.output


@then('a version of "{lineage}" exists written in "{language}" in the language group "{group}"')
def step_version(context, lineage, language, group):
    row = _latest(context)
    assert row["lineageId"] == lineage and row["language"] == language and row["languageGroupId"] == group, row


@then('that version is unpublished, has no board stage and was written by "{actor}"')
def step_unpublished(context, actor):
    row = _latest(context)
    assert row["status"] == "draft" and not row.get("stage") and not row.get("headStageKey") and row["versionCreatedBy"] == actor, row
    assert not context.client.tables.get("PublishedItem")


@then("it names source version 3 and the source's content hash")
def step_source(context):
    row = _latest(context)
    assert row["sourceLineageId"] == STORY and row["sourceVersionNumber"] == 3 and row["sourceContentHash"] == "hash-v3", row


@then("its provenance names the models, the rule versions, the findings and the cost")
def step_provenance(context):
    provenance = _provenance(context)
    assert provenance["models"]["translate"] == "gpt-6-luna" and provenance["models"]["judge"] == "gpt-6-luna"
    assert provenance["versions"]["faithfulnessPack"].startswith("translation-faithfulness@") and provenance["versions"]["glossary"].startswith("sha256:")
    assert "findings" in provenance and provenance["cost"]["totalUsd"] > 0 and provenance["source"]["contentHash"] == "hash-v3"


@then("the English Story's version is unchanged")
def step_english_unchanged(context):
    assert not [call for call in context.client.calls if call[0] in ("update", "upsert") and call[2] == context.primary["id"]], context.client.calls


@then('no text sent to the translator contains "{url}" or "{name}"')
def step_never_sent(context, url, name):
    sent = json.dumps(context.models.translate_requests, ensure_ascii=False)
    assert url not in sent and name not in sent, sent


@given('the translator first answers "{damaged}" for "{source}" and is right when asked again')
def step_damaged_first(context, damaged, source):
    context.first_answers = {source: damaged}


@then("the translator was asked again about the link and told where the target belongs, without being shown the target")
def step_asked_again(context):
    asked = [block for request in context.models.translate_requests for block in request["blocks"] if block.get("problem")]
    assert asked and "directly after the closing" in asked[0]["problem"], asked
    assert "https://example.test/report" not in json.dumps(context.models.translate_requests, ensure_ascii=False)


@then('the saved translation has the link "{text}" with its target and no stray address')
def step_link_whole(context, text):
    body = _latest(context)["bodyMarkus"]
    assert f"[{text}](https://example.test/report)" in body and body.count("https://example.test/report") == 1, body


@then("the saved translation keeps the link target and the credit exactly as the English has them")
def step_kept(context):
    body = _latest(context)["bodyMarkus"]
    assert "](https://example.test/report)" in body and 'credit="Image: Jane Doe, CC BY 2.0"' in body, body


@given('the translator writes "{wrong}" where the English says "{right}"')
def step_wrong_number(context, wrong, right):
    if right == "68 percent":
        context.translations[P1] = SPANISH[P1].replace("68 %", wrong)
    else:
        context.translations["The [report]⟦1⟧ covers 12 cities."] = "El [informe]⟦1⟧ abarca varias ciudades."


@given("the repairer keeps the wrong wording")
def step_repairer_keeps(context):
    context.repair = lambda text: text


@then('the saved translation says "{text}"')
def step_says(context, text):
    assert text in _latest(context)["bodyMarkus"], _latest(context)["bodyMarkus"]


@then("the run records one round that changed one block")
def step_one_round(context):
    rounds = _provenance(context)["rounds"]
    assert len(rounds) == 1 and rounds[0]["changed"] == 1, rounds


@given('the translator drops the attribution "the company says"')
def step_drops_attribution(context):
    context.translations[P1] = "Los autos de Waymo pueden chocar un 68 % menos."


@given('the repairer\'s rewrite also drops "may"')
def step_repair_drops_may(context):
    context.repair = lambda text: "Los autos de Waymo chocan un 68 % menos, según la empresa." if "Waymo" in text else text


@then("the rewrite is discarded and the earlier wording kept")
def step_discarded(context):
    assert "pueden chocar un 68 % menos." in _latest(context)["bodyMarkus"] and "chocan" not in _latest(context)["bodyMarkus"]


@then("the run records one reverted block")
def step_reverted(context):
    assert context.output["revertedBlocks"] == 1 and _provenance(context)["revertedBlocks"] == 1, context.output


@then("the run is held, and the review request names the dropped attribution")
def step_held_attribution(context):
    assert context.output["hold"] is True, context.output
    (review,) = context.client.tables["ReviewRequest"].values()
    assert "attribution" in review["reason"], review


@then("the run is held")
def step_held(context):
    assert context.error is None, context.error
    assert context.output["hold"] is True and context.output["outcome"] == "held", context.output


@then('a flag review request on "{lineage}" names the missing number')
def step_review_number(context, lineage):
    (review,) = context.client.tables["ReviewRequest"].values()
    subject = review["subject"] if isinstance(review["subject"], dict) else json.loads(review["subject"])
    assert review["mode"] == "flag" and subject == {"type": "story", "id": lineage} and "12" in review["reason"], review


@then("the translation is saved unpublished all the same")
def step_saved_anyway(context):
    assert _latest(context)["status"] == "draft" and not context.client.tables.get("PublishedItem")


@then("no model is called")
def step_no_model(context):
    assert not context.models.translate_requests and not context.models.refine_requests and context.models.judge_calls == context.judge_before
    assert context.output["outcome"] == "unchanged", context.output


@then("no translation version is saved")
def step_no_version(context):
    assert len(_versions(context)) == context.versions_before


@given("a corrector rewrote the translated dek")
def step_corrector(context):
    row = _latest(context)
    provenance = _provenance(context, row)
    for entry in provenance["alignment"]:
        if entry["text"] == SPANISH[DECK]:
            entry.update(text="Un informe sobre doce ciudades, revisado.", owner="human", pinned=True)
    attachment = next(value for value in context.client.tables["ModelAttachment"].values() if value["ownerId"] == row["id"] and value["role"] == "localization_provenance")
    context.files[attachment["storagePath"]] = json.dumps(provenance).encode()


@when("the English Story is republished as version {number:d} with one paragraph changed and the translation asked for again")
def step_republish(context, number):
    context.client.tables["Item"][context.primary["id"]]["versionState"] = "superseded"
    context.paragraphs = [P1.replace("68", "70"), P2, IMAGE]
    _publish(context, number)
    desired_state.want(context.client, source=context.primary, language=context.language, requested_by="cli")


@given('an editor asked for the "{language}" translation of "{story}"')
def step_asked(context, language, story):
    desired_state.want(context.client, source=context.primary, language=language, requested_by="cli")


@then("exactly one block was sent to the translator")
def step_one_block(context):
    sent = [block for request in context.models.translate_requests for block in request["blocks"]]
    assert len(sent) == 1, sent


@then("the dek is exactly as the corrector wrote it")
def step_dek(context):
    assert _latest(context)["deck"] == "Un informe sobre doce ciudades, revisado.", _latest(context)["deck"]


@given('the English Story\'s second paragraph says "{text}"')
def step_second_paragraph(context, text):
    context.paragraphs[1] = text
    _publish(context, context.primary["versionNumber"])


@given('the site\'s "{language}" writing guidelines choose the register "{register}"')
def step_register(context, language, register):
    context.register = register


@given('the translator writes "{text}" for the second paragraph')
def step_second_translation(context, text):
    context.translations[re.sub(r"\]\((https?://[^)]+)\)", "]⟦1⟧", context.paragraphs[1])] = text


@then("the repairer was never asked")
def step_repairer_idle(context):
    assert not context.models.refine_requests, context.models.refine_requests


@given('the translator keeps the stock phrase as "{text}"')
def step_stock(context, text):
    pass   # the scripted table already renders the paragraph this way


@then('the English Story\'s version carries advice for "{language}" naming the phrase "{phrase}"')
def step_advice(context, language, phrase):
    metadata = json.loads(context.client.tables["Item"][context.primary["id"]]["metadata"])
    phrases = metadata["translationAdvice"][language]["phrases"]
    assert any(phrase in entry["phrase"] for entry in phrases), phrases


@given("the judging model cannot be reached")
def step_judge_down(context):
    context.judge_down = True


@then("the run fails saying the model service could not be reached")
def step_failed(context):
    assert isinstance(context.error, ModelUnavailable) and "could not be reached" in str(context.error), context.error


@then("no translation is saved")
def step_nothing_saved(context):
    assert not _versions(context)


@when("the judging model is back and the run starts again")
def step_back(context):
    context.judge_down = False
    _run(context)


@then("the translator is not called again")
def step_translator_not_again(context):
    assert not context.models.translate_requests, context.models.translate_requests


@given("the run's ceiling is already spent by the first translation")
def step_ceiling(context):
    context.ceiling = 0.0000001


@then("the run is held because its cost reached the ceiling")
def step_held_cost(context):
    assert context.output["hold"] is True and "ceiling" in context.output["reason"], context.output


@then("no repair round ran")
def step_no_round(context):
    assert context.output["rounds"] == 0 and not context.models.refine_requests, context.output


# --- the desired-state record ------------------------------------------------------------------------------------------------

@when('an editor asks for the "{language}" translation of "{story}"')
def step_ask(context, language, story):
    context.output_lines = _command(context, ["--story", story, "--language", language, "--automation", "mom.story-localize"])


@given("nobody asked for a translation")
def step_nobody(context):
    context.client.tables.pop("LocalizationRequest", None)


def _command(context, flags):
    from papyrus_content import story_commands

    context.started = []

    def graphql(query, variables=None):
        context.started.append(variables)
        return {"runAutomation": json.dumps({"state": "started", "key": "run-1"})}

    context.client.graphql = graphql
    out = io.StringIO()
    with mock.patch.object(story_commands, "create_authoring_client", return_value=(context.client, None)), \
            mock.patch("papyrus_content.localize.record.collect", _collect(context)), \
            mock.patch("papyrus_content.story_reporting.published_story_version", lambda client, story: context.primary), redirect_stdout(out):
        story_commands.stories_localize(flags)
    return out.getvalue().splitlines()


@then('the request "{request_id}" names source version {number:d} and is wanted')
def step_wanted(context, request_id, number):
    row = context.client.tables["LocalizationRequest"][request_id]
    assert row["sourceVersionNumber"] == number and row["state"] == "wanted", row
    assert context.started and json.loads(context.started[0]["input"])["language"] == "es-419", context.started


@then('the request "{request_id}" is saved with the run\'s key')
def step_saved_key(context, request_id):
    row = context.client.tables["LocalizationRequest"][request_id]
    assert row["state"] == "saved" and row["runKey"] == context.output["runKey"], row


@then("the run stops saying no translation is requested")
def step_stops_none(context):
    assert context.output["outcome"] == "stopped" and "no translation is requested" in context.output["reason"], context.output


@then("no model is called for it")
def step_no_model_for_it(context):
    assert not context.models.translate_requests and context.models.judge_calls == 0, context.models.judge_calls


@given("the English Story is republished as version 4 and the translation asked for again")
def step_republished(context):
    context.client.tables["Item"][context.primary["id"]]["versionState"] = "superseded"
    _publish(context, 4)
    desired_state.want(context.client, source=context.primary, language=context.language, requested_by="cli")


@when("a run started for version {number:d} runs")
def step_run_for(context, number):
    with mock.patch("papyrus_content.localize.run.collect", _collect(context)), \
            mock.patch("papyrus_content.model_attachments.upload_attachment_body", _upload(context)):
        context.output = localize_story(context.client, story=STORY, language=context.language, source_version=number, models=context.models.bind)


@then("the run stops saying a newer source is requested")
def step_stops_newer(context):
    assert context.output["outcome"] == "stopped" and "newer source" in context.output["reason"], context.output


@when('an editor previews the "{language}" translation of "{story}"')
def step_preview(context, language, story):
    context.output_lines = _command(context, ["--story", story, "--language", language, "--dry-run"])


@then("the plan lists {count:d} blocks to translate and the glossary terms the translator will meet")
def step_plan(context, count):
    (line,) = context.output_lines
    plan = json.loads(line.split("\t")[3])
    assert plan["blocksToTranslate"] == count and isinstance(plan["glossaryTerms"], list), plan


@then("no request was written")
def step_no_request(context):
    assert not context.client.tables.get("LocalizationRequest") and not context.started


@given('the English Story has the stored picture "{path}"')
def step_picture(context, path):
    context.client.tables.setdefault("MediaAsset", {})["media-waymo"] = {
        "id": "media-waymo", "itemId": context.primary["id"], "type": "image", "sortKey": "0001", "metadata": json.dumps({"srcPath": path})}


@then('the saved translation\'s address is "{slug}" and not the English "{english}"')
def step_address(context, slug, english):
    assert _latest(context)["slug"] == slug != english, _latest(context)["slug"]


@then('the saved translation has the stored picture "{path}", so it can be published')
def step_has_picture(context, path):
    pictures = [json.loads(row["metadata"])["srcPath"] for row in context.client.tables["MediaAsset"].values() if row["itemId"] == _latest(context)["id"]]
    assert pictures == [path], pictures


@then("the Spanish lineage has {count:d} versions")
def step_versions_count(context, count):
    assert len(_versions(context)) == count, [row["versionNumber"] for row in _versions(context)]


# --- the cost history is read through the automation's procedure key ------------------------------------------------------------

@given("a site registered the translation procedure under its own key and an automation that runs it")
def step_own_key(context):
    context.client.tables.setdefault("Automation", {})["mom.story-localize"] = {"id": "mom.story-localize", "procedureKey": "mom.registered-story-localize"}
    context.client.tables.setdefault("ProcedureRun", {})["run-1"] = {
        "id": "run-1", "procedureKey": "mom.registered-story-localize", "runStatus": "completed", "requestedAt": "2026-11-13T10:00:00Z",
        "output": json.dumps({"language": "es-419", "sourceCharacters": 1200, "costUsd": 0.03})}
    context.client.tables["ProcedureRun"]["other"] = {
        "id": "other", "procedureKey": "papyrus.story.localize", "runStatus": "completed", "requestedAt": "2026-11-13T11:00:00Z",
        "output": json.dumps({"language": "es-419", "sourceCharacters": 9, "costUsd": 9.0})}


@when("a translation is planned or run for that automation")
def step_plan_for_automation(context):
    context.procedure_key = localize_record.automation_procedure_key(context.client, "mom.story-localize")
    context.history = localize_record.spend_history(context.client, context.procedure_key)


@then("the predicted cost comes from that procedure's measured runs, found through the automation's procedure key")
def step_history_from_key(context):
    assert context.procedure_key == "mom.registered-story-localize", context.procedure_key
    assert context.history == [{"language": "es-419", "sourceCharacters": 1200, "costUsd": 0.03}], context.history


@then("a plan with no automation named predicts from no history")
def step_no_automation_no_history(context):
    assert localize_record.automation_procedure_key(context.client, None) is None


@then("an automation that does not exist is refused naming it")
def step_missing_automation(context):
    try:
        localize_record.automation_procedure_key(context.client, "mom.missing")
    except ValueError as error:
        assert "mom.missing" in str(error), error
    else:
        raise AssertionError("a missing automation was accepted")


# --- a run started from the command line, with no automation ----------------------------------------------------------------

def _run_here(context, *, lane="iam", key="test-key", run_status="completed", not_registered=False):
    """`stories localize` with no --automation, the runner's code replaced by a recorder (it would load the procedure from a site)."""
    import os

    from papyrus_content import story_commands
    from papyrus_content.localize import start
    from papyrus_content.procedure_runner import ProcedureNotRunnable

    context.runner_calls = []
    context.started = []

    def run(request, **kwargs):
        context.runner_calls.append({"request": request, **kwargs, "request_was_written": bool(context.client.tables.get("LocalizationRequest"))})
        if not_registered:
            raise ProcedureNotRunnable("ProcedureDefinition not found.")
        return {"runId": "run-9", "runStatus": run_status, "costUsd": 0.02, "error": None if run_status == "completed" else "the model was down",
                "output": {"outcome": "saved"}}

    context.client.endpoint = "https://abc123.appsync-api.us-east-1.amazonaws.com/graphql"
    context.client.tenant_id = "mom"
    context.client.graphql = lambda query, variables=None: context.started.append(variables) or {}
    environment = {"PAPYRUS_GRAPHQL_AUTH": lane} if lane else {}
    out = io.StringIO()
    context.error = None
    with mock.patch.dict(os.environ, environment, clear=False), mock.patch.object(start, "run_procedure_request", run), \
            mock.patch("papyrus_content.site_selection.host_for", lambda endpoint=None: "mom"), \
            mock.patch.object(story_commands, "create_authoring_client", return_value=(context.client, None)), \
            mock.patch("papyrus_content.localize.record.collect", _collect(context)), \
            mock.patch("papyrus_content.story_reporting.published_story_version", lambda client, story: context.primary), redirect_stdout(out):
        if lane is None:
            os.environ.pop("PAPYRUS_GRAPHQL_AUTH", None)
        if key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        elif key:
            os.environ["OPENAI_API_KEY"] = key
        try:
            story_commands.stories_localize(["--story", STORY, "--language", "es-419"])
        except ValueError as error:
            context.error = str(error)
    context.output_lines = out.getvalue().splitlines()


@given("a site that registered the translation procedure under SITE.story-localize and has the language enabled")
def step_registered_site(context):
    context.client.tables.pop("LocalizationRequest", None)


@when('an operator signed in with AWS credentials runs "papyrus stories localize" for a published Story and the language, naming no automation')
def step_run_here(context):
    _run_here(context)


@then("the translation request is written first")
def step_request_first(context):
    assert context.runner_calls[0]["request_was_written"] and context.client.tables["LocalizationRequest"]["story-waymo#es-419"]["state"] == "wanted"


@then("the procedure runner's own code loads the registered procedure, records a ProcedureRun with its usage, cost and output, and runs it in a child process signed as the operator")
def step_runner_code(context):
    from papyrus_content.procedure_runner import execute_in_child

    (call,) = context.runner_calls
    assert call["request"]["procedureKey"] == "mom.story-localize", call["request"]
    assert call["request"]["input"]["story"] == STORY and call["request"]["input"]["language"] == "es-419"
    assert call["execute"] is execute_in_child
    assert call["environment"]["PAPYRUS_GRAPHQL_AUTH"] == "iam" and call["environment"]["PAPYRUS_GRAPHQL_ENDPOINT"] == context.client.endpoint


@then("the command waits and prints the run id, status, cost and the procedure's output")
def step_prints_run(context):
    (line,) = context.output_lines
    assert "run-9" in line and "completed" in line and "$0.02" in line and "saved" in line, line


@then("no Automation, monitor or router publication is needed")
def step_no_automation(context):
    assert not context.started and not context.client.tables.get("Automation")


@then("a failed run exits non-zero and the same command continues from the finished stages")
def step_failed_run(context):
    _run_here(context, run_status="failed")
    assert context.error and "run-9" in context.error and "failed" in context.error and "same command again" in context.error, context.error


@when('"papyrus stories localize" is run without an automation on the signed-in lane')
def step_signed_in_lane(context):
    context.client.tables.pop("LocalizationRequest", None)
    _run_here(context, lane="user")


@then("it refuses, naming the operator lane")
def step_refuses_lane(context):
    assert context.error and "--auth iam" in context.error, context.error
    assert not context.client.tables.get("LocalizationRequest") and not context.runner_calls


@then("when no model key is in the process and no key parameter is named it refuses, naming both ways to give one")
def step_refuses_key(context):
    _run_here(context, key=None)
    assert context.error and "OPENAI_API_KEY" in context.error and "--openai-key-parameter" in context.error, context.error
    assert not context.client.tables.get("LocalizationRequest")


@then("a procedure that is not registered is reported with the register command for its key")
def step_not_registered(context):
    _run_here(context, not_registered=True)
    assert context.error and "procedures register --file procedures/newsroom/story_localize.tac --key mom.story-localize" in context.error, context.error


# --- the front matter's reader-facing texts are translated with the title and the dek -------------------------------------------

@given("the English Story also has a blurb and a cover picture alt text")
def step_blurb_and_alt(context):
    front = f"title: {TITLE}\ndeck: {DECK}\nblurb: A short summary of the report.\nimageAlt: A white car on a road.\nimage: /assets/waymo/cover.png\nsources:\n- title: The report\n  url: https://example.test/report\n"
    context.primary["metadata"] = json.dumps({"frontMatterYaml": front})


@then("the version's blurb and cover picture alt text are the translated ones")
def step_translated_fields(context):
    import yaml

    front = yaml.safe_load(json.loads(_latest(context)["metadata"])["frontMatterYaml"])
    assert front["blurb"] == "Un breve resumen del informe." and front["imageAlt"] == "Un auto blanco en una carretera.", front


@then("its picture path and its references stay as written")
def step_fields_fixed(context):
    import yaml

    front = yaml.safe_load(json.loads(_latest(context)["metadata"])["frontMatterYaml"])
    assert front["image"] == "/assets/waymo/cover.png" and front["sources"] == [{"title": "The report", "url": "https://example.test/report"}], front


@given("the English Story is republished as version 4 while the version 3 run is translating")
def step_republished_mid_run(context):
    translate = context.models.translate

    def translate_then_republish(request):
        answer = translate(request)
        if not getattr(context, "republished_mid_run", False):
            context.republished_mid_run = True
            context.client.tables["Item"][context.primary["id"]]["versionState"] = "superseded"
            _publish(context, 4)
            desired_state.want(context.client, source=context.primary, language=context.language, requested_by="publish")
        return answer

    context.models.translate = translate_then_republish


@then('the request "{request_id}" still names source version {number:d} and is wanted')
def step_request_still_wanted(context, request_id, number):
    row = context.client.tables["LocalizationRequest"][request_id]
    assert row["sourceVersionNumber"] == number and row["state"] == "wanted", row


NOTE_BLOCK = ":::note\nOut of office.\n:::"
NOTE_SPANISH = ":::note\nFuera de la oficina.\n:::"


@given('the English Story has a note "{text}" between its paragraphs')
def step_note(context, text):
    assert text == "Out of office.", text
    context.paragraphs = [P1, NOTE_BLOCK, P2, IMAGE]
    context.translations[NOTE_BLOCK] = NOTE_SPANISH
    _publish(context, 3)


@given('the translator adds the paragraph "{text}" inside the note')
def step_invented(context, text):
    context.invented = text
    context.translations[NOTE_BLOCK] = NOTE_SPANISH.replace("\n:::", f"\n\n{text}\n:::")


@given("the repairer deletes any paragraph that is not in the English")
def step_repairer_deletes(context):
    context.repair = lambda text: NOTE_SPANISH if text.startswith(":::note") else text


@then("the repairer was asked about the note only, with the invented paragraph named as a problem")
def step_asked_note(context):
    blocks = [block for request in context.models.refine_requests for block in request["blocks"]]
    assert blocks and all(block["source"].startswith(":::note") for block in blocks), blocks
    assert any(context.invented in problem for block in blocks for problem in block["problems"]), blocks


@then("the saved translation has the note without the invented paragraph")
def step_note_clean(context):
    body = _latest(context)["bodyMarkus"]
    assert NOTE_SPANISH in body and context.invented not in body, body


@then("the held reason names the structure difference")
def step_held_structure(context):
    assert "structure" in context.output["reason"], context.output["reason"]


@given("the block check does not see the structure inside a note, so only the check of the whole body does")
def step_blind(context):
    context.blind_note_structure = True
