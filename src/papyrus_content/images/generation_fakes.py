"""Stand-ins for what apply writes to, for the generation tests and specs: media, review requests and Story versions held in memory. No network, no AWS."""
from __future__ import annotations


class FakeMedia:
    def __init__(self) -> None:
        self.assets: list[dict] = []
        self.review_requests: list[dict] = []

    def add_media(self, *, target: dict, src_path: str, data: bytes, media_type: str, alt: str, caption: str | None, provenance: dict) -> dict:
        asset = {"id": f"media-asset-{len(self.assets) + 1}", "srcPath": src_path, "mediaType": media_type, "alt": alt, "caption": caption, "bytes": len(data), "provenance": provenance}
        self.assets.append(asset)
        return {key: value for key, value in asset.items()}

    def open_review_request(self, *, media_asset_id: str, target: dict, candidate_id: str, applied_by: str) -> str:
        self.review_requests.append({"id": f"review-{len(self.review_requests) + 1}", "mediaAssetId": media_asset_id, "target": target, "candidateId": candidate_id, "appliedBy": applied_by})
        return self.review_requests[-1]["id"]


class FakeStories:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def save(self, *, target: dict, patch: dict, expected_current_version_id: str, actor: str) -> dict:
        self.saved.append({"target": target, "patch": patch, "expected": expected_current_version_id, "actor": actor})
        return {"versionId": f"{target['lineageId']}-v{len(self.saved) + 1}", "versionNumber": len(self.saved) + 1}
