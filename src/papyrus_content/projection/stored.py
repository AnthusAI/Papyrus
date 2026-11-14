"""The projection metadata stored on a ``PublishedItem`` at publish time.

Front matter is parsed once, when the item is published, and kept as JSON
under ``metadata.projection``. A projection that needs every item's front
matter (listing pages, collections) reads that JSON instead of parsing YAML
again on every invocation.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from ..markus_renderer.derive import compose_source
from ..markus_renderer.pages import read_title

PROJECTION_METADATA_KEY = "projection"


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def parse_front_matter(front_matter_yaml: str | None) -> dict:
    if not front_matter_yaml or not front_matter_yaml.strip():
        return {}
    import yaml

    loaded = yaml.safe_load(front_matter_yaml)
    if not isinstance(loaded, dict):
        return {}
    return json.loads(json.dumps(loaded, default=_json_default))


_CARD_IMAGE_KEYS = ("image", "cover", "ogImage", "thumbnail")
_NIGHT_IMAGE_KEYS = ("imageDark", "coverDark", "thumbnailDark")
FRONT_MATTER_IMAGE_KEYS = _CARD_IMAGE_KEYS + _NIGHT_IMAGE_KEYS
_RENDITION_TAIL = re.compile(r"\d+\.\w+")


def _split_source(path: str) -> tuple[str, str]:
    """``assets/slug/chart.png`` -> ``("assets/slug", "chart")``."""
    folder, _, name = path.strip().lstrip("/").rpartition("/")
    return folder, name.rpartition(".")[0] or name


def night_image_for(card_image: str, body_markus: str) -> str | None:
    """The Night picture of the card's picture, when the card shows a figure of the body that has a ``srcDark``.

    The card's picture is the figure's source file or one of its renditions (``assets/responsive/<folder>/<stem>-<width>.<ext>``);
    the Night one is the same file or rendition of ``srcDark``. A figure whose pair is not named gives nothing."""
    from ..markus_renderer.content_markup import _ATTR_RE, _IMAGE_DIRECTIVE_RE

    for directive in _IMAGE_DIRECTIVE_RE.finditer(body_markus or ""):
        attributes = {m.group("key"): next(v for v in (m.group("dq"), m.group("sq"), m.group("bare")) if v is not None) for m in _ATTR_RE.finditer(directive.group("attrs"))}
        light, dark = attributes.get("src", ""), attributes.get("srcDark", "")
        if not light or not dark or "://" in light or "://" in dark:
            continue
        shown = card_image.split("?")[0]
        if shown.lstrip("/") == light.lstrip("/"):
            return shown[: len(shown) - len(shown.lstrip("/"))] + dark.lstrip("/")
        folder, stem = _split_source(light)
        dark_folder, dark_stem = _split_source(dark)
        key = "/".join(part for part in (folder, stem) if part) + "-"
        at = shown.find(key)
        if at != -1 and (at == 0 or shown[at - 1] == "/") and _RENDITION_TAIL.fullmatch(shown[at + len(key):]):
            return shown[:at] + "/".join(part for part in (dark_folder, dark_stem) if part) + "-" + shown[at + len(key):]
    return None


def projection_metadata(front_matter_yaml: str | None, body_markus: str | None = None) -> dict:
    """What a listing reads. With the body, a card image that is a figure with a Day and Night pair also stores its Night picture as ``imageDark`` (an author's own ``imageDark`` stays)."""
    front_matter = parse_front_matter(front_matter_yaml)
    if body_markus and not any(front_matter.get(key) for key in _NIGHT_IMAGE_KEYS):
        shown = next((str(front_matter[key]) for key in _CARD_IMAGE_KEYS if front_matter.get(key)), "")
        night = night_image_for(shown, body_markus) if shown else None
        if night:
            front_matter["imageDark"] = night
    return {
        "frontMatter": front_matter,
        "pageTitle": read_title(compose_source(front_matter_yaml, ""), None),
    }
