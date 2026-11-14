"""Steps and harness for the automatic Section of accepted References (docs/reference-auto-section.md).

Everything is synthetic: an in-memory data client, a scripted decision model (no live model call, no key), a local folder for the bucket, and a
proof report written to a temporary file. The fake site function applies the automatic lane's ownership rule the same way the real one does
(``person_owns_section``); the real function is covered by ``scripts/test-reference-section.ts``.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from features_backend.steps.cyclotron_relevance_sweep_steps import CORPUS_ID, DOCTRINE, LocalBucket, SweepClient, reference  # noqa: E402
from papyrus_content.steering import load_steering_config  # noqa: E402

PUBLICATION = "machines-on-machines"
SECURITY, MUSIC, ART = f"{PUBLICATION}#security", f"{PUBLICATION}#music", f"{PUBLICATION}#art"
PROOF_MODEL = "scripted-auto-section"
NOW = "2026-11-13T10:00:00Z"


def section(section_id: str, order: int, enabled: bool = True) -> dict:
    slug = section_id.split("#")[-1]
    return {"id": section_id, "title": slug.title(), "shortTitle": slug, "type": "canonical", "editorialMission": f"Stories about {slug}",
            "editorialPolicy": f"Primary sources about {slug}", "assignmentGuidance": None, "killCriteria": None, "enabled": enabled,
            "enabledStatus": "enabled" if enabled else "disabled", "sortOrder": order}


SECTIONS = [section(SECURITY, 1), section(MUSIC, 2), section(ART, 3)]


class SlugModel:
    """Chooses the Section whose slug is a word of the item. "clearly" in the title makes it sure (0.95); otherwise it is unsure (0.55)."""

    model_identity = PROOF_MODEL

    def __init__(self):
        self.calls = 0

    async def classify_many(self, configs, target, training, **kwargs):
        from decision_flywheel.batched_classification import BatchedAnswers
        from decision_flywheel.models import DecisionResult

        self.calls += 1
        words = set(target.values["text"].lower().replace(",", " ").split())
        sure = 0.95 if "clearly" in words else 0.55
        answers = {}
        for classifier, config in configs.items():
            labels = list(config.task.labels)
            if "fits" in labels:
                fits = classifier.rsplit("-", 1)[-1] in words
                weights = {"fits": 0.9 if fits else 0.1, "does-not-fit": 0.1 if fits else 0.9}
                answers[classifier] = {"decision": DecisionResult("fits" if fits else "does-not-fit", weights)}
                continue
            label = next((candidate for candidate in labels if candidate.split("#")[-1] in words), labels[0])
            weights = {candidate: (sure if candidate == label else (1 - sure) / (len(labels) - 1)) for candidate in labels}
            answers[classifier] = {"decision": DecisionResult(label, weights)}
        return BatchedAnswers(answers, "scripted", {"input_tokens": 100, "output_tokens": 0}, 1)


class AutoSectionClient(SweepClient):
    """The sweep's fake client, plus the site function's two section lanes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.section_writes: list[dict] = []

    def graphql(self, query, variables=None):
        if "SetReferenceSectionAutomatically" not in query:
            return super().graphql(query, variables)
        from papyrus_content.site_auto_section import AUTO_SECTION_ACTOR, person_owns_section

        row = self.tables["Reference"][variables["referenceId"]]
        answer = {"ok": True, "referenceId": row["id"], "previousSectionId": row.get("curationSectionId"), "status": row.get("curationStatus")}
        if person_owns_section(row):
            return {"setReferenceSection": {**answer, "sectionId": row.get("curationSectionId"), "changed": False,
                                            "skipped": "a person set or cleared this section"}}
        row.update(curationSectionId=variables["sectionId"], curationSectionUpdatedBy=AUTO_SECTION_ACTOR, curationSectionActorKind="cyclotron",
                   curationSectionReason=variables["machineReason"], curationSectionDecisionRelationId=variables["decisionRelationId"],
                   curationSectionUpdatedAt=NOW, updatedAt=NOW)
        self.section_writes.append(dict(variables))
        return {"setReferenceSection": {**answer, "sectionId": variables["sectionId"], "changed": True, "actorKind": "cyclotron", "skipped": None}}


