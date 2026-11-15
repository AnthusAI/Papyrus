"""What one translation run would do, from what it collected: the plan ``papyrus stories localize --dry-run`` prints (one Story) and the whole-site dry run sums."""
from __future__ import annotations

from typing import Any

from .blocks import blocks_of
from .engine import plan_slots


def plan_of(request, *, story: str) -> dict[str, Any]:
    """``request`` is a collected ``LocalizeRequest``: the blocks to translate and the ones kept, the glossary terms the translator will meet, and the cost
    predicted from this language's measured runs (``predictedUsd`` is None while the language has none)."""
    slots = plan_slots(blocks_of(request.source.body, title=request.source.title, deck=request.source.deck, fields=request.source.fields), request.previous)
    to_translate = [slot for slot in slots if slot.translate]
    terms = [entry["term"] for entry in request.glossary.entries_in([slot.source.text for slot in to_translate], request.source.language)]
    return {"story": story, "language": request.language, "localization": request.localization_lineage, "sourceVersion": request.source.version_number,
            "blocksToTranslate": len(to_translate), "blocksKept": len(slots) - len(to_translate), "glossaryTerms": terms,
            "prediction": request.prediction.payload() if request.prediction else {}}
