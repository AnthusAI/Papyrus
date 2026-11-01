"""Which relations count as a Reference being about a concept.

Text that enrichment extracted is a ``mentions`` edge. A person tagging a Reference with a concept is a ``related_to`` edge
from the reference to the ``semanticNode`` (docs/idea-context-packs.md section 2.2). Every concept statistic counts both.
``related_to`` is also used between two References and must not count as a concept mention, so the subject and object kinds
are part of the test.
"""

from __future__ import annotations

from typing import Any

MENTIONS = "mentions"
RELATED_TO = "related_to"
CONCEPT_LINK_PREDICATES = (MENTIONS, RELATED_TO)
REFERENCE_KIND = "reference"
CONCEPT_KIND = "semanticNode"


def is_reference_concept_link(predicate: Any, subject_kind: Any, object_kind: Any) -> bool:
    return (
        str(predicate or "") in CONCEPT_LINK_PREDICATES
        and str(subject_kind or "") == REFERENCE_KIND
        and str(object_kind or "") == CONCEPT_KIND
    )
