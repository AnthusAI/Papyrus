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


def _rule_text(rule) -> str:
    """The direct-routing rule in words for the editor's rationale line."""
    if not isinstance(rule, dict):
        return "every collected item"
    reasons = (["a watchlisted author"] if rule.get("authors") else []) \
        + [f"at least {rule[key]} {name}" for key, name in (("minLikes", "likes"), ("minDownloads", "downloads")) if rule.get(key) is not None]
    return " or ".join(reasons) if reasons else "matching the monitor's filters"


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
        if decision.get("system") == "direct":
            return f" Delivered by the monitor's rule for this source ({_rule_text(decision.get('rule'))}); no machine relevance decision."
        return (f" Machine decision: {decision.get('system')} labelled {decision.get('output')} "
                f"{decision.get('label')} (decision {decision.get('decisionId')}, version {decision.get('version')}).")

    @staticmethod
    def _details_note(item: SourceItem) -> str:
        """For a source with structured details (a Hugging Face model), a short line an editor can scan."""
        d = item.details
        if not d:
            return ""
        if "query" in d:    # a web-search result
            return f" Found by the web search \u201c{d['query']}\u201d."
        parts = [d.get("pipelineTag"), f"license {d['license']}" if d.get("license") else None,
                 f"{d['likes']} likes", "built on " + ", ".join(b["modelId"] for b in d["baseModels"][:3]) if d.get("baseModels") else None]
        text = "; ".join(p for p in parts if p)
        return f" {text[:1].upper()}{text[1:]}." if text else ""

    def __call__(self, item: SourceItem, provenance: dict, extra_records=None, *, reference_id=None) -> dict:
        """`extra_records(reference)` may return more records for the same persist batch (the router's lab
        decision relation), so they land with the Reference and its provenance Message or not at all."""
        for key, value in self.monitor.binding.items():
            if provenance.get(key) != value:
                raise ValueError("Discovery provenance does not match the verified Monitor binding")
        if (provenance.get("sourceId") != item.source_id or provenance.get("fingerprint") != item.fingerprint
                or provenance.get("sourceItemUrl") != item.source_item_url):
            raise ValueError("Discovery provenance does not match the source item")
        matches = []
        addresses = {item.canonical_url}
        for alias in item.aliases:
            try:
                addresses.add(canonical_url(alias))
            except ValueError:
                continue
        if reference_id:
            selected = self.client.get_record("Reference", reference_id)
            if (not selected or selected.get("corpusId") != self.monitor.corpus_id
                    or selected.get("versionState") != "current" or selected.get("sourceUri") != item.canonical_url):
                raise ValueError("Selected Reference no longer matches the imported candidate")
            matches = [selected]
        for row in ([] if reference_id else self.client.list_records("Reference")):
            if row.get("corpusId") != self.monitor.corpus_id or row.get("versionState") not in {None, "current"}:
                continue
            try:
                same = canonical_url(row.get("sourceUri") or "") in addresses
            except ValueError:
                same = False
            if same:
                matches.append(row)
        if len({row.get("lineageId") for row in matches}) > 1:
            raise ValueError("Multiple canonical Reference lineages match; editorial resolution is required")
        source = catalog_item_with_external_item_id({
            "source_uri": item.canonical_url, "title": item.title, "media_type": item.media_type,
            "published_at": item.published_at, "retrieved_at": provenance["observedAt"],
            "curation_status": "pending", "ingestion_rationale":
                f"Discovered through {self.monitor.source_name} Monitor {self.monitor.id} for {self.monitor.publication}; pending human review. {item.source_item_url}"
                + self._details_note(item) + self._machine_decision_note(provenance),
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
                                  "summary": f"{self.monitor.source_name} discovery: {item.title}",
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
            # A source with structured details (a Hub model) keeps them here, where the weekly knowledge run reads them with one
            # indexed query (knowledge_snapshot/monitor_records.py); the Message body holds them too, in private storage.
            "metadata": {"monitorId": self.monitor.id, "sourceId": item.source_id, **({"details": item.details} if item.details else {})},
        })
        run = {"modelName": "KnowledgeImportRun", "expected": {
            "id": context["importRunId"], "corpusId": self.monitor.corpus_id,
            "importKind": "monitor-discovery", "corpusImportKindKey": f"{self.monitor.corpus_id}#monitor-discovery",
            "status": "imported", "generatedAt": provenance["observedAt"], "importedAt": provenance["observedAt"],
            "itemCount": 1, "referenceCount": 1, "relationCount": 1, "warningCount": 0,
        }}
        extras = list(extra_records(reference)) if extra_records else []
        self.persist([run, *reference_attachment_records(source, reference, context), message, relation, *extras])
        return {"referenceId": reference["id"], "referenceLineageId": reference["lineageId"],
                "referenceVersion": reference.get("versionNumber") or 1, "provenanceMessageId": event_id,
                "referenceReused": bool(matches)}
