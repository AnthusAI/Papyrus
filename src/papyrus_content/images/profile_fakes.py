"""An in-memory backend for the style profile tests and specs: just the calls the profile handlers make. No network, no AWS."""
from __future__ import annotations

import copy
import json
from typing import Any

MOM_PROFILE: dict = {
    "schemaVersion": 2,
    "identity": {
        "summary": "Flat, calm pictures in ink blue on cool paper.",
        "masterPrompt": "Flat shapes with generous rounded corners.",
        "palette": [{"name": "Ink blue", "hex": "#1f2a44", "token": "brand", "role": "brand"}, {"name": "Cool paper", "hex": "#f6f7f9", "token": "paper", "role": "ground"}],
        "paletteLimit": 6, "mood": ["calm"], "examples": [],
    },
    "techniques": {"preferred": ["flat shapes"], "avoided": ["drop shadows"]},
    "subjects": {"representation": "People are faceless silhouettes.", "never": ["real people", "real brands"]},
    "treatments": {
        "diagram": {"label": "Diagram", "guidance": "Explains a relationship."},
        "editorial-illustration": {"label": "Editorial illustration", "guidance": "A place or a moment.", "avoid": ["3D render"]},
        "photo": {"label": "Photograph", "guidance": "Authentic photographs only."},
    },
    "uses": {"cover": {"label": "Headline picture"}, "inline": {"label": "In the article"}, "social": {"label": "Social card"}},
    "imageTypes": {
        "cover-diagram": {"label": "Headline diagram", "description": "A chunky diagram that reads as a card thumbnail.", "treatment": "diagram", "use": "cover",
                          "display": {"smallestWidthPx": 160, "thumbnail": True}, "sources": ["figure-system"],
                          "figureSystem": {"rules": "design/figures/rules.md", "variant": "cover"}, "sizes": {"aspectRatio": "16:9", "width": 1920, "height": 1088}},
        "inline-diagram": {"label": "Technical diagram", "description": "A detailed diagram inside the article.", "treatment": "diagram", "use": "inline",
                           "display": {"smallestWidthPx": 343, "thumbnail": False}, "sources": ["figure-system"], "figureSystem": {"rules": "design/figures/rules.md"}},
        "cover-photo": {"label": "Headline photograph", "description": "A rights-cleared photograph.", "treatment": "photo", "use": "cover", "sources": ["stock"],
                        "display": {"smallestWidthPx": 160, "thumbnail": True}},
        "cover-illustration": {
            "label": "Headline illustration", "description": "A bold illustration that still reads small.", "treatment": "editorial-illustration", "use": "cover",
            "display": {"where": "article top and cards", "smallestWidthPx": 160, "thumbnail": True},
            "guidance": "One subject, large, in the lower third.", "avoid": ["small details", "more than one subject"],
            "sizes": {"aspectRatio": "16:9", "width": 1920, "height": 1088},
            "safeZones": [{"region": "upper third", "instruction": "Keep the upper third quiet."}], "sources": ["stock", "generated"],
        },
        "inline-illustration": {
            "extends": "cover-illustration", "label": "Illustration in the article", "description": "A larger illustration inside the article.", "use": "inline",
            "display": {"where": "article body", "smallestWidthPx": 343, "thumbnail": False}, "guidance": "Several elements may share the scene.",
            "removeFromParent": {"avoid": ["small details", "more than one subject"], "safeZones": True}, "sources": ["generated", "stock"],
        },
        "social-card": {"extends": "cover-illustration", "label": "Social card", "use": "social", "sizes": {"aspectRatio": "1.91:1", "width": 1200, "height": 630},
                        "display": {"smallestWidthPx": 120, "thumbnail": True}},
    },
    "typePreference": {"cover": ["cover-diagram", "cover-photo", "cover-illustration"], "inline": None, "social": ["social-card"]},
    "constraints": [{
        "id": "no-photoreal-generated", "version": 1, "appliesTo": {"origins": ["generated"]}, "prohibits": {"treatments": ["photo"]},
        "text": "Generated pictures must be unmistakably illustrations.", "promptDirective": "Unmistakably an illustration.",
        "promptAvoid": ["photograph", "photorealistic"], "adoptedBy": "admin-account", "adoptedAt": "2026-11-07T17:51:39Z", "reason": "Publication rule.",
    }],
    "imageReview": "after_the_fact",
}


def profile_copy() -> dict:
    return copy.deepcopy(MOM_PROFILE)


