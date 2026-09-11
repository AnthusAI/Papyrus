"""Papyrus shim: editorial rewrite options are implemented in Limatus."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from limatus.editorial_rewrite_options import (
    DEFAULT_EDITORIAL_REWRITE_MODEL,
    EditorialRewriteSkill,
    MAX_SUGGESTION_OUTPUT_TOKENS,
    OptionsResolver,
    generate_rewrite_options as _generate_rewrite_options,
    generate_rewrite_suggestions,
    generate_suggestions,
    load_rewrite_skill,
    options_contain_evasion_tactics,
    suggestions_contain_evasion_tactics,
)

from .env import PAPYRUS_ROOT

DEFAULT_EDITORIAL_REWRITE_SKILL_PATH = (
    PAPYRUS_ROOT / "publications" / "anthus" / "editorial-rewrite-skill.yml"
)


def generate_rewrite_options(
    draft_text: str,
    *,
    style_profile: Any,
    diagnosis: dict[str, Any],
    decisions: list[dict[str, Any]],
    model: str = DEFAULT_EDITORIAL_REWRITE_MODEL,
    skill_path: str | Path | None = None,
    llm_resolver: OptionsResolver | None = None,
) -> dict[str, Any]:
    resolved_skill = Path(skill_path or DEFAULT_EDITORIAL_REWRITE_SKILL_PATH).resolve()
    return _generate_rewrite_options(
        draft_text,
        style_profile=style_profile,
        diagnosis=diagnosis,
        decisions=decisions,
        model=model,
        skill_path=resolved_skill,
        llm_resolver=llm_resolver,
    )


__all__ = [
    "DEFAULT_EDITORIAL_REWRITE_MODEL",
    "DEFAULT_EDITORIAL_REWRITE_SKILL_PATH",
    "EditorialRewriteSkill",
    "MAX_SUGGESTION_OUTPUT_TOKENS",
    "OptionsResolver",
    "generate_rewrite_options",
    "generate_rewrite_suggestions",
    "generate_suggestions",
    "load_rewrite_skill",
    "options_contain_evasion_tactics",
    "suggestions_contain_evasion_tactics",
]
