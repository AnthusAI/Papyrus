"""The two context files of a pod.

``papyrus.context.jsonld`` is generated here from the relation-types file (the types marked ``pod: true``) and the profile's plain keys, never
edited by hand, and carries the profile version. A pod's copy must be byte-identical to what this module generates, and ``pod check`` compares
them. ``context.jsonld`` is the root context: it marks the folder as level 1, names the id base and declares the site's own keys.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from papyrus_content.relation_types import load_vocabulary_namespace

from . import profile
from .profile import Key

KEYWORDS = {"id": "@id", "type": "@type"}


def _term(key: Key) -> dict | str:
    if key.kind in (profile.LINK, profile.ADDRESS, profile.PREDICATE):
        return {"@id": key.iri, "@type": "@id"}
    if key.kind == profile.LINK_LIST:
        return {"@id": key.iri, "@type": "@id", "@container": "@set"}
    if key.kind == profile.TEXT_LIST:
        return {"@id": key.iri, "@container": "@set"}
    if key.kind == profile.STRING:
        return key.iri
    return {"@id": key.iri, "@type": profile.TERM_TYPES[key.kind]}


def generate(relation_types_path: str | Path | None = None, namespace: str | None = None) -> str:
    """The text of ``papyrus.context.jsonld`` for the relation-types file (the packaged one when no path is given) and the vocabulary namespace
    (the packaged relation-types file's when none is given)."""
    namespace = namespace or load_vocabulary_namespace()
    relation_types = profile.relation_types(relation_types_path)
    terms: dict[str, object] = {"@version": 1.1, **profile.prefixes(namespace), **KEYWORDS}
    for key in (*profile.PLAIN_KEYS, *profile.LINK_KEYS, *profile.RELATION_KEYS):
        terms[key.name] = _term(key)
    for relation_type in relation_types:
        terms[relation_type.key] = {"@id": f"papyrus:{relation_type.key}", "@type": "@id", "@container": "@set"}
    document = {
        "@context": terms,
        "papyrusPod": {
            "profile": profile.PROFILE_VERSION,
            "vaultLd": profile.VAULT_LD_VERSION,
            "vaultLdCommit": profile.VAULT_LD_COMMIT,
            "classes": [f"papyrus:{name}" for name in profile.CLASS_KINDS],
            "generated": "by papyrus pod init from papyrus-semantic-relation-types.yml; never edited by hand",
        },
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def id_base_problem(value: str) -> str | None:
    """Why ``value`` cannot be an id base, or None. An id is the base followed by a random identifier, so the base is an https address ending in a slash."""
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc or parts.query or parts.fragment or any(character.isspace() for character in value):
        return f"{value!r} is not an https address with no query or fragment, such as https://example.org/id/"
    if not value.endswith("/"):
        return f"{value!r} does not end with a slash; an id is the base followed by an identifier, such as https://example.org/id/"
    return None


def namespace_problem(value: str) -> str | None:
    """Why ``value`` cannot be the vocabulary namespace, or None. A term is the namespace followed by its name, so it is an https address ending in ``#`` or ``/``."""
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc or parts.query or any(character.isspace() for character in value) or not value.endswith(("#", "/")):
        return f"{value!r} is not an https address ending in # or /, such as https://example.org/ns#"
    return None


def recorded_namespace(generated: Path) -> str | None:
    """The vocabulary namespace a pod's generated context records, or None when it is missing or unreadable."""
    try:
        terms = json.loads(generated.read_text(encoding="utf-8"))["@context"]
        value = terms[profile.NAMESPACE_PREFIX]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return value if isinstance(value, str) and namespace_problem(value) is None else None


def root_context(id_base: str) -> str:
    """The text of a new ``context.jsonld``: the id base and no site keys yet."""
    document = {"@context": [profile.PROFILE_CONTEXT_FILE, {"@base": id_base}]}
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


@dataclass
class RootContext:
    """What ``context.jsonld`` says: the id base and the site's own keys (name -> Key)."""

    id_base: str = ""
    site_keys: dict[str, Key] = field(default_factory=dict)


def _is_prefix(value: object) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://")) and value.endswith(("/", "#"))


def read_root(path: Path) -> tuple[RootContext, list[str]]:
    """Read and validate a root context file: (what it declares, the problems found). The content is whatever was usable, so one bad key does not hide the rest."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return RootContext(), [f"is not readable JSON: {error}"]
    entries = document.get("@context") if isinstance(document, dict) else None
    if not isinstance(entries, list) or not entries or entries[0] != profile.PROFILE_CONTEXT_FILE:
        return RootContext(), [f'must be {{"@context": ["{profile.PROFILE_CONTEXT_FILE}", {{...}}]}}: the first entry names the generated context']
    problems: list[str] = []
    root = RootContext()
    prefixes = set(profile.PREFIX_NAMES)
    declarations = entries[1:]
    for entry in declarations:
        if not isinstance(entry, dict):
            problems.append("lists an entry that is not an object; only the generated context is named by file")
            continue
        for name, value in entry.items():
            if name == "@base":
                if isinstance(value, str) and id_base_problem(value) is None:
                    root.id_base = value
                else:
                    problems.append(f"@base is not a usable id base: {id_base_problem(value) if isinstance(value, str) else 'it must be text'}")
            elif _is_prefix(value):
                prefixes.add(name)
    for entry in declarations:
        if not isinstance(entry, dict):
            continue
        for name, value in entry.items():
            if name.startswith("@") or _is_prefix(value):
                continue
            key, problem = _site_key(name, value, prefixes)
            if problem:
                problems.append(f"key {name!r} {problem}")
            elif key is not None:
                root.site_keys[name] = key
    if not root.id_base and not any("@base" in problem for problem in problems):
        problems.append("does not name the id base: add {\"@base\": \"https://example.org/id/\"}")
    return root, problems


def reserved_names(relation_types_path: str | Path | None = None) -> set[str]:
    names = {key.name for key in (*profile.PLAIN_KEYS, *profile.LINK_KEYS, *profile.RELATION_KEYS)}
    names |= {relation_type.key for relation_type in profile.relation_types(relation_types_path)} | set(KEYWORDS)
    return names


def _site_key(name: str, value: object, prefixes: set[str]) -> tuple[Key | None, str | None]:
    if name in reserved_names():
        return None, "is already defined by the Papyrus profile; a site declares only its own keys"
    if isinstance(value, str):
        return (Key(name, value, profile.STRING), None) if _iri_ok(value, prefixes) else (None, f"needs an address such as site:{name} with a declared prefix")
    if not isinstance(value, dict) or not isinstance(value.get("@id"), str) or not _iri_ok(value["@id"], prefixes):
        return None, "must be an address or an object with an @id address such as site:name with a declared prefix"
    unsupported = set(value) - {"@id", "@type", "@container"}
    if unsupported:
        return None, f"uses {sorted(unsupported)[0]}, which the profile does not support (only @id, @type and @container)"
    container = value.get("@container")
    if container not in (None, "@set"):
        return None, "uses a @container other than @set"
    declared = value.get("@type")
    if declared == "@id":
        return Key(name, value["@id"], profile.LINK_LIST if container else profile.LINK), None
    if declared is None:
        return Key(name, value["@id"], profile.TEXT_LIST if container else profile.STRING), None
    kind = profile.XSD_KINDS.get(declared)
    if kind is None:
        return None, f"has the type {declared!r}; use @id or one of {', '.join(profile.XSD_KINDS)}"
    if container:
        return None, "is a list of typed values, which the profile does not support; use @id or plain text for lists"
    return Key(name, value["@id"], kind), None


def _iri_ok(value: str, prefixes: set[str]) -> bool:
    if value.startswith(("http://", "https://")):
        return True
    prefix, separator, rest = value.partition(":")
    return bool(separator and rest and prefix in prefixes)
