"""A recording stand-in for a client: wraps another client (usually a fake) and records the AppSync root field each call would be on the real client."""

from __future__ import annotations

import re
from typing import Any

from papyrus_content.graphql_authoring import GET_DEFINITIONS, INDEX_DEFINITIONS, LIST_DEFINITIONS, MUTATIONS

GRAPHQL_ROOT = re.compile(r"^\s*(query|mutation)\b[^{]*\{\s*(\w+)", re.S)


def root_of(query: str) -> tuple[str, str]:
    kind, field = GRAPHQL_ROOT.match(query).groups()
    return kind.capitalize(), field


class FieldRecorder:
    """``fields`` is the set of (``Query`` or ``Mutation``, field) pairs the real ``PapyrusGraphQLAuthoringClient`` would ask AppSync for."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.fields: set[tuple[str, str]] = set()

    def __getattr__(self, name: str) -> Any:
        if name == "inner" or (name.startswith("__") and name.endswith("__")):
            raise AttributeError(name)   # copy.copy asks a bare instance for __setstate__ before ``inner`` exists
        attribute = getattr(self.inner, name)
        if not callable(attribute):
            return attribute

        def call(*arguments: Any, **options: Any) -> Any:
            self.note(name, arguments)
            return attribute(*arguments, **options)

        return call

    def note(self, name: str, arguments: tuple[Any, ...]) -> None:
        if name == "list_records":
            self.fields.add(("Query", LIST_DEFINITIONS[arguments[0]]["field"]))
        elif name == "get_record":
            self.fields.add(("Query", GET_DEFINITIONS[arguments[0]]["field"]))
        elif name == "list_by_index":
            self.fields.add(("Query", INDEX_DEFINITIONS[arguments[0]]["field"]))
        elif name in ("create_record", "update_record"):
            self.fields.add(root_of(MUTATIONS[arguments[0]][name.split("_")[0]]))
        elif name == "upsert":
            self.fields.add(("Query", GET_DEFINITIONS[arguments[0]]["field"]))
            self.fields.add(root_of(MUTATIONS[arguments[0]]["update" if self.inner.get_record(arguments[0], arguments[1]["id"]) else "create"]))
        elif name == "list_semantic_relations_by_subject_state":
            self.fields.add(("Query", INDEX_DEFINITIONS["semanticRelationsBySubjectState"]["field"]))
        elif name == "list_semantic_relations_by_object_state":
            self.fields.add(("Query", INDEX_DEFINITIONS["semanticRelationsByObjectState"]["field"]))
        elif name == "list_reference_attachments_by_lineage":
            self.fields.add(("Query", INDEX_DEFINITIONS["referenceAttachmentsByReferenceLineageAndSortKey"]["field"]))
        elif name == "graphql":
            self.fields.add(root_of(arguments[0]))
