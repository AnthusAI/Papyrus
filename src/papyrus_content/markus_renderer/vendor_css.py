"""Vendor Markus CSS and wrap it in ``@layer markus`` for deterministic cascade."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def resolve_markus_static_dir() -> Path:
    spec = importlib.util.find_spec("markusmd")
    if spec is None or not spec.origin:
        raise RuntimeError(
            "markusmd package not found. Install Markus v0.5.0: "
            'pip install "git+https://github.com/AnthusAI/Markus@v0.5.0"'
        )
    static_dir = Path(spec.origin).parent / "static"
    if not static_dir.is_dir():
        raise RuntimeError(f"Markus static directory missing: {static_dir}")
    return static_dir


def wrap_layer(css_text: str) -> str:
    return f"@layer markus {{\n{css_text}\n}}\n"


def vendor_markus_css(
    dest: Path,
    *,
    theme: str | None = None,
) -> None:
    """Write bundled vendor CSS (base + optional theme) wrapped in ``@layer markus``."""
    static_dir = resolve_markus_static_dir()
    base_css = (static_dir / "markus.css").read_text(encoding="utf-8")
    parts = [wrap_layer(base_css)]

    if theme:
        theme_path = static_dir / "themes" / f"{theme}.css"
        if not theme_path.is_file():
            available = sorted(path.stem for path in (static_dir / "themes").glob("*.css"))
            raise RuntimeError(
                f"Markus theme {theme!r} not found. Available: {', '.join(available)}"
            )
        parts.append(wrap_layer(theme_path.read_text(encoding="utf-8")))

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(parts), encoding="utf-8")