def accepted(lineage: str, title: str, *, medium: str | None = None, updated_at: str = "2026-11-10T00:00:00Z", **fields) -> dict:
    row = reference(lineage, title, "accepted")
    row.update(curationStatusUpdatedAt=updated_at, curationStatusUpdatedBy="editor@example.org", curationActorKind="human",
               updatedAt=updated_at, **({"medium": medium} if medium else {}), **fields)
    return row


def person_sets_section(client: AutoSectionClient, lineage: str, section_id: str | None) -> None:
    """What the site function leaves when a person sets (or, with None, clears) a Section."""
    client.tables["Reference"][f"{lineage}-v1"].update(curationSectionId=section_id, curationSectionUpdatedBy="editor@example.org",
                                                      curationSectionActorKind="human", curationSectionReason=None,
                                                      curationSectionDecisionRelationId=None, curationSectionUpdatedAt=NOW)


def proof_report(pairs: list[list], *, model: str = PROOF_MODEL) -> dict:
    return {"schema": "cyclotron-section-proof/v1", "proofId": "sections-test", "decisionModel": model, "dryRun": False,
            "selector": {"status": "proven", "calibration": {"schema": "cyclotron-section-calibration/v1", "arm": "withTeaching", "pairs": pairs}}}


#: Held-out evidence: the selector agreed with editors on all 40 sure decisions and on half of the 20 unsure ones, so 0.95 is learned.
CONFIDENT_PROOF = [[0.95, True]] * 40 + [[0.55, True]] * 10 + [[0.55, False]] * 10


def steering_for(root: Path, *, proof: dict | None = None, auto_section: dict | None = None):
    policy = dict(auto_section or {})
    if proof is not None:
        path = root / "section-proof.json"
        path.write_text(json.dumps(proof), encoding="utf-8")
        policy.setdefault("proofPath", str(path))
    raw = {
        "schemaVersion": 1, "publication": {"name": "Example"},
        "canonicalTopicSet": {"corpusKey": "example", "classifierId": "example"},
        "corpora": [{"key": "example", "name": "example", "path": "corpora/example", "role": "canonical"}],
        "relevanceCyclotron": {"optimizer": None},
        "siteCyclotron": {"store": {"localPath": str(root / "site-cyclotron"), "s3Prefix": "s3://example-private-media/cyclotrons/sections/"},
                          **({"autoSection": policy} if policy else {})},
    }
    path = root / "steering.yml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_steering_config(str(path))


def run(client: AutoSectionClient, steering, root: Path, *, model=None, dry_run=False, scope="changed", sections=SECTIONS):
    from papyrus_content.site_auto_section import run_auto_section

    client._table("NewsroomSection").update({row["id"]: dict(row) for row in sections})
    with _patches(client):
        return run_auto_section(client, steering, DOCTRINE, sections, dry_run=dry_run, worker="worker-a", scope=scope,
                                model=model or SlugModel(), snapshots=LocalBucket(root / "bucket"), now=lambda: NOW)


def sweep(client: AutoSectionClient, steering, root: Path, *, model=None, sections=SECTIONS):
    from papyrus_content.site_sweep import run_decide_site_sections

    client._table("NewsroomSection").update({row["id"]: dict(row) for row in sections})
    with _patches(client):
        return run_decide_site_sections(client, steering, DOCTRINE, sections, apply=True, worker="worker-a", model=model or SlugModel(),
                                        snapshots=LocalBucket(root / "bucket"), now=lambda: NOW)


