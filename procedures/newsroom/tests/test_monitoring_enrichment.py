"""Item enrichment before the decision: a collected item is curated once, the decide payload carries the result, delivery copies it.

No network, no AWS, no model: capture, summary and storage are fakes.
"""
from __future__ import annotations

import json

import pytest

from curation_support import MemoryClient, MemoryStore, Summarizer
from papyrus_content import monitoring_enrichment as me, monitoring_router as mr
from papyrus_content.reference_capture import Capture
from test_monitoring_router import ONE_FEED, PUBS, Delivery, collected_table, go, setup_router

ARTICLE = "# County adopts transit plan\n\n" + "The board voted on Tuesday to adopt the plan. " * 20
SUMMARY = "Transit plan adopted; phased bus and rail work begins with a regional grant."


class Capturer:
    """Stands in for `capture_source`: answers from a script, counts the calls."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, url, *, title="", explorer=None):
        self.calls.append(url)
        answer = self.answers[min(len(self.calls), len(self.answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer


def good(text=ARTICLE):
    return Capture(True, text=text, source_kind="html", content_type="text/html", via="direct", destination_url="https://example.org/alpha",
                   signals={"wordCount": len(text.split()), "endingPattern": "sentence_end"}, paper={"isPaper": False}, page={"title": "T"})


def failed(reason="blocked", transient=False):
    capture = Capture(False, reason)
    return capture if not transient else Capture(False, "timeout")


def enricher(*answers, summarizer="default", texts=None):
    return me.Enricher(texts=texts or me.MemoryTexts(), summarizer=Summarizer(SUMMARY) if summarizer == "default" else summarizer,
                       capture=Capturer(*answers))


@pytest.fixture
def table():
    return collected_table(ONE_FEED)


def posted_values(cyclotron):
    return [c[2]["payload"]["item"]["values"] for c in cyclotron.posts()]


def test_a_collected_item_is_enriched_before_it_is_posted_and_the_payload_carries_summary_and_body(table):
    store, cyclotron = setup_router(table)
    enrich = enricher(good())
    result = go(table, store, cyclotron, enricher=enrich)
    assert result["counts"]["enriched"] == 1 and result["counts"]["decided"] == 1
    assert len(enrich.capture.calls) == 1                       # once per item, not once per publication
    values = posted_values(cyclotron)
    assert len(values) == len(PUBS) and all(v == values[0] for v in values)
    assert set(values[0]) == {"title", "url", "source", "sourceItemUrl", "summary", "body", "text"}
    assert values[0]["summary"] == SUMMARY and values[0]["body"] == ARTICLE
    assert values[0]["text"] == f"Alpha source\nhttps://example.org/alpha\n\n{SUMMARY}\n\n{ARTICLE}"
    row = table.items[("MONITOR#hn", "ENRICH#101#000001")]
    assert row["final"] is True and row["status"] == "ready" and row["curation"]["summary"]["text"] == SUMMARY
    assert "text" not in row["curation"]["capture"] and row["textKey"] in enrich.texts.objects   # the body lives outside the table


def test_the_combined_request_carries_the_same_enriched_item(table):
    store, cyclotron = setup_router(table)
    cyclotron.combined_enabled = True
    go(table, store, cyclotron, enricher=enricher(good()))
    (_, _, body), = cyclotron.combined_calls[:1]
    assert body["payload"]["item"]["values"]["summary"] == SUMMARY and body["payload"]["item"]["values"]["body"] == ARTICLE


def test_nothing_is_posted_before_enrichment_was_attempted_and_a_rerun_does_not_enrich_again(table):
    store, cyclotron = setup_router(table)
    enrich = enricher(good())
    clock = iter([1e9, 10, 10, 10, 10])      # the sweep starts the item with time to spare; enrichment then finds the invocation nearly over
    out_of_time = go(table, store, cyclotron, enricher=enrich, time_left=lambda: next(clock))
    assert cyclotron.posts() == [] and enrich.capture.calls == [] and out_of_time["counts"]["enrichmentWaiting"] == 1
    go(table, store, cyclotron, now=3000, enricher=enrich)
    go(table, store, cyclotron, now=4000, enricher=enrich)
    assert len(enrich.capture.calls) == 1 and len(cyclotron.posts()) == len(PUBS)


def test_a_capture_failure_still_proceeds_to_the_decision_with_a_typed_status(table):
    store, cyclotron = setup_router(table)
    result = go(table, store, cyclotron, enricher=enricher(failed("blocked")))
    row = table.items[("MONITOR#hn", "ENRICH#101#000001")]
    assert row["status"] == "capture_failed" and row["final"] is True
    assert {k: v for k, v in row["curation"]["capture"].items() if k != "capturedAt"} == {"status": "failed", "reason": "blocked", "transient": False}
    assert row["curation"]["summary"] == {"status": "skipped", "reason": "no_text"}
    assert result["counts"]["decided"] == 1
    assert posted_values(cyclotron)[0] == {"title": "Alpha source", "url": "https://example.org/alpha", "source": "hacker-news",
                                           "sourceItemUrl": "https://news.ycombinator.com/item?id=101",
                                           "text": "Alpha source\nhttps://example.org/alpha"}


def test_an_unexpected_enrichment_bug_is_recorded_and_the_decision_proceeds(table):
    store, cyclotron = setup_router(table)
    go(table, store, cyclotron, enricher=enricher(RuntimeError("boom")))
    row = table.items[("MONITOR#hn", "ENRICH#101#000001")]
    assert row["status"] == "capture_failed" and row["errors"][0]["type"] == "RuntimeError"
    assert row["curation"]["capture"]["reason"] == "enrichment_error" and len(cyclotron.posts()) == len(PUBS)


def test_a_transient_failure_is_retried_on_later_runs_then_the_decision_goes_ahead(table):
    store, cyclotron = setup_router(table)
    enrich = enricher(failed(transient=True), failed(transient=True), failed(transient=True))
    go(table, store, cyclotron, now=2000, enricher=enrich)
    row = table.items[("MONITOR#hn", "ENRICH#101#000001")]
    assert row["final"] is False and row["nextAttemptAt"] == 2300 and cyclotron.posts() == []
    go(table, store, cyclotron, now=2100, enricher=enrich)                # still backing off: no new attempt
    assert len(enrich.capture.calls) == 1 and cyclotron.posts() == []
    go(table, store, cyclotron, now=2400, enricher=enrich)                # second attempt, still transient
    assert len(enrich.capture.calls) == 2 and cyclotron.posts() == []
    go(table, store, cyclotron, now=3200, enricher=enrich)                # third and last: final, and the decision proceeds
    row = table.items[("MONITOR#hn", "ENRICH#101#000001")]
    assert len(enrich.capture.calls) == me.MAX_ATTEMPTS and row["final"] is True and row["status"] == "capture_failed"
    assert row["curation"]["capture"]["reason"] == "timeout" and len(cyclotron.posts()) == len(PUBS)


def test_a_transient_failure_that_passes_gets_the_enriched_decision(table):
    store, cyclotron = setup_router(table)
    enrich = enricher(failed(transient=True), good())
    go(table, store, cyclotron, now=2000, enricher=enrich)
    go(table, store, cyclotron, now=2400, enricher=enrich)
    assert posted_values(cyclotron)[0]["body"] == ARTICLE


def test_a_missing_summarizer_is_a_degraded_status_not_a_stop(table):
    store, cyclotron = setup_router(table)
    go(table, store, cyclotron, enricher=enricher(good(), summarizer=None))
    row = table.items[("MONITOR#hn", "ENRICH#101#000001")]
    assert row["status"] == "degraded" and row["curation"]["summary"]["reason"] == "openai_not_configured"
    values = posted_values(cyclotron)[0]
    assert "summary" not in values and values["text"] == f"Alpha source\nhttps://example.org/alpha\n\n{ARTICLE}"


def test_a_paper_without_grobid_is_a_typed_skip():
    paper = Capture(True, text=ARTICLE, source_kind="pdf", signals={}, paper={"isPaper": True, "basis": ["arxiv"]}, page={}, pdf_bytes=b"%PDF")
    row = me.enrich_item(me.new_row("hn", {"sourceId": "1", "revision": 1, "canonicalUrl": "https://arxiv.org/abs/2601.01234"}),
                         {"sourceId": "1", "revision": 1, "title": "P", "canonicalUrl": "https://arxiv.org/abs/2601.01234"}, "hn",
                         enricher(paper), me.utc_now())
    assert row["curation"]["grobid"] == {"status": "skipped", "reason": "grobid_not_configured"} and row["status"] == "ready"


def test_the_router_counts_bodies_under_500_characters_without_gating_them(table):
    store, cyclotron = setup_router(table)
    short = go(table, store, cyclotron, enricher=enricher(good("A short blurb.")))
    assert short["counts"]["shortBodies"] == 1 and cyclotron.posts()      # counted, and the decision still goes ahead
    table2 = collected_table(ONE_FEED)
    store, cyclotron = setup_router(table2)
    assert go(table2, store, cyclotron, enricher=enricher(good()))["counts"]["shortBodies"] == 0


def test_the_capture_row_carries_the_full_text_url_the_text_came_from():
    capture = good()
    capture.full_text_url = "https://journal.example.org/paper.pdf"
    row = me.enrich_item(me.new_row("hn", {"sourceId": "1", "revision": 1, "canonicalUrl": "https://example.org/a"}),
                         {"sourceId": "1", "revision": 1, "title": "P", "canonicalUrl": "https://example.org/a"}, "hn",
                         enricher(capture), me.utc_now())
    assert row["curation"]["capture"]["fullTextUrl"] == "https://journal.example.org/paper.pdf"


def test_a_very_long_body_is_sent_whole_in_every_request(table):
    store, cyclotron = setup_router(table)
    huge = ("A sentence about transit that goes on and on. " * 5000)           # about 225 KB
    enrich = enricher(good(huge))
    go(table, store, cyclotron, enricher=enrich)
    assert cyclotron.posts()
    for values in posted_values(cyclotron):
        assert values["body"] == huge and values["text"].endswith(huge) and values["summary"] == SUMMARY
    assert "bodyTruncatedForLabLimit" not in table.items[("MONITOR#hn", "DISC#101#000001")]


def test_validation_accepts_the_enriched_shape_and_rejects_a_text_that_is_not_the_composition(table):
    store, cyclotron = setup_router(table)
    config = mr.validate_router_config(table.items[("MONITOR#hn", "CONFIG#router")])
    disc = table.items[("MONITOR#hn", "DISC#101#000001")]
    body = mr.build_decide_request(config, config["publications"][0], disc, enrichment={"summary": "S", "body": "B"})["body"]
    mr.validate_request(body)
    assert body["payload"]["item"]["values"]["text"] == "Alpha source\nhttps://example.org/alpha\n\nS\n\nB"
    bad = json.loads(json.dumps(body))
    bad["payload"]["item"]["values"]["text"] = "Alpha source\nhttps://example.org/alpha"
    with pytest.raises(ValueError):
        mr.validate_request(bad)
    bad["payload"]["item"]["values"] = {**body["payload"]["item"]["values"], "extra": "x"}
    with pytest.raises(ValueError):
        mr.validate_request(bad)
    oversize = json.loads(json.dumps(body))
    oversize["payload"]["item"]["values"].update(body="B" * 70_000, text="x")
    with pytest.raises(ValueError):
        mr.validate_request(oversize)


def test_an_item_already_posted_unenriched_is_not_changed_by_a_later_enrichment(table):
    store, cyclotron = setup_router(table)
    go(table, store, cyclotron, enricher=None)            # posted before enrichment existed
    cyclotron.pending_polls = 0
    enrich = enricher(good())
    go(table, store, cyclotron, now=3000, enricher=enrich)
    assert enrich.capture.calls == [] and len(cyclotron.posts()) == len(PUBS)


# --- delivery copies the curation ------------------------------------------------------------------------------------------------------


@pytest.fixture
def copied(monkeypatch, table):
    references = [{"id": f"reference-{p}-101", "lineageId": f"reference-{p}-101", "versionNumber": 1} for p in PUBS]
    client = MemoryClient(references)
    stores = []
    monkeypatch.setattr(me, "AttachmentStore", lambda c: stores.append(MemoryStore(c)) or stores[-1])
    store, cyclotron = setup_router(table)
    enrich = enricher(good())
    result = go(table, store, cyclotron, enricher=enrich, appsync=lambda endpoint: client)
    return type("Copied", (), {"client": client, "stores": stores, "enrich": enrich, "result": result, "cyclotron": cyclotron, "table": table})


def test_delivery_copies_the_items_curation_onto_each_reference_in_the_card_shape(copied):
    assert copied.result["counts"]["curationCopied"] == len(PUBS)
    for pub in PUBS:
        card = copied.client.card(f"reference-{pub}-101")
        assert card["kind"] == "reference-curation" and card["status"] == "ready" and card["referenceId"] == f"reference-{pub}-101"
        assert card["summary"]["text"] == SUMMARY and card["summary"]["model"] == "gpt-6-luna"
        assert card["capture"]["status"] == "completed" and card["current"]["textSortKey"] == "curation-text"
        assert card["origin"]["kind"] == "item-enrichment" and card["signals"]["endingPattern"] == "sentence_end"
    body = copied.stores[0].text({"id": "reference-anth-us-101"}, "curation-text")
    assert body == ARTICLE                                               # exactly what the lab decided on (it fit, so it was not cut)
    assert copied.table.items[("MONITOR#hn", "ROUTE#101#000001")]["publications"]["anth-us"]["curationCopy"] == "copied"


def test_what_the_panel_shows_is_what_was_decided(copied):
    decided = posted_values(copied.cyclotron)[0]
    card = copied.client.card("reference-anth-us-101")
    assert card["summary"]["text"] == decided["summary"]
    assert copied.stores[0].text({"id": "reference-anth-us-101"}, "curation-text") == decided["body"]


def test_the_post_delivery_curation_procedure_finds_nothing_to_do(copied):
    from papyrus_content import reference_curation as curation
    reference = {"id": "reference-anth-us-101", "lineageId": "reference-anth-us-101", "versionNumber": 1, "sourceUri": "https://example.org/alpha"}
    card = copied.client.card(reference["id"])
    plan = curation.plan_stages(card, force=False, grobid_configured=False, now=me.utc_now(), summarizer_available=True)
    assert plan["outcome"] == "already_curated"


def test_a_failed_copy_never_fails_the_delivery(monkeypatch, table):
    def boom(*args, **kwargs):
        raise RuntimeError("upload refused")
    monkeypatch.setattr(me, "copy_curation", lambda *a, **k: boom())
    monkeypatch.setattr(mr, "copy_curation", lambda *a, **k: boom())
    store, cyclotron = setup_router(table)
    result = go(table, store, cyclotron, enricher=enricher(good()), appsync=lambda endpoint: MemoryClient())
    assert result["counts"]["delivered"] == len(PUBS) and result["counts"]["curationCopyFailed"] == len(PUBS)
    state = table.items[("MONITOR#hn", "ROUTE#101#000001")]["publications"]["anth-us"]
    assert state["delivered"] is True and state["curationCopy"].startswith("failed")


def test_an_existing_card_is_kept(copied):
    row = copied.table.items[("MONITOR#hn", "ENRICH#101#000001")]
    reference = {"id": "reference-anth-us-101", "lineageId": "reference-anth-us-101", "versionNumber": 1}
    assert me.copy_curation(copied.client, reference, row, copied.enrich.texts, me.utc_now()) == "kept"


# --- the Lambda wiring --------------------------------------------------------------------------------------------------------------


class Ssm:
    def __init__(self, value="sk-test", fail=False):
        self.value, self.fail, self.asked = value, fail, []

    def get_parameter(self, Name, WithDecryption):
        self.asked.append((Name, WithDecryption))
        if self.fail:
            raise RuntimeError("AccessDenied")
        return {"Parameter": {"Value": self.value}}


def test_the_lambda_enricher_is_off_without_a_bucket_and_reads_only_its_one_key_parameter():
    assert me.lambda_enricher({}) is None
    ssm = Ssm()
    on = me.lambda_enricher({"ENRICHMENT_BUCKET": "b", "ENRICHMENT_OPENAI_KEY_PARAMETER": "/papyrus/monitoring/openai", "BIBLICUS_GROBID_URL": "http://g"},
                            ssm=ssm, s3=object())
    assert ssm.asked == [("/papyrus/monitoring/openai", True)] and on.summarizer is not None and on.grobid_url == "http://g"
    assert me.lambda_enricher({"ENRICHMENT_BUCKET": "b", "ENRICHMENT_OPENAI_KEY_PARAMETER": "/p"}, ssm=Ssm(fail=True), s3=object()).summarizer is None
    assert me.lambda_enricher({"ENRICHMENT_BUCKET": "b"}, s3=object()).summarizer is None


class S3:
    def __init__(self):
        self.objects, self.puts = {}, []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            error = RuntimeError("missing")
            error.response = {"Error": {"Code": "NoSuchKey"}}
            raise error
        return {"Body": type("B", (), {"read": lambda self_: self.objects[Key]})()}


def test_s3_texts_round_trip_encrypted_and_a_missing_key_is_none():
    client = S3()
    texts = me.S3Texts("bucket", client)
    texts.put("enrichment/hn/1/000001/text.md", "héllo")
    assert texts.get("enrichment/hn/1/000001/text.md") == "héllo" and texts.get("nope") is None
    assert client.puts[0]["ServerSideEncryption"] == "AES256" and client.puts[0]["Bucket"] == "bucket"


# --- the stack ------------------------------------------------------------------------------------------------------------------------


def test_the_stack_has_a_private_bucket_one_key_parameter_and_least_privilege_for_both():
    from test_monitoring_router import _template
    template = _template()
    resources, parameters = template["Resources"], template["Parameters"]
    bucket = resources["EnrichmentBucket"]
    assert bucket["DeletionPolicy"] == "Retain" and set(bucket["Properties"]["PublicAccessBlockConfiguration"].values()) == {True}
    assert parameters["EnrichmentOpenAiKeyParameter"]["Default"] == "" and parameters["EnrichmentGrobidUrl"]["Default"] == ""
    env = resources["RouterFunction"]["Properties"]["Environment"]["Variables"]
    assert env["ENRICHMENT_BUCKET"] == ("Ref", "EnrichmentBucket") and "ENRICHMENT_OPENAI_KEY_PARAMETER" in env and "BIBLICUS_GROBID_URL" in env
    key = resources["RouterEnrichmentKeyPolicy"]["Properties"]
    (read,) = key["PolicyDocument"]["Statement"]
    assert read["Action"] == "ssm:GetParameter" and "EnrichmentOpenAiKeyParameter" in json.dumps(read["Resource"]) and "*" not in json.dumps(read["Resource"])
    storage = resources["RouterEnrichmentStoragePolicy"]["Properties"]["PolicyDocument"]["Statement"]
    assert storage[0]["Action"] == ["s3:GetObject", "s3:PutObject"] and storage[0]["Resource"][1].endswith("/enrichment/*")
    assert all(r[1].endswith("/types/Mutation/fields/createModelAttachmentDownload") for r in storage[1]["Resource"]) and len(storage[1]["Resource"]) == 7


def test_the_router_gets_the_tavily_key_parameter_and_may_read_and_decrypt_only_that():
    from test_monitoring_router import _template
    template = _template()
    assert template["Parameters"]["TavilyKeyParameter"]["Default"] == "/papyrus/shared/tavily-api-key"
    env = template["Resources"]["RouterFunction"]["Properties"]["Environment"]["Variables"]
    assert "PAPYRUS_TAVILY_KEY_PARAMETER" in env
    policy = template["Resources"]["RouterTavilyKeyPolicy"]
    assert policy["Condition"] == "HasTavilyKey"
    read, decrypt = policy["Properties"]["PolicyDocument"]["Statement"]
    assert read["Action"] == "ssm:GetParameter" and "TavilyKeyParameter" in json.dumps(read["Resource"]) and "*" not in json.dumps(read["Resource"])
    assert decrypt["Action"] == "kms:Decrypt" and "kms:ViaService" in json.dumps(decrypt["Condition"])


def test_the_collector_gets_the_same_tavily_key_grants_for_web_search():
    from test_monitoring_router import _template
    template = _template()
    env = template["Resources"]["CollectorFunction"]["Properties"]["Environment"]["Variables"]
    assert "PAPYRUS_TAVILY_KEY_PARAMETER" in env
    policy = template["Resources"]["CollectorTavilyKeyPolicy"]
    assert policy["Condition"] == "HasTavilyKey" and policy["Properties"]["Roles"] == [("Ref", "CollectorRole")]
    read, decrypt = policy["Properties"]["PolicyDocument"]["Statement"]
    assert read["Action"] == "ssm:GetParameter" and "TavilyKeyParameter" in json.dumps(read["Resource"]) and "*" not in json.dumps(read["Resource"])
    assert decrypt["Action"] == "kms:Decrypt" and "kms:ViaService" in json.dumps(decrypt["Condition"])
