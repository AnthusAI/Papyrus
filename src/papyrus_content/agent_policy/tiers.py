"""Which model a tier uses (PPY-c9c165, slice G4).

A definition names a tier (``editorial``, ``work``, ``bulk`` or ``decision``), never a model. The site's agent policy document maps a tier to a model
id (``site.tiers``); a tier the site does not map uses the engine's default for it. Changing a model is therefore a new version of the policy, read by
the next run, with no deploy. ``decision`` (the trained decision model) has no engine default: asking for it before the site maps it is an error
that names the tier, never a quiet fall to another model.

Every model a policy maps must be in the price table (``model_cost``), so a model that nothing can price is refused when the policy is saved and
a run's cost is never silently zero.
"""
from __future__ import annotations

from typing import Any, Mapping

from papyrus_content import model_defaults
from papyrus_content.model_cost import load_prices, price_for

#: The engine's model for each tier a site has not mapped. ``decision`` has none on purpose.
ENGINE_TIER_MODELS = {
    "editorial": model_defaults.DEFAULT_EDITORIAL_REWRITE_MODEL,
    "work": model_defaults.DEFAULT_LLM_MODEL,
    "bulk": model_defaults.DEFAULT_SMALL_LLM_MODEL,
}


class TierUnmapped(Exception):
    """The tier has no model: the site's policy does not map it and the engine has no default for it."""


def model_for(document: Mapping[str, Any], tier: str) -> str:
    """The model a run in ``tier`` uses under this policy document."""
    mapped = (document.get("site") or {}).get("tiers", {}).get(tier)
    model = mapped or ENGINE_TIER_MODELS.get(tier)
    if not model:
        raise TierUnmapped(f'The "{tier}" tier has no model: the site policy does not map it (site.tiers.{tier}) and the engine has no default for it.')
    return model


def unpriced(model: str, prices: Mapping[str, Any] | None = None) -> bool:
    """True when the price table has no entry for ``model``."""
    return price_for(model, dict(load_prices() if prices is None else prices)) is None
