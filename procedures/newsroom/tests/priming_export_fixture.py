"""A fake site backend for the priming export: References, an automation, its runs and the stories they made."""
import json
from copy import deepcopy

from papyrus_content.reference_curation_store import card_id

CORPUS = "knowledge-corpus-distinctive"
PUBLICATION = "distinctive"
PROCEDURE = "distinctive.ttab.ruling-analysis"
EDITOR_ADDRESS = "editor.person@example.test"


def reference(name, status="pending", by="papyrus-monitoring-worker", reason="", source_uri=None, published="2026-09-28T04:00:00Z", **extra):
    return {"id": f"{name}-v1", "lineageId": name, "versionState": "current", "corpusId": CORPUS, "title": f"Title of {name}",
            "sourceUri": source_uri or f"https://example.test/{name}", "sourcePublishedAt": published, "importedAt": "2026-10-21T20:58:41Z",
            "curationStatus": status, "curationStatusUpdatedBy": by, "curationStatusUpdatedAt": "2026-10-25T10:00:00Z",
            "curationStatusReason": reason, **extra}


def automation(monitor="ttab", publication=PUBLICATION, kind="monitor", procedure=PROCEDURE):
    return {"id": f"{publication}.{monitor}", "procedureKey": procedure,
            "trigger": json.dumps({"kind": kind, "config": {"monitorId": monitor, "publicationId": publication}})}


def run(story, proceeding, *, status="completed", at="2026-10-24T17:05:50Z", procedure=PROCEDURE):
    return {"id": f"run-{story}-{at}", "procedureKey": procedure, "runStatus": status, "requestedAt": at,
            "input": json.dumps({"proceeding": proceeding, "opinion_url": f"https://ttab.example.test/{proceeding}/decision.pdf"}),
            "output": json.dumps({"story": story} if story else {})}


def version(story, number, stage, by, *, state="superseded", reason="", date="2026-10-06", at="2026-10-24T18:00:00Z"):
    return {"id": f"{story}-v{number}", "lineageId": story, "versionNumber": str(number), "versionState": state, "stage": stage,
            "versionCreatedBy": by, "versionCreatedAt": at, "changeReason": reason, "title": f"Story {story}",
            "metadata": json.dumps({"frontMatterYaml": f'date: "{date}"\ncaption: "x"\n'})}


class FakeSite:
    """list_records / list_by_index / get_record over dict tables. It has no write method, so a write cannot happen."""

    def __init__(self, references=(), automations=(), runs=(), versions=(), cards=None):
        self.tables = {"Reference": list(references), "Automation": list(automations), "ProcedureRun": list(runs), "Item": list(versions)}
        self.cards = cards or {}
        self.calls = []

    def list_records(self, model):
        self.calls.append(("list", model))
        return deepcopy(self.tables.get(model, []))

    def list_by_index(self, index, key, **_):
        self.calls.append(("index", index))
        assert index == "itemsByLineageAndVersion"
        return deepcopy([row for row in self.tables["Item"] if row["lineageId"] == key])

    def get_record(self, model, record_id):
        self.calls.append(("get", model))
        if model == "ReferenceAttachment":
            for lineage, card in self.cards.items():
                if record_id == card_id({"id": f"{lineage}-v1"}):
                    return {"id": record_id, "metadata": json.dumps({"kind": "reference-curation", **card})}
        return None

    def list_reference_attachments_by_lineage(self, lineage):
        return []


class FakeCards:
    """Stands in for AttachmentStore: the curation-text body of a Reference by lineage id."""

    bodies = {}

    def __init__(self, client):
        pass

    def read_text(self, reference, sort_key):
        return self.bodies.get(reference["lineageId"])
