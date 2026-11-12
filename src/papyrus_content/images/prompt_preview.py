"""image_prompt_preview: the exact request an image model would receive, with where every part came from and what it would cost, made without calling a provider.

The request is compiled from the resolved image guidelines (publication layer, section layer, image type, use) through the fixed skeleton in
``prompt_skeleton.py``. It can be asked for with a Story or Reference target, with only a section, or with neither (a private round for ad assets and
section art, where there is nothing to apply). Nothing here reads a provider, writes a record or spends money.
"""
from __future__ import annotations

from typing import Any

from .handlers import Caller, ImageOperationError, Outcome
from .image_prices import estimate_cost
from .profile_handlers import _publication, resolve_for_request
from .prompt_skeleton import compose_plan
from .visual_style import StyleError

UNATTENDED_COUNT = 1
SET_COUNT = 4


def capabilities_of(client: Any) -> dict:
    """What this site may use for generation. A site with nothing configured answers not configured, and spends nothing."""
    reader = getattr(client, "image_generation_settings", None)
    settings = reader() if callable(reader) else None
    return settings or {"configured": False, "models": [], "approvedForSpend": False}


def capability_check(settings: dict, model: str | None, speed: str, count: int) -> dict:
    if not settings.get("configured") or not settings.get("models"):
        return {"ok": False, "reason": "generation_not_configured", "message": "This site has no approved image model, so nothing can be generated yet.",
                "approvedForSpend": bool(settings.get("approvedForSpend"))}
    names = [entry.get("name") for entry in settings["models"]]
    chosen = model or names[0]
    if chosen not in names:
        return {"ok": False, "reason": "capability_unsupported", "message": f"{chosen} is not a model this site has approved.", "approvedForSpend": bool(settings.get("approvedForSpend")),
                "alternatives": names}
    return {"ok": True, "model": chosen, "speed": speed, "count": count, "approvedForSpend": bool(settings.get("approvedForSpend"))}


def _count_for(arguments: dict, caller: Caller) -> int:
    asked = int(arguments.get("count") or 1)
    if caller.kind == "agent" and asked > UNATTENDED_COUNT:
        raise ImageOperationError("set_needs_person", "A set of pictures is for a person choosing. Unattended work makes one picture.", details={"asked": asked})
    return asked


def _types_to_plan(client: Any, arguments: dict) -> list[str | None]:
    if arguments.get("spread") != "types":
        return [arguments.get("imageType")]
    named = arguments.get("imageTypes")
    if named:
        return list(named)
    resolved, _ = resolve_for_request(client, {k: v for k, v in arguments.items() if k in ("target", "sectionId", "use")}, operation="resolve")
    return [row["key"] for row in resolved["availableTypes"] if "generated" in (row.get("sources") or [])]


def preview_prompt(client, arguments: dict, caller: Caller, files=None) -> Outcome:
    publication = _publication(client)
    count = _count_for(arguments, caller)
    speed = arguments.get("speed") or "auto"
    plans: list[dict] = []
    warnings: list[dict] = []
    for image_type in _types_to_plan(client, arguments):
        request = {key: arguments[key] for key in ("target", "sectionId", "use") if arguments.get(key)}
        if image_type:
            request["imageType"] = image_type
        try:
            resolved, found = resolve_for_request(client, request, operation="generate", section_fields="visualStyle", files=files)
        except StyleError as error:
            raise ImageOperationError(error.code, error.message, details=error.details) from error
        for warning in found:
            if warning not in warnings:
                warnings.append(warning)
        plan = compose_plan(resolved, arguments["brief"])
        plan = {**plan, "imageTypeChosenBy": resolved["imageTypeChosenBy"], "fieldSources": resolved["fieldSources"], "layers": resolved["layers"],
                "private": not arguments.get("target")}
        repeats = count if arguments.get("spread") != "types" else 1
        plans.extend({**plan, "position": len(plans) + offset} for offset in range(repeats))
    settings = capabilities_of(client)
    check = capability_check(settings, arguments.get("model"), speed, len(plans))
    estimate = estimate_cost(check.get("model") or arguments.get("model"), len(plans), speed)
    return Outcome({"plans": plans, "estimate": estimate, "capabilityCheck": check}, publication, tuple(warnings))
