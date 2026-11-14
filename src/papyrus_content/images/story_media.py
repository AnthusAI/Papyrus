"""Apply for real: copy a generated picture into the site's media and make the Story's next draft version, never a publication.

``StoryMediaWriter`` is both of the things apply writes through. ``add_media`` puts the picture at ``media/<srcPath>`` (the key the newsroom editor, ``stories
save-version --images`` and the renditions all agree on) and remembers its MediaAsset row; ``save`` then makes the Story's next version with
``save_story_version`` (which stores that row against the new version and carries earlier pictures forward). A generated picture carries no credit line: the
MediaAsset says it was generated, with the candidate, model and guidelines version it came from, and the page shows only the subtle generated note.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from papyrus_content.markus_import import media_id_for
from papyrus_content.record_helpers import to_aws_json
from papyrus_content.renditions import media_key_for_source
from papyrus_content.story_reporting import _current_of, planned_version_record_id, save_story_version, story_versions

PutObject = Callable[[str, bytes, str, str], None]


def s3_put_object(store: Any) -> PutObject:
    """Put bytes under a media key with a media store's own client (the signed-in person's rights, or the AWS credentials of the lane)."""
    def put(storage_path: str, data: bytes, content_type: str, sha256: str) -> None:
        store._require_media_key(storage_path)
        if store.has(storage_path, sha256):
            return
        store._client.put_object(Bucket=store.bucket, Key=storage_path, Body=data, ContentType=content_type, Metadata={"sha256": sha256})
    return put


class StoryMediaWriter:
    def __init__(self, client: Any, put_object: PutObject, *, review_requests: Any = None):
        self.client, self.put_object, self.review_requests = client, put_object, review_requests
        self.pending: dict[str, dict] = {}

    def add_media(self, *, target: dict, src_path: str, data: bytes, media_type: str, alt: str, caption: str | None, provenance: dict) -> dict:
        digest = hashlib.sha256(data).hexdigest()
        storage_path = media_key_for_source(src_path)
        self.put_object(storage_path, data, media_type, digest)
        next_id = planned_version_record_id(self.client, target["lineageId"])
        asset = {"id": media_id_for(next_id, src_path), "srcPath": src_path, "storagePath": storage_path, "alt": alt, "caption": caption, "mediaType": media_type,
                 "bytes": len(data), "sha256": digest, "provenance": provenance}
        self.pending[target["lineageId"]] = {**asset, "position": len(self.pending)}
        return asset

    def open_review_request(self, *, media_asset_id: str, target: dict, candidate_id: str, applied_by: str) -> str:
        if self.review_requests is None:
            return f"review-pending-{media_asset_id}"
        return self.review_requests(media_asset_id=media_asset_id, target=target, candidate_id=candidate_id, applied_by=applied_by)

    def _media_row(self, item_id: str, asset: dict) -> dict:
        return {"id": media_id_for(item_id, asset["srcPath"]), "itemId": item_id, "type": "image", "role": "body", "sortKey": f"{asset['position']:03d}#{asset['srcPath']}",
                "storagePath": asset["storagePath"], "alt": asset["alt"], **({"caption": asset["caption"]} if asset.get("caption") else {}),
                "metadata": to_aws_json({"srcPath": asset["srcPath"], "sha256": asset["sha256"], "bytes": asset["bytes"], "contentType": asset["mediaType"],
                                         "generated": True, **asset["provenance"]})}

    def save(self, *, target: dict, patch: dict, expected_current_version_id: str, actor: str) -> dict:
        import yaml

        versions = story_versions(self.client, target["lineageId"])
        latest = _current_of(versions)
        if latest["id"] != expected_current_version_id:
            from .handlers import ImageOperationError

            raise ImageOperationError("stale_version", "The Story has changed since you read it. Read it again.", details={"currentVersionId": latest["id"]})
        metadata = json.loads(latest.get("metadata") or "{}") if isinstance(latest.get("metadata"), str) else dict(latest.get("metadata") or {})
        front = yaml.safe_load(metadata.get("frontMatterYaml") or "") or {}
        front.update(patch.get("frontMatter") or {})
        body = latest.get("bodyMarkus") or ""
        directive = patch["bodyDirective"]
        body = f"{directive}\n\n{body}" if patch.get("frontMatter", {}).get("image") else f"{body.rstrip()}\n\n{directive}\n"
        asset = self.pending.pop(target["lineageId"], None)
        record = save_story_version(self.client, target["lineageId"], front_matter_yaml=yaml.safe_dump(front, sort_keys=False, allow_unicode=True) if front else None,
                                    body_markus=body, actor=actor, change_reason="Added a generated picture.",
                                    media_rows=(lambda item_id: [self._media_row(item_id, asset)]) if asset else None)
        return {"versionId": record["id"], "versionNumber": record["versionNumber"]}