class _patches:
    def __init__(self, client):
        bodies = client.bodies

        def store_body(recording_client, attachment, body):
            recording_client.upsert("ModelAttachment", attachment)
            bodies[attachment["id"]] = body

        self.patches = [
            mock.patch("papyrus_content.site_auto_section.knowledge_corpus_id", return_value=CORPUS_ID),
            mock.patch("papyrus_content.site_sweep.knowledge_corpus_id", return_value=CORPUS_ID),
            mock.patch("papyrus_content.records.upload_attachment_body", side_effect=store_body),
            mock.patch("papyrus_content.assignments.upload_attachment_body", side_effect=store_body),
            mock.patch("papyrus_content.relevance_sweep.download_attachment_buffer",
                       side_effect=lambda recording_client, attachment: bodies.get(attachment["id"])),
        ]

    def __enter__(self):
        for patch in self.patches:
            patch.start()

    def __exit__(self, *exc):
        for patch in reversed(self.patches):
            patch.stop()


def _nonempty(tables: dict) -> dict:
    """The tables that hold rows (a read creates an empty table in the fake client)."""
    return copy.deepcopy({name: rows for name, rows in tables.items() if rows})


def row(client: AutoSectionClient, lineage: str) -> dict:
    return client.tables["Reference"][f"{lineage}-v1"]


# --- behave steps -------------------------------------------------------------------------------------------------------------------


def _root(context) -> Path:
    if not getattr(context, "auto_section_root", None):
        context.auto_section_tmp = tempfile.TemporaryDirectory()
        context.auto_section_root = Path(context.auto_section_tmp.name)
    return context.auto_section_root


def _client(context) -> AutoSectionClient:
    if not getattr(context, "auto_section_client", None):
        context.auto_section_client = AutoSectionClient({"Reference": []})
    return context.auto_section_client


@given("a Machines on Machines style site whose Sections are Security, Music and Art under prefixed ids")
def step_site(context):
    _root(context)
    _client(context)
    context.auto_section_model = SlugModel()


@given("an approved Section proof whose held-out selector decisions agree with editors when the selector is sure")
def step_proof(context):
    context.auto_section_steering = steering_for(_root(context), proof=proof_report(CONFIDENT_PROOF))


@given("the site has no approved Section proof")
def step_no_proof(context):
    context.auto_section_steering = steering_for(_root(context))


@given('an accepted video "{lineage}" titled "{title}" with no section')
def step_accepted_video(context, lineage, title):
    _client(context).upsert("Reference", accepted(lineage, title, medium="video"))


@given('an accepted Reference "{lineage}" titled "{title}" with no section')
def step_accepted(context, lineage, title):
    _client(context).upsert("Reference", accepted(lineage, title))


@given('an accepted Reference "{lineage}" titled "{title}" that a person put in "{section_id}"')
def step_person_section(context, lineage, title, section_id):
    _client(context).upsert("Reference", accepted(lineage, title))
    person_sets_section(_client(context), lineage, section_id)


@given('an accepted Reference "{lineage}" titled "{title}" whose section a person cleared')
def step_person_cleared(context, lineage, title):
    _client(context).upsert("Reference", accepted(lineage, title))
    person_sets_section(_client(context), lineage, None)


@when("the automatic Section pass runs")
def step_run(context):
    context.auto_section_before_calls = context.auto_section_model.calls
    context.auto_section_result = run(_client(context), context.auto_section_steering, _root(context), model=context.auto_section_model)


@when("the automatic Section pass runs again over every accepted Reference")
def step_run_again(context):
    context.auto_section_writes_before = len(_client(context).section_writes)
    context.auto_section_relations_before = copy.deepcopy(_client(context).tables.get("SemanticRelation", {}))
    context.auto_section_before_calls = context.auto_section_model.calls
    context.auto_section_result = run(_client(context), context.auto_section_steering, _root(context), model=context.auto_section_model,
                                      scope="all")


@when("the automatic Section backfill runs as a dry run")
def step_dry_run(context):
    _client(context)._table("NewsroomSection").update({row["id"]: dict(row) for row in SECTIONS})
    context.auto_section_tables_before = _nonempty(_client(context).tables)
    context.auto_section_result = run(_client(context), context.auto_section_steering, _root(context), model=context.auto_section_model,
                                      dry_run=True, scope="all")


