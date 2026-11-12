"""Generating, reading, discarding and applying pictures: image_generate, image_round_get, image_discard, image_apply and image_capabilities.

``generation_handlers`` binds the handlers to a client (for the guidelines), a candidate store, the providers a site may use and the two things apply needs
to write (media and Story versions). Spending needs the publication's settings to approve it and a provider that was handed in on purpose: the default
handler table does not contain these handlers, so nothing spends by accident. The tests and specs hand in a fake provider.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from .candidates import CLOSED, TERMINAL, CandidateStore
from .generation_settings import GenerationSettings, read_settings
from .handlers import Caller, Handler, ImageOperationError, Outcome
from .image_prices import actual_cost
from .profile_handlers import _publication, _story_for
from .prompt_preview import preview_prompt
from .providers import ImageProvider, ProviderFailure, ProviderRequest

FILE_FOLDER = "newsroom/image-candidates"
MAX_PICTURE_BYTES = 10 * 1024 * 1024
SIGNATURES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg", b"RIFF": "image/webp"}


class MediaSink(Protocol):
    def add_media(self, *, path: str, data: bytes, media_type: str, alt: str, caption: str | None, provenance: dict) -> dict: ...
    def open_review_request(self, *, media_asset_id: str, target: dict, candidate_id: str, applied_by: str) -> str: ...


class StorySaver(Protocol):
    def save(self, *, target: dict, patch: dict, expected_current_version_id: str, actor: str) -> dict: ...


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def summary(candidate: dict, store: CandidateStore | None = None) -> dict:
    keys = ("id", "position", "status", "imageType", "origin", "lane", "reviewStatus", "retryOf", "error")
    row = {key: candidate[key] for key in keys if candidate.get(key) is not None}
    row["reviewStatus"] = candidate.get("reviewStatus", "unreviewed")
    return row


def free_checks(data: bytes, expected_media_type: str) -> list[dict]:
    found = next((kind for signature, kind in SIGNATURES.items() if data.startswith(signature)), None)
    return [{"name": "format", "passed": found is not None and found == expected_media_type},
            {"name": "size", "passed": 0 < len(data) <= MAX_PICTURE_BYTES}]


class Generation:
    def __init__(self, client: Any, store: CandidateStore, providers: dict[str, ImageProvider], *, media: MediaSink | None = None, stories: StorySaver | None = None,
                 files=None, now: Callable[[], str] = _now, new_id: Callable[[str], str] = _id):
        self.client, self.store, self.providers, self.media, self.stories = client, store, providers, media, stories
        self.files, self.now, self.new_id = files, now, new_id

    def settings(self) -> GenerationSettings:
        return read_settings(self.client, self.files)

    def capabilities(self, arguments: dict, caller: Caller) -> Outcome:
        publication = _publication(self.client)
        settings = self.settings()
        result = settings.public()
        result["spentTodayUsd"] = self.store.spent_on(self.now()[:10])
        return Outcome(result, publication)

    def _model_entry(self, settings: GenerationSettings, asked: str | None) -> dict:
        if not settings.configured:
            raise ImageOperationError("generation_not_configured", "This site has no image model set up. Add one under generation.models in the image guidelines.",
                                      details={"reason": "no_models"})
        if not settings.spend_approved:
            raise ImageOperationError("generation_not_configured", "Spending on image generation is not approved for this site, so nothing was made. A person approves it "
                                      "by setting generation.spendApproved in the image guidelines.", details={"reason": "spend_not_approved"})
        names = [model["name"] for model in settings.models]
        if asked and asked not in names:
            raise ImageOperationError("capability_unsupported", f"{asked} is not a model this site has approved.", details={"alternatives": names})
        return next(model for model in settings.models if not asked or model["name"] == asked)

    def _ceiling_problem(self, settings: GenerationSettings, round_spent: float) -> str | None:
        day = self.store.spent_on(self.now()[:10])
        if settings.per_day_ceiling_usd is not None and day >= settings.per_day_ceiling_usd:
            return f"The day's spending ceiling of ${settings.per_day_ceiling_usd} is reached (${day} spent)."
        if settings.per_round_ceiling_usd is not None and round_spent >= settings.per_round_ceiling_usd:
            return f"The round's spending ceiling of ${settings.per_round_ceiling_usd} is reached (${round_spent} spent)."
        return None

    def generate(self, arguments: dict, caller: Caller) -> Outcome:
        publication = _publication(self.client)
        if caller.request_id:
            earlier = self.store.round_for_request(caller.request_id, caller.subject)
            if earlier is not None:
                return Outcome(self._round_result(earlier), publication)
        settings = self.settings()
        entry = self._model_entry(settings, arguments.get("model"))
        provider = self.providers.get(entry["provider"])
        if provider is None:
            raise ImageOperationError("generation_not_configured", f"No {entry['provider']} provider is available in this place.", details={"reason": "provider_unavailable"})
        preview = preview_prompt(self.client, arguments, caller, self.files)
        plans = preview.result["plans"]
        speed = "standard"
        round_id = self.new_id("round")
        target = arguments.get("target")
        round_record = {"roundId": round_id, "target": target, "sectionId": arguments.get("sectionId"), "use": arguments["use"], "imageType": plans[0]["imageType"],
                        "imageTypeChosenBy": plans[0]["imageTypeChosenBy"], "brief": arguments["brief"], "createdBy": caller.subject, "createdByKind": caller.kind,
                        **({"delegatedBy": caller.delegated_by} if caller.delegated_by else {}), "requestId": caller.request_id, "createdAt": self.now(),
                        "model": entry["name"], "lane": speed, "private": not target}
        self.store.save_round(round_record)
        spent = 0.0
        for plan in plans:
            candidate = {"id": self.new_id("candidate"), "roundId": round_id, "position": plan["position"], "status": "running", "imageType": plan["imageType"], "origin": "generated",
                         "lane": speed, "reviewStatus": "unreviewed", "createdAt": self.now(), "prompt": plan["text"], "resolutionHash": plan["resolutionHash"],
                         "profile": plan["profile"], "model": entry["name"], "provider": entry["provider"], "costUsd": 0.0,
                         "altDraft": {"text": arguments["brief"], "basis": "brief", "note": "Drafted from the brief, not from the picture. A person should check it."}}
            problem = self._ceiling_problem(settings, spent)
            if problem:
                candidate.update(status="failed", error={"code": "spend_ceiling_exceeded", "message": problem, "retryable": False})
                self.store.save_candidate(candidate)
                continue
            sizes = plan["settings"]
            request = ProviderRequest(plan["text"], entry["name"], int(sizes.get("width") or 1024), int(sizes.get("height") or 1024), entry.get("quality"), speed)
            try:
                image = provider.generate(request)
            except ProviderFailure as failure:
                candidate.update(status="failed", error={"code": failure.code, "message": failure.message, "retryable": failure.retryable})
                self.store.save_candidate(candidate)
                continue
            path = f"{FILE_FOLDER}/{round_id}/{candidate['id']}.{image.media_type.split('/')[-1]}"
            self.store.put_file(path, image.data)
            cost = actual_cost(entry["name"], image.input_tokens, image.output_tokens, speed)
            spent = round(spent + (cost or 0), 6)
            candidate.update(status="ready", filePath=path, mediaType=image.media_type, width=image.width, height=image.height, costUsd=cost or 0.0,
                             costKnown=cost is not None, usage={"inputTokens": image.input_tokens, "outputTokens": image.output_tokens}, providerRef=image.provider_ref,
                             checks=free_checks(image.data, image.media_type))
            self.store.save_candidate(candidate)
        return Outcome(self._round_result(round_record, preview.result["estimate"]), publication, preview.warnings)

    def _round_result(self, round_record: dict, estimate: dict | None = None) -> dict:
        candidates = self.store.candidates_of(round_record["roundId"])
        spent = round(sum(row.get("costUsd") or 0 for row in candidates), 6)
        known = all(row.get("costKnown", True) for row in candidates if row["status"] == "ready")
        return {"roundId": round_record["roundId"], "imageType": round_record["imageType"], "imageTypeChosenBy": round_record["imageTypeChosenBy"],
                "candidates": [summary(row) for row in candidates],
                "estimate": estimate or {"priced": known, "usd": spent, "basis": "Worked out from the tokens the provider reported." if known else "Some pictures have no price on file."}}

    def round_get(self, arguments: dict, caller: Caller) -> Outcome:
        publication = _publication(self.client)
        round_record = self.store.get_round(arguments["roundId"])
        if round_record is None:
            raise ImageOperationError("not_found", f"No round {arguments['roundId']} in this publication.")
        candidates = self.store.candidates_of(round_record["roundId"])
        result = {"roundId": round_record["roundId"], "use": round_record["use"], "imageType": round_record["imageType"], "brief": round_record["brief"],
                  "candidates": [summary(row) for row in candidates], "done": all(row["status"] in TERMINAL for row in candidates)}
        if round_record.get("target"):
            result["target"] = round_record["target"]
        return Outcome(result, publication)

    def discard(self, arguments: dict, caller: Caller) -> Outcome:
        publication = _publication(self.client)
        if arguments.get("candidateId"):
            candidate = self.store.get_candidate(arguments["candidateId"])
            if candidate is None:
                raise ImageOperationError("not_found", f"No picture {arguments['candidateId']} in this publication.")
            if candidate["status"] in CLOSED:
                raise ImageOperationError("candidate_closed", f"Picture {candidate['id']} is already {candidate['status']}.")
            chosen = [candidate]
        else:
            if self.store.get_round(arguments["roundId"]) is None:
                raise ImageOperationError("not_found", f"No round {arguments['roundId']} in this publication.")
            chosen = [row for row in self.store.candidates_of(arguments["roundId"]) if row["status"] not in CLOSED]
        for candidate in chosen:
            if candidate.get("filePath"):
                self.store.delete_file(candidate["filePath"])
            self.store.save_candidate({**candidate, "status": "rejected", "discardedBy": caller.subject, "discardedAt": self.now(), "discardReason": arguments["reason"],
                                       "filePath": None})
        return Outcome({"discarded": [row["id"] for row in chosen]}, publication)

    def apply(self, arguments: dict, caller: Caller) -> Outcome:
        publication = _publication(self.client)
        if arguments.get("candidateRef"):
            raise ImageOperationError("source_not_allowed", "Stock pictures are applied from the newsroom's picker for now; this applies generated pictures by candidateId.",
                                      details={"allowed": ["generated"]})
        candidate = self.store.get_candidate(arguments["candidateId"])
        if candidate is None:
            raise ImageOperationError("not_found", f"No picture {arguments['candidateId']} in this publication.")
        if candidate["status"] in CLOSED:
            raise ImageOperationError("candidate_closed", f"Picture {candidate['id']} is already {candidate['status']}.")
        if candidate["status"] != "ready":
            raise ImageOperationError("candidate_not_ready", f"Picture {candidate['id']} is {candidate['status']}.")
        round_record = self.store.get_round(candidate["roundId"]) or {}
        if round_record.get("private"):
            raise ImageOperationError("invalid_input", "That picture was made without a Story or Reference, so there is nothing to apply it to.", details={"path": "candidateId"})
        if round_record.get("target") and round_record["target"] != arguments["target"]:
            raise ImageOperationError("not_found", "That picture was made for a different Story or Reference.")
        if round_record.get("use") != arguments["use"]:
            raise ImageOperationError("invalid_input", f"That picture was made for the {round_record.get('use')} use, not {arguments['use']}.", details={"path": "use"})
        if arguments.get("imageType") and arguments["imageType"] != candidate["imageType"]:
            raise ImageOperationError("image_type_unknown", f"That picture is a {candidate['imageType']}, not a {arguments['imageType']}.")
        story = _story_for(self.client, arguments["target"])
        if story is not None and story["id"] != arguments["expectedCurrentVersionId"]:
            raise ImageOperationError("stale_version", "The Story has changed since you read it. Read it again.", details={"currentVersionId": story["id"]})
        data = self.store.read_file(candidate["filePath"])
        alt = (arguments.get("alt") or (candidate.get("altDraft") or {}).get("text") or "").strip()
        checks = [{"name": "alt-text", "passed": bool(alt)}, *(free_checks(data, candidate["mediaType"]) if data else [{"name": "file", "passed": False}])]
        if not all(check["passed"] for check in checks):
            raise ImageOperationError("checks_failed", "The picture cannot be applied until these checks pass: " + ", ".join(c["name"] for c in checks if not c["passed"]) + ".",
                                      details={"checks": checks})
        if self.media is None:
            raise ImageOperationError("service_unavailable", "Media cannot be written from here.")
        path = f"media/assets/{arguments['target']['lineageId']}/{candidate['id']}.{candidate['mediaType'].split('/')[-1]}"
        person = caller.kind == "person"
        provenance = {"origin": "generated", "candidateId": candidate["id"], "model": candidate["model"], "resolutionHash": candidate["resolutionHash"], "profile": candidate["profile"],
                      "generatedNote": True, "reviewStatus": "human-verified" if person else "unreviewed"}
        asset = self.media.add_media(path=path, data=data, media_type=candidate["mediaType"], alt=alt, caption=arguments.get("caption"), provenance=provenance)
        review_id = None if person else self.media.open_review_request(media_asset_id=asset["id"], target=arguments["target"], candidate_id=candidate["id"], applied_by=caller.subject)
        directive = f'::image{{src="{path}" alt="{alt}"}}'
        patch = {"bodyDirective": directive, "frontMatter": {"image": path} if arguments["use"] == "cover" else {}}
        result: dict = {"patch": patch, "mediaAsset": asset, "imageType": candidate["imageType"], "reviewStatus": provenance["reviewStatus"]}
        if review_id:
            result["reviewRequestId"] = review_id
        if arguments.get("save", True):
            if self.stories is None:
                raise ImageOperationError("service_unavailable", "Story versions cannot be saved from here.")
            result["savedVersion"] = self.stories.save(target=arguments["target"], patch=patch, expected_current_version_id=arguments["expectedCurrentVersionId"], actor=caller.subject)
        self.store.save_candidate({**candidate, "status": "applied", "appliedBy": caller.subject, "appliedAt": self.now(), "mediaAssetId": asset["id"],
                                   "reviewStatus": provenance["reviewStatus"]})
        return Outcome(result, publication)


def generation_handlers(client: Any, store: CandidateStore, providers: dict[str, ImageProvider], **options: Any) -> dict[str, Handler]:
    service = Generation(client, store, providers, **options)
    return {"image_capabilities": service.capabilities, "image_generate": service.generate, "image_round_get": service.round_get,
            "image_discard": service.discard, "image_apply": service.apply}
