"""The pod profile: what a note may say, pinned in one place.

Profile version 1 pins Vault-LD 0.5.0 at commit 025e71b. A new Vault-LD release changes nothing here until this pin moves. Lifecycle keys
(``stage``, ``rating`` and the review stamps) are not part of version 1.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROFILE_VERSION = 1
VAULT_LD_VERSION = "0.5.0"
VAULT_LD_COMMIT = "025e71b"

CONTEXT_FILE = "context.jsonld"
PROFILE_CONTEXT_FILE = "papyrus.context.jsonld"

# The classes a note may have, as `type: papyrus:<Class>`, and the relation-type kind each one is when it is the end of a link.
CLASS_KINDS: dict[str, str | None] = {
    "Article": "item",
    "Post": "item",
    "Page": "item",
    "Reference": "reference",
    "Concept": "semanticNode",
    "Person": "semanticNode",
    "Organization": "semanticNode",
    "Section": None,       # reached only through the `section` key
    "Relation": "semanticRelation",
}
CLASS_PREFIX = "papyrus:"

STRING, TEXT_LIST, DATE, BOOLEAN, INTEGER, DECIMAL = "string", "string-list", "date", "boolean", "integer", "decimal"
LINK, LINK_LIST, ADDRESS, PREDICATE = "link", "link-list", "address", "predicate"


@dataclass(frozen=True)
class Key:
    name: str
    iri: str
    kind: str


# Plain keys (facts), in the order the context file lists them.
PLAIN_KEYS: tuple[Key, ...] = (
    Key("title", "schema:name", STRING),
    Key("description", "schema:description", STRING),
    Key("date", "schema:datePublished", DATE),
    Key("updated", "schema:dateModified", DATE),
    Key("authors", "schema:author", TEXT_LIST),
    Key("publisher", "schema:publisher", STRING),
    Key("image", "schema:image", STRING),
    Key("tags", "papyrus:tag", TEXT_LIST),
    Key("aliases", "schema:alternateName", TEXT_LIST),
    Key("definition", "skos:definition", STRING),
    Key("language", "schema:inLanguage", STRING),
    Key("draft", "papyrus:draft", BOOLEAN),
    Key("redirects", "papyrus:redirect", TEXT_LIST),
)

# Link keys other than the relation types: `section` points at a note, `url` is an outside address.
LINK_KEYS: tuple[Key, ...] = (
    Key("section", "papyrus:section", LINK),
    Key("url", "schema:url", ADDRESS),
)

# The keys of a Relation note (one link that carries words, a state or a date). The words go in the body.
RELATION_KEYS: tuple[Key, ...] = (
    Key("from", "rdf:subject", LINK),
    Key("relation", "rdf:predicate", PREDICATE),
    Key("to", "rdf:object", LINK),
    Key("state", "papyrus:state", STRING),
    Key("decidedOn", "papyrus:decidedOn", DATE),
    Key("decidedBy", "papyrus:decidedBy", STRING),
)
RELATION_STATES = ("current", "suggested", "rejected")

# The `papyrus` prefix is the pod's own vocabulary namespace (chosen at `pod init`, recorded in its generated context); the rest are fixed.
NAMESPACE_PREFIX = "papyrus"
FIXED_PREFIXES = {
    "schema": "https://schema.org/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}
PREFIX_NAMES = frozenset({NAMESPACE_PREFIX, *FIXED_PREFIXES})


def prefixes(namespace: str) -> dict[str, str]:
    """The context's prefixes, the pod's vocabulary namespace first."""
    return {NAMESPACE_PREFIX: namespace, **FIXED_PREFIXES}


XSD_KINDS = {"xsd:string": STRING, "xsd:integer": INTEGER, "xsd:decimal": DECIMAL, "xsd:boolean": BOOLEAN, "xsd:date": DATE, "xsd:dateTime": DATE}

TERM_TYPES = {STRING: "xsd:string", DATE: "xsd:date", BOOLEAN: "xsd:boolean", INTEGER: "xsd:integer", DECIMAL: "xsd:decimal"}


@dataclass(frozen=True)
class RelationType:
    key: str
    subject_kinds: tuple[str, ...]
    object_kinds: tuple[str, ...]
    symmetric: bool


def relation_types(path: str | Path | None = None) -> list[RelationType]:
    """The relation types the relation-types file marks ``pod: true``, in the file's order."""
    from papyrus_content.relation_types import load_semantic_relation_type_seeds

    return [
        RelationType(entry["key"], tuple(entry["allowedSubjectKinds"]), tuple(entry["allowedObjectKinds"]), bool(entry["isSymmetric"]))
        for entry in load_semantic_relation_type_seeds(path)
        if entry["pod"]
    ]

