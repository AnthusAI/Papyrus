"""Which relations count as a Reference being about a concept.

Text that enrichment extracted is a ``mentions`` edge. A person tagging a Reference with a concept is a ``tagged_with`` edge
from the reference to the ``semanticNode`` (docs/idea-context-packs.md section 2.2), or, in rows written before the rename, ``related_to``. Every concept statistic counts both.
``related_to`` is also used between two References and must not count as a concept mention, so the subject and object kinds
are part of the test.
"""

from __future__ import annotations

from typing import Any

from .reference_links import CONCEPT_TAG_PREDICATE, CONCEPT_TAG_PREDICATES, LEGACY_CONCEPT_TAG_PREDICATE

MENTIONS = "mentions"
TAGGED_WITH = CONCEPT_TAG_PREDICATE
RELATED_TO = LEGACY_CONCEPT_TAG_PREDICATE   # the tag's name before `tagged_with`: still read, until the stored rows are migrated
# Every predicate that makes a concept a concept of a Reference or story: extracted text (`mentions`), a tag (`tagged_with`) and the legacy tag (`related_to`).
CONCEPT_LINK_PREDICATES = (MENTIONS, *CONCEPT_TAG_PREDICATES)
REFERENCE_KIND = "reference"
CONCEPT_KIND = "semanticNode"


def is_reference_concept_link(predicate: Any, subject_kind: Any, object_kind: Any) -> bool:
    return (
        str(predicate or "") in CONCEPT_LINK_PREDICATES
        and str(subject_kind or "") == REFERENCE_KIND
        and str(object_kind or "") == CONCEPT_KIND
    )