class FakeBackend:
    """Just enough of the authoring client for one publication: its canonical corpus, doctrine and Story Items, and newsroom sections."""

    def __init__(self, publication: str = "example", *, tenant_id: str | None = None, profile: dict | None = None):
        self.tenant_id = tenant_id
        self.endpoint = None
        self.corpora = [{"id": f"knowledge-corpus-{publication}", "name": publication.title(), "role": "canonical"}]
        self.items: list[dict] = []
        self.sections: dict[str, dict] = {}
        self.writes: list[tuple[str, str, dict]] = []
        self.reads: list[tuple[str, str]] = []
        self.document_attachments: list[dict] = []
        self.document_bodies: dict[str, bytes] = {}
        self.document_files = FakeFiles(self)
        self.attachments: dict[str, dict] = {}
        if profile is not None:
            self.save_profile_version(profile, by="admin-account", reason="First profile.")

    def save_profile_version(self, document: dict, *, by: str, reason: str, section: str | None = None) -> dict:
        """Save a document the way the store does now: a catalog row, the text in the fake S3."""
        from .profile_store import document_store, IMAGE_KIND

        store = document_store(self)
        current = store.current_row(IMAGE_KIND, section)
        saved = store.save(IMAGE_KIND, document, section=section, expected_current_version_id=current["id"] if current else "none", actor=by, reason=reason,
                           now="2026-11-07T17:51:39Z", saved_by={"sub": by, "kind": "person"})
        return next(row for row in self.items if row["id"] == saved["reference"]["itemId"])

    def save_inline_profile_version(self, document: dict, *, by: str, reason: str) -> dict:
        """Save a profile the way a site that has not moved yet holds it: inline in the row's metadata."""
        from .profile_store import inline_next_record, profile_versions

        versions = profile_versions(self)
        record = inline_next_record(versions, document, actor=by, reason=reason, now="2026-11-07T17:51:39Z", saved_by={"sub": by, "kind": "person"})
        self.create_record("Item", record)
        for row in versions:
            if row.get("versionState") == "current":
                self.update_record("Item", {"id": row["id"], "versionState": "superseded"})
        return record

    def add_story(self, lineage: str, *, section: str | None = None, image_style: dict | None = None, version: int = 1) -> dict:
        metadata = {"imageStyle": image_style} if image_style else {}
        row = {"id": f"{lineage}-v{version}", "lineageId": lineage, "versionNumber": version, "versionState": "current", "type": "article", "section": section,
               "tenantId": self.tenant_id, "metadata": json.dumps(metadata)}
        self.items.append(row)
        return row

    def add_section(self, section_id: str, **fields: Any) -> dict:
        self.sections[section_id] = {"id": section_id, "title": section_id.title(), "tenantId": self.tenant_id, "updatedAt": "2026-11-07", **fields}
        return self.sections[section_id]

    # the calls the handlers make
    def list_by_index(self, index: str, key: str, **_: Any) -> list[dict]:
        self.reads.append((index, key))
        if index == "knowledgeCorporaByRoleAndName":
            return copy.deepcopy(self.corpora)
        if index == "itemBySlug":
            return copy.deepcopy([row for row in self.items if row.get("slug") == key])
        if index == "modelAttachmentsByOwnerRoleAndSortKey":
            return copy.deepcopy([row for row in self.document_attachments if row.get("ownerId") == key])
        if index == "itemsByLineageAndVersion":
            return copy.deepcopy([row for row in self.items if row.get("lineageId") == key])
        raise AssertionError(f"unexpected index {index}")

    def add_attachment(self, sha: str, *, role: str = "visual_example", media_type: str = "image/png", size: int = 200_000, filename: str | None = None, **fields: Any) -> str:
        """An uploaded and completed picture, the way completeModelAttachmentUpload leaves it. Returns its attachment id."""
        attachment_id = f"model-attachment-item-item-editorial-doctrine-visual-style-{role.replace('_', '-')}-{sha}"
        self.attachments[attachment_id] = {"id": attachment_id, "ownerKind": "item", "ownerId": "item-editorial-doctrine-visual-style", "role": role, "sortKey": sha,
                                           "filename": filename or f"{sha}.png", "mediaType": media_type, "byteSize": size, "sha256": sha, "status": "active", **fields}
        return attachment_id

    def get_record(self, model: str, record_id: str) -> dict | None:
        if model == "ModelAttachment":
            return copy.deepcopy(self.attachments.get(record_id))
        return copy.deepcopy(self.sections.get(record_id)) if model == "NewsroomSection" else None

    def get_record_with_fields(self, model: str, record_id: str, extra_fields: str) -> dict | None:
        return self.get_record(model, record_id)

    def safe_list_records(self, model: str) -> list[dict]:
        return copy.deepcopy(list(self.sections.values())) if model == "NewsroomSection" else []

    def create_record(self, model: str, record: dict) -> None:
        assert model == "Item"
        self.writes.append(("create", model, copy.deepcopy(record)))
        self.items.append({**copy.deepcopy(record), "tenantId": self.tenant_id})

    def update_record(self, model: str, record: dict) -> None:
        assert model == "Item"
        self.writes.append(("update", model, copy.deepcopy(record)))
        next(row for row in self.items if row["id"] == record["id"]).update(copy.deepcopy(record))


class FakeFiles:
    """The S3 side of the fake: what the upload does with an attachment (it creates the ModelAttachment row) and what a download returns."""

    def __init__(self, backend: FakeBackend):
        self.backend = backend
        self.downloads: list[str] = []

    def put(self, attachment: dict, body: bytes) -> dict:
        self.backend.document_attachments.append(copy.deepcopy(attachment))
        self.backend.document_bodies[attachment["storagePath"]] = bytes(body)
        return attachment

    def get(self, attachment: dict) -> bytes | None:
        self.downloads.append(attachment["ownerId"])
        return self.backend.document_bodies.get(attachment["storagePath"])
