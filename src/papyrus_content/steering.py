from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .env import PAPYRUS_ROOT
from .papyrus_config import DEFAULT_STEERING_CONFIG_PATH, resolve_topics_steering_config_path
from .relevance_cyclotron import normalize_relevance_cyclotron_config

DEFAULT_STEERING_CONFIG = DEFAULT_STEERING_CONFIG_PATH
VALID_CORPUS_ROLES = frozenset({"canonical", "source", "supporting", "archive"})


def resolve_steering_config_path(config_path: str | None = None) -> Path | None:
    configured = config_path or os.environ.get("PAPYRUS_STEERING_CONFIG") or resolve_topics_steering_config_path()
    resolved = Path(configured)
    if not resolved.is_absolute():
        resolved = PAPYRUS_ROOT / resolved
    if not resolved.exists():
        if config_path or os.environ.get("PAPYRUS_STEERING_CONFIG"):
            raise ValueError(f"Steering config was not found: {configured}")
        return None
    return resolved


def load_steering_config(config_path: str | None = None) -> dict[str, Any] | None:
    resolved = resolve_steering_config_path(config_path)
    if resolved is None:
        return None
    parsed = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    return normalize_steering_config(parsed, str(resolved))


def require_steering_config(config_path: str | None = None) -> dict[str, Any]:
    config = load_steering_config(config_path)
    if config is None:
        raise ValueError(f"Steering config was not found: {DEFAULT_STEERING_CONFIG}")
    return config


def normalize_steering_config(raw_config: Any, config_path: str) -> dict[str, Any]:
    if not isinstance(raw_config, dict):
        raise ValueError("Steering config must be a YAML object.")
    if raw_config.get("schemaVersion") != 1:
        raise ValueError("Steering config schemaVersion must be 1.")

    canonical_topic_set = raw_config.get("canonicalTopicSet") or {}
    canonical_corpus_key = _required_string(canonical_topic_set.get("corpusKey"), "canonicalTopicSet.corpusKey")
    canonical_classifier_id = _required_string(
        canonical_topic_set.get("classifierId"),
        "canonicalTopicSet.classifierId",
    )
    corpora = raw_config.get("corpora")
    if not isinstance(corpora, list) or not corpora:
        raise ValueError("Steering config corpora must include at least one corpus.")

    seen_keys: set[str] = set()
    normalized_corpora = [
        normalize_corpus_config(corpus, index, seen_keys) for index, corpus in enumerate(corpora)
    ]
    if not any(corpus["key"] == canonical_corpus_key for corpus in normalized_corpora):
        raise ValueError(f"canonicalTopicSet.corpusKey does not match a configured corpus: {canonical_corpus_key}")

    publication = raw_config.get("publication") or {}
    return {
        "configPath": config_path,
        "schemaVersion": 1,
        "publication": {"name": _optional_string(publication.get("name")) or "Papyrus"},
        "canonicalTopicSet": {
            "corpusKey": canonical_corpus_key,
            "classifierId": canonical_classifier_id,
        },
        "corpora": normalized_corpora,
        "relevanceCyclotron": normalize_relevance_cyclotron_config(raw_config.get("relevanceCyclotron")),
    }


def normalize_corpus_config(corpus: Any, index: int, seen_keys: set[str]) -> dict[str, Any]:
    if not isinstance(corpus, dict):
        raise ValueError(f"corpora[{index}] must be an object.")
    key = _required_string(corpus.get("key"), f"corpora[{index}].key")
    if key in seen_keys:
        raise ValueError(f"Duplicate corpus key in steering config: {key}")
    seen_keys.add(key)

    role = _optional_string(corpus.get("role")) or "source"
    if role not in VALID_CORPUS_ROLES:
        raise ValueError(f"Unsupported role for corpus {key}: {role}")

    local_classifiers = []
    for classifier_index, classifier in enumerate(corpus.get("localClassifiers") or []):
        classifier_id = _required_string(
            (classifier or {}).get("classifierId"),
            f"corpora[{index}].localClassifiers[{classifier_index}].classifierId",
        )
        local_classifiers.append(
            {
                "classifierId": classifier_id,
                "label": _optional_string((classifier or {}).get("label")) or classifier_id,
            }
        )

    canonical_projection = None
    projection = corpus.get("canonicalProjection")
    if isinstance(projection, dict):
        canonical_projection = {
            "authorityCorpusKey": _required_string(
                projection.get("authorityCorpusKey"),
                f"corpora[{index}].canonicalProjection.authorityCorpusKey",
            ),
            "classifierId": _required_string(
                projection.get("classifierId"),
                f"corpora[{index}].canonicalProjection.classifierId",
            ),
        }

    return {
        "key": key,
        "name": _optional_string(corpus.get("name")) or key,
        "path": _optional_string(corpus.get("path")),
        "s3Prefix": _optional_string(corpus.get("s3Prefix")),
        "role": role,
        "localClassifiers": local_classifiers,
        "canonicalProjection": canonical_projection,
    }


