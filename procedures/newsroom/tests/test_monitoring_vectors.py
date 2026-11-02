"""The router's daily vector pass (src/papyrus_content/monitoring_vectors.py, features_backend/monitoring-vector-pass.feature): index sync, then suggestions,
then packs and single items. The index, the embeddings, the S3 Vectors client and the backends are fakes; nothing here reaches the network."""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from contextlib import redirect_stdout
from functools import partial
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_monitoring_router as tr  # noqa: E402
import test_monitoring_stories as tms  # noqa: E402
from field_recorder import FieldRecorder  # noqa: E402
from fake_idea_store import FakeIdeaStore  # noqa: E402
from ideas_fixtures import NOW  # noqa: E402
from test_monitor_stories import StoryModel, pages, world  # noqa: E402
from papyrus_content import monitoring_vectors as vectors  # noqa: E402
from papyrus_content.monitoring_router import run_router, validate_router_config  # noqa: E402
from papyrus_content.monitoring_stories import run_publication, validate_monitor_stories  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ARN = "arn:aws:s3vectors:us-east-1:712236451410:bucket/site-vectors/index/site-index"
BUCKET = "site-storage-bucket"
POLICY = {"vectorIndexArn": ARN, "storageBucketName": BUCKET, "suggestions": {"enabled": True}}
PUBLICATION = {"publicationId": "example-site", "corpusId": "knowledge-corpus-example-site", "appsyncEndpoint": tr.ENDPOINT}
RUN_AT = NOW


