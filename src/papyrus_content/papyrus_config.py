from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import yaml

from .env import PAPYRUS_ROOT

DEFAULT_PAPYRUS_CONFIG = ".papyrus/config.yaml"
DEFAULT_OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_OPENAI_TTS_VOICE = "alloy"
DEFAULT_PUBLIC_SITE_BASE_URL = "https://p.apyr.us"
DEFAULT_NEWSROOM_REFERENCE_WEB_PATH_PREFIX = "/newsroom/references"
DEFAULT_STEERING_CONFIG_PATH = "corpora/papyrus-steering.yml"
DEFAULT_LEXICAL_STEERING_PATH = "corpora/papyrus-lexical-steering.yml"
DEFAULT_TOPIC_IGNORE_TERMS = (
    "et",
    "al",
    "fig",
    "figure",
    "table",
    "appendix",
    "references",
    "abstract",
    "introduction",
    "preprint",
    "arxiv",
    "doi",
    "http",
    "https",
    "document",
    "candidate",
    "paper",
    "url",
    "research",
)


def resolve_papyrus_config_path(config_path: str | None = None, *, required: bool = False) -> Path | None:
    configured = config_path or os.environ.get("PAPYRUS_CONFIG") or DEFAULT_PAPYRUS_CONFIG
    resolved = Path(configured)
    if not resolved.is_absolute():
        resolved = PAPYRUS_ROOT / resolved
    if not resolved.exists():
        if required or config_path or os.environ.get("PAPYRUS_CONFIG"):
            raise ValueError(f"Papyrus config was not found: {configured}")
        return None
    return resolved


def load_papyrus_config(config_path: str | None = None) -> dict[str, Any] | None:
    resolved = resolve_papyrus_config_path(config_path)
    if resolved is None:
        return None
    parsed = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    return normalize_papyrus_config(parsed, str(resolved))


def normalize_papyrus_config(raw_config: Any, config_path: str) -> dict[str, Any]:
    if not isinstance(raw_config, dict):
        raise ValueError("Papyrus config must be a YAML object.")
    if raw_config.get("schemaVersion") != 1:
        raise ValueError("Papyrus config schemaVersion must be 1.")
    topics = raw_config.get("topics") or {}
    if not isinstance(topics, dict):
        raise ValueError("Papyrus config topics must be an object.")
    ignore_terms = normalize_ignore_terms(topics.get("ignoreTerms"))
    public_site = raw_config.get("publicSite") or {}
    if public_site is not None and not isinstance(public_site, dict):
        raise ValueError("Papyrus config publicSite must be an object.")
    public_site = public_site if isinstance(public_site, dict) else {}
    base_url = _optional_string(public_site.get("baseUrl"))
    if base_url:
        base_url = normalize_public_site_base_url(base_url)
    reader_cache = raw_config.get("readerCache") or {}
    if reader_cache is not None and not isinstance(reader_cache, dict):
        raise ValueError("Papyrus config readerCache must be an object.")
    reader_cache = reader_cache if isinstance(reader_cache, dict) else {}
    openai = raw_config.get("openai") or {}
    if openai is not None and not isinstance(openai, dict):
        raise ValueError("Papyrus config openai must be an object.")
    openai = openai if isinstance(openai, dict) else {}
    return {
        "configPath": config_path,
        "schemaVersion": 1,
        "topics": {
            "steeringConfigPath": _optional_string(topics.get("steeringConfigPath")) or DEFAULT_STEERING_CONFIG_PATH,
            "lexicalConfigPath": _optional_string(topics.get("lexicalConfigPath")) or DEFAULT_LEXICAL_STEERING_PATH,
            "ignoreTerms": ignore_terms or list(DEFAULT_TOPIC_IGNORE_TERMS),
        },
        "publicSite": {
            "baseUrl": base_url,
        },
        "readerCache": {
            "revalidateSecret": _optional_string(reader_cache.get("revalidateSecret")),
        },
        "openai": {
            "apiKey": _optional_string(openai.get("api_key")),
            "model": _optional_string(openai.get("model")) or DEFAULT_OPENAI_TTS_MODEL,
            "voice": _optional_string(openai.get("voice")) or DEFAULT_OPENAI_TTS_VOICE,
            "baseUrl": _optional_string(openai.get("baseUrl")),
        },
    }