def find_corpus_config(config: dict[str, Any], corpus_key: str) -> dict[str, Any] | None:
    return next((corpus for corpus in config.get("corpora", []) if corpus.get("key") == corpus_key), None)


def require_corpus_config(config: dict[str, Any], corpus_key: str, field_name: str = "corpus key") -> dict[str, Any]:
    corpus = find_corpus_config(config, corpus_key)
    if corpus is None:
        raise ValueError(f"Unknown {field_name}: {corpus_key}")
    return corpus


def resolve_classifier_for_corpus(config: dict[str, Any], corpus: dict[str, Any], explicit_classifier: str | None) -> str:
    if explicit_classifier:
        return explicit_classifier
    if corpus.get("key") == config["canonicalTopicSet"]["corpusKey"]:
        return config["canonicalTopicSet"]["classifierId"]
    local_classifiers = corpus.get("localClassifiers") or []
    if len(local_classifiers) == 1:
        return local_classifiers[0]["classifierId"]
    raise ValueError(
        f"--classifier is required for corpus {corpus['key']}; config does not identify exactly one classifier."
    )


def selected_corpus_configs(config: dict[str, Any], corpus_key: str | None) -> list[dict[str, Any]]:
    if corpus_key:
        return [require_corpus_config(config, corpus_key, "--corpus-key")]
    return list(config.get("corpora") or [])


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required.")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def looks_like_biblicus_project(path: Path) -> bool:
    if not path.exists():
        return False
    if (path / "src" / "biblicus").is_dir():
        return True
    pyproject = path / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        return "biblicus" in pyproject.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False


def resolve_corpus_local_path(corpus: dict[str, Any], steering_config: dict[str, Any]) -> Path:
    config_path = steering_config.get("configPath")
    if not isinstance(config_path, str) or not config_path.strip():
        raise ValueError("steering_config.configPath is required to resolve corpus local path.")
    steering_dir = Path(config_path).resolve().parent
    corpus_path_value = corpus.get("path")
    if not isinstance(corpus_path_value, str) or not corpus_path_value.strip():
        raise ValueError(f"Corpus {corpus.get('key')} has no path in steering config.")
    configured = Path(corpus_path_value.strip())
    if configured.is_absolute():
        resolved = configured.resolve()
    elif configured.parts and configured.parts[0] == "corpora" and steering_dir.name == "corpora":
        resolved = (steering_dir.parent / configured).resolve()
    else:
        resolved = (steering_dir / configured).resolve()
    if not resolved.exists():
        from .corpus_storage_paths import (
            corpus_storage_path_prefix,
            corpus_storage_segment,
            legacy_corpus_storage_segment,
            legacy_mixed_case_corpus_segment,
        )

        corpus_key = str(corpus.get("key") or "")
        fallbacks = []
        if corpus_key:
            fallbacks.append((steering_dir.parent / corpus_storage_path_prefix(corpus_key)).resolve())
            fallbacks.append(
                (
                    steering_dir.parent
                    / f"corpora/{legacy_mixed_case_corpus_segment(corpus_storage_segment(corpus_key))}"
                ).resolve()
            )
            fallbacks.append((steering_dir.parent / f"corpora/{legacy_corpus_storage_segment(corpus_key)}").resolve())
        for candidate in fallbacks:
            if candidate.exists():
                return candidate
        raise ValueError(f"Corpus path does not exist: {resolved}")
    return resolved