@pytest.fixture(autouse=True)
def iam_auth(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")


@pytest.fixture(autouse=True)
def runtime_has_s3vectors(monkeypatch):
    monkeypatch.setattr(vectors, "s3vectors_client_missing_reason", lambda region_name=None: None)


def accepted(number: int, at: str) -> dict:
    return {"id": f"ref-{number}", "lineageId": f"lineage-{number}", "versionState": "current", "curationStatus": "accepted", "curationStatusUpdatedAt": at}


class AcceptedClient:
    def __init__(self, rows):
        self.rows = rows
        self.asked = []

    def list_by_index(self, index_name, key_value, *, limit=100):
        self.asked.append((index_name, key_value))
        return list(self.rows)


class Watermark:
    def __init__(self, value=None):
        self.value, self.writes = value, []

    def read(self):
        return self.value

    def write(self, value):
        self.value = value
        self.writes.append(value)


class Pass:
    """Records the order of the steps and what each was given."""

    def __init__(self, *, characters=0, cards=0, written=0, stop_after=None, fail_index=None):
        self.order, self.options, self.suggested = [], None, []
        self.characters, self.cards, self.written, self.fail_index, self.stop_after = characters, cards, written, fail_index, stop_after
        self.stats_seen = []

    def indexer(self, services, options):
        self.order.append("index")
        self.options = options
        if self.fail_index:
            raise RuntimeError(self.fail_index)
        stats = {"vectorsWritten": self.written + self.cards, "conceptCardsToWrite": self.cards, "embeddingInputCharacters": self.characters}
        if options.stop_check:
            reason = options.stop_check(stats)
            if reason:
                stats["stoppedBy"] = reason
        return stats

    def suggester(self, client, provider, reference_id, **options):
        self.order.append(f"suggest:{reference_id}")
        self.suggested.append((reference_id, options))
        return {"referenceId": reference_id, "skipped": None, "references": [{"outcome": "created"}, {"outcome": "kept"}], "concepts": [{"outcome": "updated"}]}


def run_pass(client, pass_, watermark, *, policy=None, key="sk-test", out_of_time=lambda: False, maximum_cost_usd=0.5):
    return vectors.run_vector_pass(
        client, PUBLICATION, {**POLICY, **(policy or {})}, now=RUN_AT, out_of_time=out_of_time, maximum_cost_usd=maximum_cost_usd, embedding_key=key,
        read_watermark=watermark.read, write_watermark=watermark.write, services_for=lambda publication, bucket: ("services", bucket),
        indexer=pass_.indexer, suggester=pass_.suggester, provider_for=lambda arn: ("provider", arn), calibration_loader=lambda client: "calibration")


# --- the settings ---------------------------------------------------------------------------------------------------------------------------


def test_the_vector_settings_default_to_suggestions_on_and_no_index_and_validate():
    normalized = validate_monitor_stories("p", None)
    assert normalized["suggestions"] == {"enabled": True} and normalized["vectorIndexArn"] is None and normalized["storageBucketName"] is None
    filled = validate_monitor_stories("p", {"vectorIndexArn": ARN, "storageBucketName": BUCKET, "suggestions": {"enabled": False}})
    assert filled["vectorIndexArn"] == ARN and filled["storageBucketName"] == BUCKET and filled["suggestions"] == {"enabled": False}
    assert validate_monitor_stories("p", filled) == filled
    for bad in ({"vectorIndexArn": "arn:aws:s3:::a-bucket"}, {"vectorIndexArn": 3}, {"storageBucketName": "Not A Bucket"}, {"suggestions": {"enabled": "yes"}},
                {"suggestions": {"limit": 3}}, {"suggestions": True}):
        with pytest.raises(ValueError):
            validate_monitor_stories("p", bad)


def seed_module():
    spec = importlib.util.spec_from_file_location("seed_router_config", ROOT / "infra/monitoring/seed_router_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def amplify_outputs(arn=ARN, bucket=BUCKET):
    return {"custom": {"knowledgeQuery": {"s3VectorIndexArn": arn}}, "storage": {"bucket_name": bucket}}


def test_seeding_reads_the_index_arn_and_the_bucket_from_each_sites_amplify_outputs():
    seed = seed_module()
    config = json.loads((ROOT / "docs/monitoring-router-config.example.json").read_text())
    config["publications"][0]["monitorStories"] = {"singleItem": False}
    filled = seed.fill_vector_settings(config, {"anth-us": amplify_outputs(), "threat-intelligence": amplify_outputs(ARN.replace("site-index", "other"), "other-bucket")})
    first, second, third = (entry["monitorStories"] for entry in filled["publications"])
    assert first == {"singleItem": False, "vectorIndexArn": ARN, "storageBucketName": BUCKET}   # what the entry already said is kept
    assert third["vectorIndexArn"].endswith("index/other") and third["storageBucketName"] == "other-bucket"
    assert second["vectorIndexArn"] != ARN   # p-apyr-us was not named: its entry is untouched
    publications = validate_router_config(filled)["publications"]
    assert publications[0]["monitorStories"]["vectorIndexArn"] == ARN
    assert config["publications"][0]["monitorStories"] == {"singleItem": False}   # the input is not changed


def test_seeding_refuses_outputs_without_an_index_or_a_bucket_and_publications_that_are_not_in_the_config():
    seed = seed_module()
    config = json.loads((ROOT / "docs/monitoring-router-config.example.json").read_text())
    with pytest.raises(ValueError, match="s3VectorIndexArn"):
        seed.fill_vector_settings(config, {"anth-us": {"custom": {}, "storage": {"bucket_name": BUCKET}}})
    with pytest.raises(ValueError, match="bucket_name"):
        seed.fill_vector_settings(config, {"anth-us": {"custom": {"knowledgeQuery": {"s3VectorIndexArn": ARN}}}})
    with pytest.raises(ValueError, match="not in the config"):
        seed.fill_vector_settings(config, {"nowhere": amplify_outputs()})


# --- the pass: order, watermark, bounds -----------------------------------------------------------------------------------------------------


def test_the_index_is_synced_for_the_newly_accepted_references_then_each_gets_suggestions_and_the_watermark_moves():
    client = AcceptedClient([accepted(1, "2026-10-30T10:00:00Z"), accepted(2, "2026-10-31T10:00:00Z"), accepted(3, "2026-10-29T10:00:00Z")])
    pass_, watermark = Pass(characters=4_000_000, cards=2, written=5), Watermark("2026-10-29T12:00:00Z")
    result = run_pass(client, pass_, watermark)
    assert client.asked == [("referencesByCurationStatusKey", "knowledge-corpus-example-site#accepted")]
    assert pass_.options.action == "sync" and pass_.options.reference_ids == ("ref-1", "ref-2") and not pass_.options.skip_references   # ref-3 was accepted before the last pass
    assert pass_.options.include_concept_cards and not pass_.options.include_ontology_vectors
    assert pass_.order == ["index", "suggest:ref-1", "suggest:ref-2"]   # the index first; the oldest acceptance first
    assert all(options["calibration"] == "calibration" and options["corpus_id"] == "knowledge-corpus-example-site" and "cut" not in options for _, options in pass_.suggested)
    assert (result["indexed"], result["conceptCardsWritten"], result["suggestionsWritten"], result["suggestionsSkippedReason"]) == (5, 2, 4, None)
    assert watermark.writes == ["2026-10-31T10:00:00Z"]
    assert result["costUsd"] == pytest.approx(0.02)   # 4,000,000 characters at 4 per token, $0.02 per million tokens


def test_the_first_pass_takes_every_accepted_reference_and_a_pass_with_nothing_new_still_syncs_the_concept_cards():
    client = AcceptedClient([accepted(1, "2026-10-30T10:00:00Z")])
    watermark = Watermark()
    run_pass(client, Pass(), watermark)
    assert watermark.value == "2026-10-30T10:00:00Z"
    quiet = Pass(cards=1)
    result = run_pass(client, quiet, watermark)
    assert quiet.options.skip_references and quiet.options.reference_ids == () and quiet.order == ["index"]
    assert result["conceptCardsWritten"] == 1 and result["suggestionsWritten"] == 0 and result["newlyAccepted"] == 0


def test_a_version_that_is_not_current_is_not_a_new_acceptance():
    client = AcceptedClient([{**accepted(1, "2026-10-30T10:00:00Z"), "versionState": "superseded"}, accepted(2, "2026-10-30T11:00:00Z")])
    pass_ = Pass()
    run_pass(client, pass_, Watermark())
    assert pass_.options.reference_ids == ("ref-2",)


def test_without_an_index_arn_the_pass_does_nothing_and_says_why():
    pass_, watermark = Pass(), Watermark()
    result = run_pass(AcceptedClient([accepted(1, "2026-10-30T10:00:00Z")]), pass_, watermark, policy={"vectorIndexArn": None})
    assert pass_.order == [] and watermark.writes == []
    assert result["suggestionsSkippedReason"] == "no vectorIndexArn in the publication's monitorStories" and result["indexSkippedReason"] == result["suggestionsSkippedReason"]
    assert (result["indexed"], result["conceptCardsWritten"], result["suggestionsWritten"]) == (0, 0, 0)


def test_a_runtime_whose_boto3_has_no_s3vectors_client_skips_the_pass_and_says_so(monkeypatch):
    monkeypatch.setattr(vectors, "s3vectors_client_missing_reason", lambda region_name=None: "the runtime's boto3 has no usable s3vectors client (UnknownServiceError)")
    pass_ = Pass()
    result = run_pass(AcceptedClient([accepted(1, "2026-10-30T10:00:00Z")]), pass_, Watermark())
    assert pass_.order == [] and "no usable s3vectors client" in result["suggestionsSkippedReason"]


def test_suggestions_can_be_turned_off_and_the_index_is_still_kept_current():
    pass_, watermark = Pass(), Watermark()
    result = run_pass(AcceptedClient([accepted(1, "2026-10-30T10:00:00Z")]), pass_, watermark, policy={"suggestions": {"enabled": False}})
    assert pass_.order == ["index"] and result["suggestionsSkippedReason"] == "suggestions are off in the publication's monitorStories"
    assert watermark.writes == ["2026-10-30T10:00:00Z"]


def test_without_the_openai_key_the_index_is_skipped_with_a_reason_the_watermark_stays_and_suggestions_still_use_the_vectors_that_exist():
    pass_, watermark = Pass(), Watermark()
    result = run_pass(AcceptedClient([accepted(1, "2026-10-30T10:00:00Z")]), pass_, watermark, key=None)
    assert result["indexSkippedReason"] == "openai_not_configured" and pass_.order == ["suggest:ref-1"] and watermark.writes == []


def test_a_failing_index_sync_is_reported_and_leaves_the_watermark_so_the_next_pass_takes_the_same_references():
    pass_, watermark = Pass(fail_index="throttled"), Watermark()
    result = run_pass(AcceptedClient([accepted(1, "2026-10-30T10:00:00Z")]), pass_, watermark)
    assert "index sync failed (RuntimeError: throttled)" in result["indexSkippedReason"] and watermark.writes == []
    assert pass_.order == ["index", "suggest:ref-1"] and result["suggestionsWritten"] == 2   # suggestions still use whatever vectors exist


def test_the_embedding_cost_stops_the_index_at_the_cost_bound_and_nothing_after_it_runs():
    pass_, watermark = Pass(characters=400_000_000), Watermark()   # $2 of embeddings against a $0.50 bound
    result = run_pass(AcceptedClient([accepted(1, "2026-10-30T10:00:00Z")]), pass_, watermark)
    assert result["stoppedBy"] == "cost" and pass_.order == ["index"] and watermark.writes == []
    assert result["suggestionsSkippedReason"] == "stopped by cost while indexing"


def test_running_out_of_time_stops_the_index_and_the_suggestions_and_keeps_the_watermark():
    pass_, watermark = Pass(), Watermark()
    result = run_pass(AcceptedClient([accepted(1, "2026-10-30T10:00:00Z")]), pass_, watermark, out_of_time=lambda: True)
    assert result["stoppedBy"] == "time" and watermark.writes == []
    steps = Pass()
    ticks = iter([False, False, True])
    result = run_pass(AcceptedClient([accepted(1, "2026-10-30T10:00:00Z"), accepted(2, "2026-10-30T11:00:00Z"), accepted(3, "2026-10-30T12:00:00Z")]), steps, Watermark(),
                      out_of_time=lambda: next(ticks, True))
    assert steps.order == ["index", "suggest:ref-1"] and result["stoppedBy"] == "time"   # index check passed, ref-1 suggested, then the time was gone


def test_one_reference_whose_suggestions_fail_does_not_stop_the_others():
    class Flaky(Pass):
        def suggester(self, client, provider, reference_id, **options):
            if reference_id == "ref-1":
                raise ValueError("Reference not found")
            return super().suggester(client, provider, reference_id, **options)

    pass_ = Flaky()
    result = run_pass(AcceptedClient([accepted(1, "2026-10-30T10:00:00Z"), accepted(2, "2026-10-30T11:00:00Z")]), pass_, Watermark())
    assert pass_.order == ["index", "suggest:ref-2"] and result["suggestionsFailed"] == 1 and result["suggestionsWritten"] == 2


def test_the_embedding_key_and_the_index_arn_are_in_the_environment_only_while_the_index_runs(monkeypatch):
    import os

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PAPYRUS_S3_VECTOR_INDEX_ARN", raising=False)
    seen = {}

    class Seeing(Pass):
        def indexer(self, services, options):
            seen.update(key=os.environ.get("OPENAI_API_KEY"), arn=os.environ.get("PAPYRUS_S3_VECTOR_INDEX_ARN"), services=services)
            return super().indexer(services, options)

    run_pass(AcceptedClient([accepted(1, "2026-10-30T10:00:00Z")]), Seeing(), Watermark())
    assert seen == {"key": "sk-test", "arn": ARN, "services": ("services", BUCKET)}
    assert "OPENAI_API_KEY" not in os.environ and "PAPYRUS_S3_VECTOR_INDEX_ARN" not in os.environ


def test_the_index_sync_stops_between_references_when_asked_and_does_not_start_the_concept_cards():
    from papyrus_knowledge_query import vector_index
    from papyrus_knowledge_query.services import KnowledgeQueryServices

    references = [{"id": f"r{n}", "lineageId": f"l{n}", "versionState": "current", "curationStatus": "accepted"} for n in range(1, 4)]
    prepared = []

    def prepare(services, reference, options):
        prepared.append(reference["id"])
        return {"referenceId": reference["id"], "status": "prepared", "candidates": [{"key": f"k-{reference['id']}", "text": "x" * 100, "metadata": {"vectorKind": "reference_passage"}}]}

    cards = mock.Mock(return_value=[])
    with mock.patch.dict("os.environ", {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:fake"}), \
            mock.patch.object(vector_index, "_list_references", return_value=references), mock.patch.object(vector_index, "_list_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_prepare_note_messages", return_value=[]), mock.patch.object(vector_index, "_list_index_vectors", return_value=[]), \
            mock.patch.object(vector_index, "_prepare_reference_for_indexing", side_effect=prepare), mock.patch.object(vector_index, "_prepare_concept_card_vectors", cards), \
            mock.patch.object(vector_index, "_embed_and_put_vectors", side_effect=lambda arn, candidates: len(candidates)):
        services = KnowledgeQueryServices(graph=mock.Mock(), corpus_text=object())
        stats = vector_index.index_reference_passages(services, vector_index.VectorIndexOptions(action="sync", worker_count=1, include_ontology_vectors=False,
                                                                                               stop_check=lambda stats: "time" if len(stats["referenceResults"]) >= 2 else None))
        assert stats["stoppedBy"] == "time" and prepared == ["r1", "r2"] and stats["vectorsWritten"] == 2 and not cards.called
        prepared.clear()
        stats = vector_index.index_reference_passages(services, vector_index.VectorIndexOptions(action="sync", worker_count=1, include_ontology_vectors=False, skip_references=True))
        assert prepared == [] and cards.called and "stoppedBy" not in stats


# --- the router: the order in a run, the log line, the stored watermark ---------------------------------------------------------------------------


def router_with(settings):
    table, store = tms.router(settings={tms.PUBLICATION: settings})
    return table, store


def run_task(store, client, order, monkeypatch, *, key="sk-test", accepted_rows=None):
    pass_ = Pass(characters=400_000, cards=1, written=3)
    monkeypatch.setattr("papyrus_content.monitoring_vectors.accepted_since", lambda c, p, watermark: accepted_rows or [])
    monkeypatch.setattr("papyrus_content.monitoring_vectors.run_vector_pass", partial(
        vectors.run_vector_pass, services_for=lambda publication, bucket: object(), indexer=lambda services, options: (order.append("index"), pass_.indexer(services, options))[1],
        suggester=lambda c, provider, reference_id, **options: (order.append("suggest"), pass_.suggester(c, provider, reference_id, **options))[1],
        provider_for=lambda arn: object(), calibration_loader=lambda c: None))
    model = StoryModel()
    endpoints = {tr.ENDPOINT.replace("abc123", "api0"): client}
    out = io.StringIO()

    from papyrus_content.ideas import monitor_stories

    real_drafting = monitor_stories.draft_monitor_stories
    monkeypatch.setattr(monitor_stories, "draft_monitor_stories", lambda **options: (order.append("drafting"), real_drafting(**options))[1])
    draft = partial(run_publication, fetch=pages(*range(1, 60)), explorer=None)

    with redirect_stdout(out):
        result = run_router(store, "hn", now=NOW.timestamp(), task="monitor-stories", appsync=lambda endpoint: endpoints[endpoint], deliver=tr.Delivery(),
                            story_transport=model, story_drafter=draft, embedding_key=key)
    line = next(json.loads(text) for text in out.getvalue().splitlines() if text.startswith('{"monitorStories"'))
    return result, line, pass_


@pytest.fixture
def idea_sink(monkeypatch):
    monkeypatch.setattr("papyrus_content.ideas.items.ItemStore", lambda client, **options: FakeIdeaStore(client, gate=options.get("gate")))
    from test_idea_items import FakeGate
    monkeypatch.setattr("papyrus_content.ideas.gate.HumanusGate.for_client", classmethod(lambda cls, client, **options: FakeGate()))


def test_a_router_run_syncs_the_index_then_suggests_then_drafts_and_the_log_line_names_each_count(idea_sink, monkeypatch):
    table, store = router_with({**tms.SINGLE_ITEM_ONLY, "vectorIndexArn": ARN, "storageBucketName": BUCKET})
    _, client = world(2)
    order = []
    result, line, _ = run_task(store, client, order, monkeypatch, accepted_rows=[accepted(1, "2026-10-30T10:00:00Z")])
    assert order == ["index", "suggest", "drafting"]
    assert (line["indexed"], line["conceptCardsWritten"], line["suggestionsWritten"], line["suggestionsSkippedReason"]) == (3, 1, 2, None)
    assert line["drafted"] == 2 and line["costUsd"] >= 0.002   # the model's spend and the embeddings (400,000 characters) share one meter
    stored = table.get_item({"pk": "MONITOR#hn", "sk": vectors.watermark_sort_key(tms.PUBLICATION)})["Item"]
    assert stored["watermark"] == "2026-10-30T10:00:00Z"
    assert result["monitorStories"][tms.PUBLICATION]["indexed"] == 3


def test_a_run_without_an_index_arn_still_drafts_and_logs_the_reason_suggestions_are_off(idea_sink):
    table, store = router_with(tms.SINGLE_ITEM_ONLY)
    _, client = world(2)
    result, lines = tms.run_task(store, {tms.PUBLICATION: client}, StoryModel())
    line = lines[tms.PUBLICATION]
    assert line["drafted"] == 2
    assert (line["indexed"], line["conceptCardsWritten"], line["suggestionsWritten"]) == (0, 0, 0)
    assert line["suggestionsSkippedReason"] == "no vectorIndexArn in the publication's monitorStories"
    assert table.get_item({"pk": "MONITOR#hn", "sk": vectors.watermark_sort_key(tms.PUBLICATION)}).get("Item") is None


def test_the_log_line_of_a_publication_that_was_skipped_or_disabled_carries_the_vector_fields_too(idea_sink):
    table, store = router_with({"enabled": False})
    _, client = world(1)
    _, lines = tms.run_task(store, {tms.PUBLICATION: client}, StoryModel())
    assert lines[tms.PUBLICATION]["status"] == "disabled" and lines[tms.PUBLICATION]["suggestionsSkippedReason"] is None and lines[tms.PUBLICATION]["indexed"] == 0


# --- IAM -------------------------------------------------------------------------------------------------------------------------------------


SITES = ("AnthUs", "Papyrus", "ThreatIntel", "DataParade", "Pilobolus", "Shipped", "Distinctive", "MachinesOnMachines")


def idea_policy_text():
    text = (ROOT / "infra" / "monitoring" / "papyrus-monitoring.yaml").read_text()
    start = text.index("  RouterIdeaPolicy:")
    return text, text[start:text.index("\n\n  ", start)]


def test_the_idea_policy_grants_the_s3_vectors_actions_on_the_eight_indexes_and_reads_the_eight_buckets_and_no_policy_was_added():
    text, policy = idea_policy_text()
    block = policy[policy.index("Sid: SiteVectorIndexes"):policy.index("Sid: ReadEditorialJudgmentKey")]
    for action in ("s3vectors:GetVectors", "s3vectors:QueryVectors", "s3vectors:PutVectors", "s3vectors:ListVectors"):
        assert action in block
    assert "s3vectors:DeleteVectors" not in block and "s3vectors:*" not in block
    for site in SITES:
        assert f"- !Ref {site}VectorIndexArn" in block, site
        assert f'arn:${{AWS::Partition}}:s3:::${{{site}StorageBucketName}}/*' in block, site
        for parameter, default in ((f"{site}VectorIndexArn", "unset-vector-index"), (f"{site}StorageBucketName", "unset-storage-bucket")):
            declared = text[text.index(f"\n  {parameter}:\n"):]
            assert default in declared[:declared.index("Description")], parameter   # the default names nothing, so an unfilled parameter grants nothing real
    assert "Resource: '*'" not in block and 's3:::*' not in block
    assert "Roles: [!Ref RouterRole]" in policy


def test_every_graphql_field_the_sync_and_the_suggestions_ask_for_is_granted_by_the_idea_policy():
    """Records the fields the real client and the knowledge-query provider would ask a publication's API for, then checks the one policy grants them."""
    from papyrus_content.reference_suggestions import suggest_for
    from papyrus_content.suggestion_calibration import load_calibration
    from papyrus_knowledge_query import vector_index
    from papyrus_knowledge_query.services import KnowledgeQueryServices
    from test_reference_suggestions import FakeVectorProvider, build

    inner, provider = build()
    inner.tables["SemanticNode"] = {"node-voice-v1": {"id": "node-voice-v1", "lineageId": "node-voice", "versionNumber": 1}}
    original_get = inner.get_record
    inner.get_record = lambda model, record_id: inner.tables.get(model, {}).get(record_id) if model != "SemanticNode" else {"id": "node-voice-v1", "lineageId": "node-voice", "versionNumber": 1}
    original_list = inner.list_by_index
    inner.list_by_index = lambda index, key, **kw: [] if index == "semanticRelationsByNewsroomFeedAndCreatedAt" else original_list(index, key, **kw)
    recorder = FieldRecorder(inner)
    for _ in range(2):   # the second pass finds the edge already written and updates it
        suggest_for(recorder, provider, "reference-a-v1", corpus_id="corpus-1", calibration=load_calibration(recorder), now="2026-11-01T12:00:00Z")
    recorded = set(recorder.fields)
    assert {("Query", "listReferencesByLineageAndVersion"), ("Mutation", "createSemanticRelation"), ("Query", "listSemanticRelationsByNewsroomFeedAndCreatedAt")} <= recorded | {
        ("Query", "listReferencesByLineageAndVersion")}

    asked = []

    class Graph:
        def graphql(self, query, variables):
            asked.extend(("Query", name) for name in re.findall(r"\b((?:list|get)[A-Z]\w+)\(", query))
            return {}

        def list_reference_attachments(self, reference):
            asked.append(("Query", "listReferenceAttachmentsByReferenceLineageAndSortKey"))
            return []

        def list_outgoing_relations_batch(self, objects):
            asked.append(("Query", "listSemanticRelationsBySubjectState"))
            return {}

        def list_outgoing_relations(self, obj, *a, **k):
            asked.append(("Query", "listSemanticRelationsBySubjectState"))
            return []

    with mock.patch.dict("os.environ", {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:fake"}), mock.patch.object(vector_index, "_list_index_vectors", return_value=[]), \
            mock.patch.object(vector_index, "_prepare_ontology_vectors", return_value=[]), mock.patch.object(vector_index, "_embed_and_put_vectors", return_value=0):
        vector_index.index_reference_passages(KnowledgeQueryServices(graph=Graph(), corpus_text=object()), vector_index.VectorIndexOptions(action="sync", include_ontology_vectors=False))
    recorded |= set(asked)
    assert {("Query", "listReferences"), ("Query", "listMessagesByKindAndCreatedAt"), ("Query", "listSemanticNodes")} <= recorded

    note = {"id": "m1", "messageKind": "note", "messageDomain": "knowledge", "status": "active", "createdAt": "2026-11-01T00:00:00Z"}
    batch = vector_index.LIST_MODEL_ATTACHMENTS_BY_OWNER_QUERY
    recorded |= {("Query", name) for name in re.findall(r"\b((?:list|get)[A-Z]\w+)\(", batch)}
    granted = {(kind, name) for kind, name in re.findall(r"apis/\*/types/(Query|Mutation)/fields/(\w+)\"", idea_policy_text()[1])}
    assert note and recorded <= granted | {("Query", "getReference")}, sorted(recorded - granted)


# --- packaging ---------------------------------------------------------------------------------------------------------------------------------


def load_build():
    spec = importlib.util.spec_from_file_location("monitoring_build", ROOT / "infra/monitoring/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    return build


def test_the_router_zip_closure_carries_the_vector_pass_and_the_knowledge_query_package_and_they_import_with_the_standard_library_and_pyyaml(tmp_path):
    """The closure the zip holds (no wheels: those are fetched for the Lambda and need the network) imports in an isolated interpreter that has no boto3."""
    import shutil
    import subprocess

    import yaml

    build = load_build()
    modules = build.router_modules()
    needed = ["monitoring_vectors", "reference_suggestions", "suggestion_calibration", "reference_links", "knowledge_snapshot/keys", "knowledge_wiki/pages", "corpus_storage_paths"]
    assert set(needed) <= set(modules), sorted(set(needed) - set(modules))
    files = build.knowledge_query_files()
    assert set(files) == {f"papyrus_knowledge_query/{name}.py" for name in ("__init__", "engine", "ranking", "services", "tokens", "uris", "vector_index")}
    assert sum(len(data) for data in files.values()) < 1_000_000   # source only: far below the zip's bound
    task = tmp_path / "task"
    for name in ["__init__", *modules]:
        target = task / "papyrus_content" / f"{name}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "src" / "papyrus_content" / f"{name}.py", target)
    for name, data in files.items():
        target = task / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    shutil.copytree(Path(yaml.__file__).parent, task / "yaml")
    script = ("import sys; sys.path.insert(0, sys.argv[1])\n"
              "from papyrus_content import monitoring_vectors, reference_suggestions, suggestion_calibration\n"
              "from papyrus_knowledge_query import vector_index\n"
              "from papyrus_knowledge_query.services import S3VectorsProvider, S3CorpusTextProvider, GraphQLKnowledgeGraphProvider\n"
              "assert vector_index.VectorIndexOptions(stop_check=None).action == 'sync'\n"
              "assert not any(m in sys.modules for m in ('pydantic', 'biblicus', 'httpx', 'tiktoken', 'boto3'))\n")
    done = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(task)], capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr[-1200:]