@when("the site sweep with automatic Sections runs")
def step_sweep(context):
    context.auto_section_sweep = sweep(_client(context), context.auto_section_steering, _root(context), model=context.auto_section_model)


@then('"{lineage}" is in the section "{section_id}"')
def step_in_section(context, lineage, section_id):
    assert row(_client(context), lineage).get("curationSectionId") == section_id, row(_client(context), lineage)


@then('"{lineage}" has no section')
def step_no_section(context, lineage):
    assert not row(_client(context), lineage).get("curationSectionId"), row(_client(context), lineage)


@then('the section of "{lineage}" was set by the machine, naming the selector decision, the model version and the learned threshold')
def step_machine_actor(context, lineage):
    current = row(_client(context), lineage)
    assert current["curationSectionActorKind"] == "cyclotron" and current["curationSectionUpdatedBy"] == "auto:cyclotron"
    relation = _client(context).tables["SemanticRelation"][current["curationSectionDecisionRelationId"]]
    assert relation["predicate"] == "site_decision_is" and relation["relationState"] == "current"
    reason = current["curationSectionReason"]
    assert f"model version {relation['modelVersion']}" in reason and "95.0% learned from 60 held-out editor Section choices" in reason, reason
    assert "An editor can change or clear it." in reason


@then('the result says "{lineage}" was left without a section because it is below the learned threshold')
def step_left(context, lineage):
    proposal = next(item for item in context.auto_section_result.proposals if item["lineageId"] == lineage)
    assert proposal["action"] == "leave" and "below the learned threshold" in proposal["reason"], proposal


@then('"{lineage}" was not a candidate because a person set or cleared its section')
def step_not_candidate(context, lineage):
    assert lineage not in {item["lineageId"] for item in context.auto_section_result.proposals}
    assert context.auto_section_result.skipped.get("a person set or cleared its section", 0) >= 1


@then("no section model was asked and nothing was decided")
def step_no_model(context):
    assert context.auto_section_model.calls == context.auto_section_before_calls
    assert context.auto_section_result.decided == 0


@then("the result says no Section is set until there is a learned threshold")
def step_no_threshold(context):
    result = context.auto_section_result
    assert result.stopped_because == "no learned threshold" and "no approved Section proof" in result.calibration["reason"]
    assert not result.proposals


@then("no new section decision or write is made")
def step_idempotent(context):
    client = _client(context)
    assert context.auto_section_result.decided == 0 and context.auto_section_model.calls == context.auto_section_before_calls
    assert len(client.section_writes) == context.auto_section_writes_before
    assert client.tables.get("SemanticRelation", {}) == context.auto_section_relations_before
    assert context.auto_section_result.counts.get("set", 0) == 0


@then('the dry run lists "{lineage}" for "{section_id}" with the model\'s confidence and the evidence')
def step_dry_listing(context, lineage, section_id):
    from papyrus_content.site_auto_section import format_lines

    proposal = next(item for item in context.auto_section_result.proposals if item["lineageId"] == lineage)
    assert proposal["action"] == "set" and proposal["sectionId"] == section_id and proposal["confidence"] == 0.95
    assert "held-out editor Section choices" in proposal["reason"]
    assert any(line.startswith(f"references\tauto-section\tset\t{lineage}\t{section_id}\t95.0%") for line in format_lines(context.auto_section_result))


@then("the dry run wrote nothing to the site and kept no cyclotron store")
def step_dry_nothing(context):
    assert _nonempty(_client(context).tables) == context.auto_section_tables_before
    assert not (_root(context) / "site-cyclotron").exists() and not (_root(context) / "bucket").exists()


@then('the sweep reports the automatic Section of "{lineage}"')
def step_sweep_reports(context, lineage):
    auto = context.auto_section_sweep.auto_section
    assert any(item["lineageId"] == lineage and item["action"] == "set" for item in auto["proposals"]), auto