def resolve_topics_steering_config_path() -> str:
    config = load_papyrus_config()
    if config:
        return str(config["topics"]["steeringConfigPath"])
    return DEFAULT_STEERING_CONFIG_PATH


def resolve_topics_lexical_config_path() -> str:
    config = load_papyrus_config()
    if config:
        return str(config["topics"]["lexicalConfigPath"])
    return DEFAULT_LEXICAL_STEERING_PATH


def resolve_topics_ignore_terms() -> list[str]:
    config = load_papyrus_config()
    if config:
        return list(config["topics"]["ignoreTerms"] or [])
    return list(DEFAULT_TOPIC_IGNORE_TERMS)


def normalize_public_site_base_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("Public site baseUrl must be a non-empty URL.")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Public site baseUrl must be an absolute http(s) URL.")
    path = (parsed.path or "").rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def resolve_public_site_base_url() -> str:
    env_value = str(os.environ.get("PAPYRUS_PUBLIC_SITE_BASE_URL") or "").strip()
    if env_value:
        return normalize_public_site_base_url(env_value)
    config = load_papyrus_config()
    if config:
        configured = str((config.get("publicSite") or {}).get("baseUrl") or "").strip()
        if configured:
            return configured
    return DEFAULT_PUBLIC_SITE_BASE_URL


def resolve_reader_cache_revalidate_secret() -> str | None:
    env_value = str(os.environ.get("PAPYRUS_REVALIDATE_SECRET") or "").strip()
    if env_value:
        return env_value
    config = load_papyrus_config()
    if config:
        configured = str((config.get("readerCache") or {}).get("revalidateSecret") or "").strip()
        if configured:
            return configured
    return None


def resolve_openai_api_key() -> str | None:
    env_value = str(os.environ.get("OPENAI_API_KEY") or "").strip()
    if env_value:
        return env_value
    config = load_papyrus_config()
    if config:
        configured = str((config.get("openai") or {}).get("apiKey") or "").strip()
        if configured:
            return configured
    return None


def resolve_openai_tts_defaults() -> dict[str, str | None]:
    env_model = str(os.environ.get("OPENAI_TTS_MODEL") or "").strip()
    env_voice = str(os.environ.get("OPENAI_TTS_VOICE") or "").strip()
    env_base_url = str(os.environ.get("OPENAI_BASE_URL") or "").strip()
    config = load_papyrus_config()
    openai = (config or {}).get("openai") or {}
    return {
        "model": env_model or str(openai.get("model") or DEFAULT_OPENAI_TTS_MODEL),
        "voice": env_voice or str(openai.get("voice") or DEFAULT_OPENAI_TTS_VOICE),
        "baseUrl": env_base_url or str(openai.get("baseUrl") or "").strip() or None,
    }


def resolve_reader_revalidation_base_url() -> str:
    env_value = str(os.environ.get("PAPYRUS_BASE_URL") or "").strip().rstrip("/")
    if env_value:
        return env_value
    return resolve_public_site_base_url().rstrip("/")


def build_newsroom_reference_public_url(
    lineage_id: str,
    *,
    base_url: str | None = None,
) -> str | None:
    lineage = str(lineage_id or "").strip()
    if not lineage:
        return None
    base = str(base_url or resolve_public_site_base_url()).rstrip("/")
    encoded = quote(unquote(lineage), safe="")
    return f"{base}{DEFAULT_NEWSROOM_REFERENCE_WEB_PATH_PREFIX}/{encoded}"


def normalize_ignore_terms(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise ValueError("Papyrus config topics.ignoreTerms must be a list.")
    normalized: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw_value):
        term_value = entry
        if isinstance(entry, dict):
            term_value = entry.get("term")
        term = _optional_string(term_value)
        if not term:
            raise ValueError(f"Papyrus config topics.ignoreTerms[{index}] must be a non-empty string.")
        lowered = term.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(lowered)
    return normalized


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
