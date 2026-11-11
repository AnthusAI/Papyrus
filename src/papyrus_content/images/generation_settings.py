"""A site's image generation settings: the ``generation`` field of the publication's image guidelines, and nothing else.

Only the publication layer holds it. A section's document cannot override it, the same as a binding constraint, and an agent cannot change what spending
is allowed (profile_handlers.save_profile answers ``human_required``). The default is nothing configured and spend not approved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from papyrus_content.guidelines.document import GuidelineError

from .profile_store import read_current_profile

SPEND_FIELDS = ("spendApproved", "perRoundCeilingUsd", "perDayCeilingUsd")
GENERATION_FIELDS = frozenset({"models", "spendApproved", "unreviewedMayPublish", "perRoundCeilingUsd", "perDayCeilingUsd", "interactiveCount"})
MODEL_FIELDS = frozenset({"provider", "name", "quality"})


@dataclass(frozen=True)
class GenerationSettings:
    models: tuple[dict, ...] = field(default_factory=tuple)
    spend_approved: bool = False
    unreviewed_may_publish: bool = False
    per_round_ceiling_usd: float | None = None
    per_day_ceiling_usd: float | None = None

    @property
    def configured(self) -> bool:
        return bool(self.models)

    def public(self) -> dict:
        return {"configured": self.configured, "models": [dict(model) for model in self.models], "approvedForSpend": self.spend_approved,
                "unreviewedMayPublish": self.unreviewed_may_publish,
                "spendCeilings": {"perRoundUsd": self.per_round_ceiling_usd, "perDayUsd": self.per_day_ceiling_usd}}


def settings_from(document: dict | None) -> GenerationSettings:
    raw = (document or {}).get("generation")
    raw = raw if isinstance(raw, dict) else {}
    models = tuple(dict(model) for model in raw.get("models") or [] if isinstance(model, dict) and model.get("name") and model.get("provider"))
    return GenerationSettings(models, raw.get("spendApproved") is True, raw.get("unreviewedMayPublish") is True,
                              raw.get("perRoundCeilingUsd"), raw.get("perDayCeilingUsd"))


def read_settings(client: Any, files=None) -> GenerationSettings:
    try:
        document, _, _ = read_current_profile(client, files)
    except GuidelineError:
        return GenerationSettings()
    return settings_from(document)


def spend_fields_of(document: dict | None) -> dict:
    generation = (document or {}).get("generation")
    generation = generation if isinstance(generation, dict) else {}
    return {name: generation.get(name) for name in SPEND_FIELDS}


def check_generation(value: Any, add) -> None:
    """Problems with a ``generation`` field, reported through ``add(path, message)``."""
    if not isinstance(value, dict):
        return
    for name in value:
        if name not in GENERATION_FIELDS:
            add(f"generation.{name}", f"{name} is not a generation setting.")
    for name in ("spendApproved", "unreviewedMayPublish"):
        if name in value and not isinstance(value[name], bool):
            add(f"generation.{name}", f"{name} must be true or false.")
    for name in ("perRoundCeilingUsd", "perDayCeilingUsd"):
        if name in value and (isinstance(value[name], bool) or not isinstance(value[name], (int, float)) or value[name] < 0):
            add(f"generation.{name}", f"{name} must be a number of dollars, zero or more.")
    if "models" in value:
        if not isinstance(value["models"], list):
            add("generation.models", "models must be a list, most preferred first.")
            return
        for index, model in enumerate(value["models"]):
            where = f"generation.models[{index}]"
            if not isinstance(model, dict) or not model.get("provider") or not model.get("name"):
                add(where, "Each model needs a provider and a name.")
                continue
            for name in model:
                if name not in MODEL_FIELDS:
                    add(f"{where}.{name}", f"{name} is not a model setting.")
