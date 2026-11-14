"""Convert a dedicated site's ``projection.json`` to a SiteConfig and back.

A dedicated site's projection.json is a superset of SiteConfig. :func:`to_site_config` splits it into the SiteConfig (the part a shared tenant may set)
and the *rest* (everything else, unchanged), and :func:`from_site_config` puts the two together again, so converting a dedicated site and back gives the
same projection.json and therefore the same pages.

Mapping (projection.json -> SiteConfig):

* ``site.name``, ``site.tagline``, ``site.description`` -> ``name``, ``tagline``, ``purpose``
* ``urls.sections.<name>.base|label|description`` -> ``sections[].slug|label|description``, in order
* ``nav.links[].label|href`` -> ``nav[]``; ``footer.columns`` -> ``footer``
* ``homePage.layout`` -> ``homeTemplate``; ``homePage.threads.enabled`` -> ``features.conversations``; ``embeds.providers`` non-empty -> ``features.videos``

Not in projection.json at all, so never produced by the converter and not written back: ``analyticsId``, ``consentRegionPolicy`` (the site environment
carries them) and the ``findings``, ``concepts`` and ``readerVotes`` feature flags.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping

from .validate import validate_site_config

SECTION_KEYS = ("base", "label", "description")
LINK_KEYS = ("label", "href")
DEFAULT_EMBED_PROVIDERS = ["youtube"]
LINK_EXTRAS = "linkExtras"   # in the rest: link settings SiteConfig does not carry (cta, external, children), by position
BASE_DERIVED = "_baseDerived"  # in the rest: the section had no ``base``; its slug was derived from its name


class ConversionError(ValueError):
    """The projection.json cannot be expressed as a SiteConfig."""


def _links_to_config(links: list, where: str) -> tuple[list[dict], list[dict]]:
    config_links, extras = [], []
    for index, link in enumerate(links):
        if not isinstance(link, Mapping) or not link.get("label") or not link.get("href"):
            raise ConversionError(f"{where}[{index}] needs a label and an href to become a SiteConfig link")
        config_links.append({key: link[key] for key in LINK_KEYS})
        extras.append({key: value for key, value in link.items() if key not in LINK_KEYS})
    return config_links, extras


def _links_from_config(links: list, extras: list | None) -> list[dict]:
    result = []
    for index, link in enumerate(links):
        extra = extras[index] if extras and index < len(extras) else {}
        result.append({**link, **extra})
    return result


def to_site_config(projection: Mapping) -> tuple[dict, dict]:
    """Split ``projection`` into ``(site_config, rest)``. ``rest`` is what a shared tenant cannot set; keep it with the dedicated site."""
    rest = copy.deepcopy(dict(projection))
    site = rest.get("site")
    if not isinstance(site, dict) or not site.get("name"):
        raise ConversionError("projection.json needs site.name")
    config: dict = {"schemaVersion": 1, "name": site.pop("name")}
    for source, target in (("tagline", "tagline"), ("description", "purpose")):
        if source in site:
            config[target] = site.pop(source)

    urls = rest.get("urls") or {}
    sections = urls.get("sections")
    if sections:
        config["sections"] = []
        for name, entry in list(sections.items()):
            entry = dict(entry or {})
            item = {"name": name}
            if "base" in entry:
                item["slug"] = entry.pop("base")
            else:
                item["slug"] = name.lower().replace(" ", "-")
                entry[BASE_DERIVED] = True
            for key in ("label", "description"):
                if key in entry:
                    item[key] = entry.pop(key)
            config["sections"].append(item)
            sections[name] = entry

    nav = rest.get("nav") or {}
    if "links" in nav:
        config["nav"], extras = _links_to_config(nav["links"], "nav.links")
        nav[LINK_EXTRAS] = extras
        del nav["links"]

    footer = rest.get("footer") or {}
    if "columns" in footer:
        config["footer"], all_extras = [], []
        for index, column in enumerate(footer.pop("columns")):
            links, extras = _links_to_config(column.get("links") or [], f"footer.columns[{index}].links")
            entry = {"links": links}
            if "title" in column:
                entry["title"] = column["title"]
            config["footer"].append(entry)
            all_extras.append(extras)
        footer[LINK_EXTRAS] = all_extras

    layout = (rest.get("homePage") or {}).get("layout")
    if layout is not None:
        config["homeTemplate"] = layout
    features: dict = {}
    threads = (rest.get("homePage") or {}).get("threads") or {}
    if "enabled" in threads:
        features["conversations"] = bool(threads["enabled"])
    if "embeds" in rest:
        features["videos"] = bool((rest["embeds"] or {}).get("providers"))
    if features:
        config["features"] = features

    problems = validate_site_config(config)
    if problems:
        raise ConversionError("; ".join(problems))
    return config, rest


def from_site_config(config: Mapping, rest: Mapping | None = None) -> dict:
    """Build a projection.json from ``config`` and the dedicated-only ``rest`` (none for a shared tenant)."""
    problems = validate_site_config(config)
    if problems:
        raise ConversionError("; ".join(problems))
    projection = copy.deepcopy(dict(rest or {}))
    site = projection.setdefault("site", {})
    site["name"] = config["name"]
    for source, target in (("tagline", "tagline"), ("purpose", "description")):
        if source in config:
            site[target] = config[source]

    if "sections" in config:
        previous = (projection.setdefault("urls", {})).get("sections") or {}
        rebuilt = {}
        for item in config["sections"]:
            entry = dict(previous.get(item["name"]) or {})
            if entry.pop(BASE_DERIVED, False) is False:
                entry["base"] = item["slug"]
            elif item["slug"] != item["name"].lower().replace(" ", "-"):
                entry["base"] = item["slug"]
            for key in ("label", "description"):
                if key in item:
                    entry[key] = item[key]
            rebuilt[item["name"]] = entry
        projection["urls"]["sections"] = rebuilt

    if "nav" in config:
        nav = projection.setdefault("nav", {})
        nav["links"] = _links_from_config(config["nav"], nav.pop(LINK_EXTRAS, None))
    if "footer" in config:
        footer = projection.setdefault("footer", {})
        all_extras = footer.pop(LINK_EXTRAS, None) or []
        footer["columns"] = []
        for index, column in enumerate(config["footer"]):
            entry = {key: column[key] for key in ("title",) if key in column}
            entry["links"] = _links_from_config(column["links"], all_extras[index] if index < len(all_extras) else None)
            footer["columns"].append(entry)

    if "homeTemplate" in config:
        projection.setdefault("homePage", {})["layout"] = config["homeTemplate"]
    features = config.get("features") or {}
    if "conversations" in features:
        projection.setdefault("homePage", {}).setdefault("threads", {})["enabled"] = features["conversations"]
    if "videos" in features:
        embeds = projection.setdefault("embeds", {})
        if not features["videos"]:
            embeds["providers"] = []
        elif not embeds.get("providers"):
            embeds["providers"] = list(DEFAULT_EMBED_PROVIDERS)
    return projection
