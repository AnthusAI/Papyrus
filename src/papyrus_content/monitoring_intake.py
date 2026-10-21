"""Use existing Reference/message factories and authoring APIs for a worker.

Editorial-session intake is owned by PR367; this adapter does not grant access,
fall back to IAM, update curation or fabricate classifier/feedback receipts.
"""
from __future__ import annotations

import json

from .catalog import (catalog_item_with_external_item_id, message_record,
                      reference_attachment_records, reference_record, semantic_relation_record)
from .ids import hash_short, knowledge_corpus_id
from .monitoring import Monitor, SourceItem, canonical_url
from .records import apply_record_changes, build_record_changes


class ReferenceIntake:
    def __init__(self, client, monitor: Monitor, *, auth_mode: str, persist=None):
        if auth_mode != "iam":
            raise ValueError("This Monitor worker requires explicitly configured IAM; editorial-session intake is owned by PR367. No IAM fallback.")
        if client.endpoint.rstrip("/") != monitor.endpoint.rstrip("/") or getattr(client, "tenant_id", None):
            raise ValueError("Monitor endpoint/tenant binding does not match the selected worker client")
        corpora = [r for r in client.list_records("KnowledgeCorpus") if r.get("role") == "canonical"]
        if (len(corpora) != 1 or corpora[0].get("id") != monitor.corpus_id
                or knowledge_corpus_id({"key": monitor.publication}) != monitor.corpus_id):
            raise ValueError("Monitor binding requires the publication's single verified canonical KnowledgeCorpus")
        self.client, self.monitor = client, monitor
        self.persist = persist or (lambda rows: apply_record_changes(client, build_record_changes(client, rows)))

    @staticmethod
    def _machine_decision_note(provenance: dict) -> str:
        """Editors see where a routed item came from: the machine decision recorded in the provenance."""
        decision = provenance.get("machineDecision")
        if not isinstance(decision, dict):
            return ""
        return (f" Machine decision: {decision.get('system')} labelled {decision.get('output')} "
                f"{decision.get('label')} (decision {decision.get('decisionId')}, version {decision.get('version')}).")

    def __call__(self, item: SourceItem, provenance: dict) -> dict:
        for key, value in self.monitor.binding.items():
            if provenance.get(key) != value:
                raise ValueError("Discovery provenance does not match the verified Monitor binding")
        if (provenance.get("sourceId") != item.source_id or provenance.get("fingerprint") != item.fingerprint
                or provenance.get("sourceItemUrl") != item.source_item_url):
            raise ValueError("Discovery provenance does not match the source item")
        matches = []
        for row in self.client.list_records("Reference"):
            if row.get("corpusId") != self.monitor.corpus_id or row.get("versionState") not in {None, "current"}:
                continue
            try:
                same = canonical_url(row.get("sourceUri") or "") == item.canonical_url
            except ValueError:
                same = False
            if same:
                matches.append(row)
        if len({row.get("lineageId") for row in matches}) > 1:
            raise ValueError("Multiple canonical Reference lineages match; editorial resolution is required")
        source = catalog_item_with_external_item_id({
            "source_uri": item.canonical_url, "title": item.title, "media_type": "text/html",
            "published_at": item.published_at, "retrieved_at": provenance["observedAt"],
            "curation_status": "pending", "ingestion_rationale":
                f"Discovered through Hacker News Monitor {self.monitor.id} for {self.monitor.publication}; pending human review. {item.source_item_url}"
                + self._machine_decision_note(provenance),
        })
        context = {"corpusId": self.monitor.corpus_id,
                   "importRunId": "monitor-" + hash_short([self.monitor.binding, item.source_id, item.fingerprint]),
                   "now": provenance["observedAt"], "actor": "papyrus-monitoring-worker"}
        if matches:
            reference = max(matches, key=lambda row: row.get("versionNumber") or 1)
        else:
            proposed = reference_record(source, context)["expected"]
            # The catalog factory builds an import intermediate. Canonical Reference
            # has no metadata column; provenance belongs in its private Message.
            proposed.pop("metadata", None)
            try:
                # Normal model create is conditional on absent identity; never upsert
                # a Reference, which could reset another worker's human curation.
                self.client.create_record("Reference", proposed)
            except Exception as error:
                if "ConditionalCheckFailed" not in str(error) and "already exists" not in str(error):
                    raise
                existing = self.client.get_record("Reference", proposed["id"])
                if (not existing or existing.get("corpusId") != self.monitor.corpus_id
                        or canonical_url(existing.get("sourceUri") or "") != item.canonical_url):
                    raise
            reference = self.client.get_record("Reference", proposed["id"])
            if not reference or reference.get("corpusId") != self.monitor.corpus_id:
                raise ValueError("Reference creation has no verified persisted readback")

        event_id = "message-monitor-" + hash_short([self.monitor.binding, item.source_id, item.fingerprint])
        message = message_record({"id": event_id, "messageKind": "ingestion_rationale",
                                  "source": "papyrus-monitoring", "authorLabel": "Papyrus Monitor worker",
                                  "summary": f"Hacker News discovery: {item.title}",
                                  "body": json.dumps(provenance, sort_keys=True),
                                  "metadata": {"corpusId": self.monitor.corpus_id},
                                  "createdAt": provenance["observedAt"], "importRunId": context["importRunId"]})
        # The canonical Message envelope omits bodies. Supply the private payload
        # to the existing expander, which uploads it instead of sending it to DynamoDB.
        message["expected"]["body"] = json.dumps(provenance, sort_keys=True)
        relation = semantic_relation_record({
            "predicate": "ingestion_rationale", "subjectKind": "message", "subjectId": event_id,
            "subjectLineageId": event_id, "subjectVersionNumber": 1,
            "objectKind": "reference", "objectId": reference["id"],
            "objectLineageId": reference["lineageId"], "objectVersionNumber": reference.get("versionNumber") or 1,
            "importRunId": context["importRunId"], "importedAt": provenance["observedAt"],
            "metadata": {"monitorId": self.monitor.id, "sourceId": item.source_id},
        })
        run = {"modelName": "KnowledgeImportRun", "expected": {
            "id": context["importRunId"], "corpusId": self.monitor.corpus_id,
            "importKind": "monitor-discovery", "corpusImportKindKey": f"{self.monitor.corpus_id}#monitor-discovery",
            "status": "imported", "generatedAt": provenance["observedAt"], "importedAt": provenance["observedAt"],
            "itemCount": 1, "referenceCount": 1, "relationCount": 1, "warningCount": 0,
        }}
        self.persist([run, *reference_attachment_records(source, reference, context), message, relation])
        return {"referenceId": reference["id"], "referenceLineageId": reference["lineageId"],
                "referenceVersion": reference.get("versionNumber") or 1, "provenanceMessageId": event_id}
