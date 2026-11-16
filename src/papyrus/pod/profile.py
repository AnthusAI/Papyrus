"""The pod profile: what a note may say, pinned in one place.

Profile version 2 pins Vault-LD 0.5.0 at commit 025e71b. A new Vault-LD release changes nothing here until this pin moves. Version 2 adds the
lifecycle keys (``stage``, ``format``, ``rating``, the review stamps and the two reasons), named and valued as on the newsroom's content item.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROFILE_VERSION = 2
VAULT_LD_VERSION = "0.5.0"
VAULT_LD_COMMIT = "025e71b"

NAMESPACE = "https://p.apyr.us/ns#"
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
    # Lifecycle keys: the cloud Item's names and values. `type` and `section` are the profile's own keys above.
    Key("stage", "papyrus:stage", STRING),
    Key("format", "papyrus:format", STRING),
    Key("rating", "papyrus:rating", INTEGER),
    Key("reviewedBy", "papyrus:reviewedBy", STRING),
    Key("reviewedOn", "papyrus:reviewedOn", DATE),
    Key("reviewedHash", "papyrus:reviewedHash", STRING),
    Key("spikedReason", "papyrus:spikedReason", STRING),
    Key("heldReason", "papyrus:heldReason", STRING),
)

# The ten stages of a content item. A note with a stage is built only at "published"; a note with none is built unless `draft: true`.
STAGES = ("idea", "assignment", "reporting", "copywriting", "illustration", "typesetting", "published", "held", "spiked", "retired")
# A pod grants one to four stars. Five needs a person's approval in the newsroom, so a pod refuses it.
RATINGS = (1, 2, 3, 4)
REVIEW_HASH_PREFIX = "sha256:"

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

PREFIXES = {
    "papyrus": NAMESPACE,
    "schema": "https://schema.org/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}
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

