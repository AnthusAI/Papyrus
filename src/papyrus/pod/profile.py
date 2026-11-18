"""The pod profile: what a note may say, pinned in one place.

Profile version 3 pins Vault-LD 0.5.0 at commit 025e71b. A new Vault-LD release changes nothing here until this pin moves. Version 2 added the
lifecycle keys (``stage``, ``format``, ``rating``, the review stamps and the two reasons), named and valued as on the newsroom's content item. Version 3 adds
the Announcement and Delivery classes with their keys.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROFILE_VERSION = 3
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
    "Announcement": "announcement",
    "Delivery": "delivery",
}
# Notes that are records of what was said and where, never pages: the words are the body, outside the graph, and nothing builds them into a site.
NEVER_PAGES = ("Announcement", "Delivery")
# The classes a site may build into pages, when their lifecycle keys allow it.
PAGE_CLASSES = ("Article", "Post", "Page")
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

# The keys of an Announcement note (the decision to say something) and of a Delivery note (one channel's version of it). They have the field names of the
# newsroom's records. The words of a Delivery are the body. `announces` and `supersedes` are relation types, so they are not listed here.
ANNOUNCEMENT_KEYS: tuple[Key, ...] = (
    Key("kind", "papyrus:kind", STRING),
    Key("state", "papyrus:state", STRING),
    Key("releaseAt", "papyrus:releaseAt", STRING),
)
DELIVERY_KEYS: tuple[Key, ...] = (
    Key("announcement", "papyrus:announcement", LINK),
    Key("channel", "papyrus:channel", STRING),
    Key("account", "papyrus:account", STRING),
    Key("mode", "papyrus:mode", STRING),
    Key("state", "papyrus:state", STRING),
    Key("resultUrl", "papyrus:resultUrl", ADDRESS),
    Key("attempts", "papyrus:attempts", TEXT_LIST),
)
# The keys only one class takes, so a stray key can be told where it belongs.
CLASS_KEYS: dict[str, tuple[Key, ...]] = {"Relation": RELATION_KEYS, "Announcement": ANNOUNCEMENT_KEYS, "Delivery": DELIVERY_KEYS}
# A pod records what happened, so the states are the final ones; it never holds a Delivery that is waiting to go.
ANNOUNCEMENT_STATES = ("released", "cancelled", "withdrawn")
DELIVERY_STATES = ("sent", "failed", "withdrawn", "superseded")
# A pod delivers in manual mode only: a person sends it. Sending automatically needs a connected account, a budget guard and Caducus, which a newsroom has.
POD_MODE = "manual"
# An attempt is a person's line: `<number> <time> <outcome> [by <name> | <code>]`.
ATTEMPT_OUTCOMES = ("sent", "refused")

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

