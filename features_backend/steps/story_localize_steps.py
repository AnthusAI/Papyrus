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
        return {"blocks": [{"id": block["id"], "text": table.get(block["text"], block["text"])} for block in request["blocks"]]}

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
    def collect(client, *, story, language, judge, procedure_version, ceiling_usd=None, decision_model=None):
        source = localize_record.source_version(context.primary, "en")
        lineage = f"{story}--{language}"
        current, previous = localize_record.previous_alignment(client, lineage)
        glossary = starter_glossary(language)
        checker = BlockChecker(source_language="en", target_language=language, glossary=glossary, copy_edit_pack=starter_pack(language), judge=judge,
                               lanes={"rules": True, "classifier": False})
        english = BlockChecker(source_language="en", target_language="en", glossary=glossary, copy_edit_pack=starter_pack("en"), judge=None,
                               lanes={"rules": True, "classifier": False})
        key = localize_record.run_key(source, language, procedure_version=procedure_version, checker_versions=checker.versions)
        return LocalizeRequest(source=source, language=language, localization_lineage=lineage, run_key=key, glossary=glossary, checker=checker,
                               previous=previous, ceiling_usd=context.ceiling, procedure_version=procedure_version,
                               source_checker=lambda text: english.copy_edit(text)[0])
    return collect


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
