"""Papyrus shim: editorial style profiles are implemented in Limatus."""

from __future__ import annotations

from limatus.editorial_style import *  # noqa: F403

from .env import PAPYRUS_ROOT

DEFAULT_ANTHUS_STYLE_PROFILE_PATH = PAPYRUS_ROOT / "publications" / "anthus" / "style-profile.yml"