def resolve_biblicus_runtime_dir(options: dict[str, Any]) -> Path:
    from .env import BIBLICUS_ROOT

    raw = _optional_string(options.get("biblicus-workdir")) or _optional_string(options.get("biblicusWorkdir"))
    candidate = Path(raw) if raw else BIBLICUS_ROOT
    resolved = candidate.expanduser().resolve()
    if looks_like_biblicus_project(resolved):
        return resolved
    sibling = (PAPYRUS_ROOT.parent / "Biblicus").resolve()
    if looks_like_biblicus_project(sibling):
        return sibling
    raise ValueError(
        f"Biblicus project directory was not found at {resolved}. "
        "Set --biblicus-workdir to a Biblicus checkout (with src/biblicus/)."
    )


def find_corpus_config_by_path(config: dict[str, Any] | None, corpus_path: str | None) -> dict[str, Any] | None:
    if not config or not corpus_path:
        return None
    normalized = corpus_path.rstrip("/")
    for corpus in config.get("corpora") or []:
        path_value = corpus.get("path")
        if not path_value:
            continue
        if path_value == normalized or path_value.rstrip("/") == normalized:
            return corpus
        if normalized.endswith(path_value.rstrip("/")):
            return corpus
    return None


def resolve_steering_import_corpus(config: dict[str, Any] | None, options: dict[str, Any]) -> dict[str, Any]:
    if options.get("corpus-key"):
        required_config = config or require_steering_config(options.get("config"))
        corpus_config = require_corpus_config(required_config, options["corpus-key"], "--corpus-key")
        return {
            "corpusConfig": corpus_config,
            "corpusPath": options.get("corpus") or corpus_config.get("path"),
            "classifierId": resolve_classifier_for_corpus(
                required_config,
                corpus_config,
                options.get("classifier"),
            ),
        }
    corpus_config = find_corpus_config_by_path(config, options.get("corpus"))
    classifier_id = options.get("classifier")
    if not classifier_id and corpus_config and config:
        classifier_id = resolve_classifier_for_corpus(config, corpus_config, None)
    return {
        "corpusConfig": corpus_config,
        "corpusPath": options.get("corpus"),
        "classifierId": classifier_id,
    }


def resolve_projection_import_corpora(config: dict[str, Any] | None, options: dict[str, Any]) -> dict[str, Any]:
    from .ids import knowledge_corpus_id

    target_corpus = None
    authority_corpus = None
    if options.get("target-corpus-key"):
        required_config = config or require_steering_config(options.get("config"))
        target_corpus = require_corpus_config(required_config, options["target-corpus-key"], "--target-corpus-key")
        authority_key = options.get("authority-corpus-key") or (
            (target_corpus.get("canonicalProjection") or {}).get("authorityCorpusKey")
        )
        if authority_key:
            authority_corpus = require_corpus_config(required_config, authority_key, "--authority-corpus-key")
        classifier_id = (
            options.get("classifier")
            or (target_corpus.get("canonicalProjection") or {}).get("classifierId")
            or required_config["canonicalTopicSet"]["classifierId"]
        )
        return {
            "targetCorpus": target_corpus,
            "authorityCorpus": authority_corpus,
            "targetCorpusId": options.get("target-corpus-id") or knowledge_corpus_id(target_corpus),
            "authorityCorpusId": options.get("authority-corpus-id")
            or (knowledge_corpus_id(authority_corpus) if authority_corpus else None),
            "classifierId": classifier_id,
        }
    if options.get("authority-corpus-key"):
        required_config = config or require_steering_config(options.get("config"))
        authority_corpus = require_corpus_config(required_config, options["authority-corpus-key"], "--authority-corpus-key")
    return {
        "targetCorpus": target_corpus,
        "authorityCorpus": authority_corpus,
        "targetCorpusId": options.get("target-corpus-id"),
        "authorityCorpusId": options.get("authority-corpus-id")
        or (knowledge_corpus_id(authority_corpus) if authority_corpus else None),
        "classifierId": options.get("classifier"),
    }
