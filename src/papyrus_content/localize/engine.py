"""One translation run: one Story, one language (``papyrus.story.localize``, PPY-843a7c; design: papyrus-multilingual-humanus-design.md, section 3).

Stages, each stored under a key made of its inputs so a re-run of an interrupted run pays only for what is missing:

1. **collect** (``record.collect``): the source version, the previous localization and its alignment, which blocks changed, the glossary
   entries, the language's pack and register notes, the run key. Stops when the run key already finished (no model call, no save).
2. **budget** (``budget.predict``): the predicted cost from this language's measured runs; waits when it is above the caller's ceiling.
3. **translate**: only the blocks whose source changed (all of them the first time), with their neighbours as context, the glossary entries
   that occur in them and the register notes; links, citations, code and fixed attributes never reach the model (``blocks.protect``).
4. **normalize and parity**, 5. **bilingual judge**, 6. **copy edit**: ``checks.BlockChecker`` on each changed block; certain repairs
   (typography replacements, a fixed attribute put back, emphasis that would not render) are applied by code.
7. **refine**: the machine-owned blocks with findings that may drive a rewrite go back to the model with the source and the findings.
8. **loop**: 4 to 7 again on the changed blocks only, while a round strictly reduces the findings (``checks.tally``) and adds no faithfulness
   finding; a block whose rewrite makes faithfulness worse reverts to its earlier text. It ends on convergence: a round that changes nothing,
   or one that no longer reduces the findings. The number of rounds is recorded, never configured.
9. **record** and 10. **gate**: the translation is assembled and checked whole against the source (structure, links, directives), the
   provenance is built, and the gate holds when an error-severity faithfulness finding remains. Saving, the review request and the report back
   to the English Story are the caller's (``record``): this module writes nothing.

A block a person corrected (owner ``human``) is never sent to a model and never changed; its findings are advice. Every failure raises: no
other model is tried and no stage is skipped.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from .blocks import Block, PlaceholderError, Protected, blocks_of, join_body, protect, protect_like
from .budget import Prediction
from .checks import BlockChecker, Finding, apply_fixes, closing_emphasis, faithfulness_worse, tally
from .models import PROMPT_VERSION, LocalizeModels, Spend, StructuredOutputMissing

PROCEDURE_KEY = "papyrus.story.localize"
MAXIMUM_ATTEMPTS = 3   # a reply without a usable structured answer is asked again, as editor_review.tac does; then the run fails
SPACED_LANGUAGES_BASES = ("es", "en")


class StageStore(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...

    def put(self, key: str, value: dict[str, Any]) -> None: ...


class MemoryStageStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        value = self.values.get(key)
        return json.loads(json.dumps(value)) if value is not None else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        self.values[key] = json.loads(json.dumps(value))


@dataclass(frozen=True)
class SourceVersion:
    lineage_id: str
    version_id: str
    version_number: int
    content_hash: str
    language: str
    title: str
    deck: str
    body: str
    section: str | None = None


@dataclass(frozen=True)
class AlignedBlock:
    """One block of the previous localization: the source block it came from, its text, and who owns it."""

    source_block: str | None
    text: str
    owner: str = "machine"      # machine | human
    pinned: bool = False


@dataclass
class LocalizeRequest:
    source: SourceVersion
    language: str
    localization_lineage: str
    run_key: str
    glossary: Any
    checker: BlockChecker
    register_notes: list[str] = field(default_factory=list)
    previous: list[AlignedBlock] | None = None
    previous_source_hash: str | None = None
    prediction: Prediction | None = None
    ceiling_usd: float | None = None
    procedure_version: str = ""
    source_checker: Callable[[str], list[Finding]] | None = None   # the English copy-edit check, for the report back


class RunFailed(RuntimeError):
    """The run cannot finish: the reason is the message. Stored stages are kept, so the next start continues from them."""


def stage_key(stage: str, *parts: Any) -> str:
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:32]
    return f"{stage}/{digest}"


@dataclass
class _Slot:
    """One block of the translation being made."""

    source: Block
    protected: Protected | None
    text: str
    owner: str = "machine"
    pinned: bool = False
    translate: bool = False
    conflict: bool = False
    findings: list[Finding] = field(default_factory=list)
    checked: bool = False


def _spaced(language: str) -> bool:
    return language.split("-")[0] in SPACED_LANGUAGES_BASES


def plan_slots(source_blocks: list[Block], previous: list[AlignedBlock] | None) -> list[_Slot]:
    """Which blocks keep their translation, which are translated, and which are a person's (kept as written, a conflict when their source changed).

    The alignment spike's rule (PPY-1e2f29): an unchanged source block keeps its target; a changed or new one is translated when its target is
    the machine's; a changed or deleted source block under a person's pinned block is a conflict, and nothing is overwritten."""
    if not previous:
        return [_Slot(block, protect(block.text) if block.translated else None, block.text, translate=block.translated) for block in source_blocks]
    old_ids = [entry.source_block for entry in previous]
    new_ids = [block.id for block in source_blocks]
    slots: list[_Slot] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old_ids, b=new_ids, autojunk=False).get_opcodes():
        if tag == "equal":
            for old, block in zip(previous[i1:i2], source_blocks[j1:j2]):
                slots.append(_Slot(block, protect(block.text) if block.translated else None, old.text, owner=old.owner, pinned=old.pinned))
            continue
        people = [entry for entry in previous[i1:i2] if entry.owner == "human" and entry.pinned]
        new_blocks = source_blocks[j1:j2]
        if people:   # a person's wording under a changed or deleted source block: kept exactly, and shown as a conflict
            for index, entry in enumerate(people):
                anchor = new_blocks[min(index, len(new_blocks) - 1)] if new_blocks else Block(entry.source_block or "removed", "prose", "")
                slots.append(_Slot(anchor, None, entry.text, owner="human", pinned=True, conflict=True))
            new_blocks = new_blocks[len(people):]
        for block in new_blocks:
            slots.append(_Slot(block, protect(block.text) if block.translated else None, block.text, translate=block.translated))
    return slots


class Localizer:
    """Runs the stages for one request. ``models`` makes every model call; ``stages`` keeps what each stage produced."""

    def __init__(self, request: LocalizeRequest, *, models: LocalizeModels, spend: Spend, stages: StageStore):
        self.request, self.models, self.spend, self.stages = request, models, spend, stages
        self.languages = {"source": request.source.language, "target": request.language,
                          "source_name": _language_name(request.source.language), "target_name": _language_name(request.language)}
        self.rounds: list[dict[str, Any]] = []
        self.reverted = 0
        self.held_for_cost: str | None = None

    # --- the run -------------------------------------------------------------------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        request = self.request
        finished = self.stages.get(f"run/{request.run_key}")
        if finished is not None:
            return {**finished, "repeated": True}
        source_blocks = blocks_of(request.source.body, title=request.source.title, deck=request.source.deck)
        slots = plan_slots(source_blocks, request.previous)
        to_translate = [slot for slot in slots if slot.translate]
        characters = sum(len(slot.source.text) for slot in to_translate)
        prediction = request.prediction
        if request.ceiling_usd is not None and prediction is not None and prediction.predicted_usd is not None and prediction.predicted_usd > request.ceiling_usd:
            return self._outcome(slots, "waiting", f"predicted cost ${prediction.predicted_usd:.4f} is above the ceiling ${request.ceiling_usd:.4f}",
                                 characters)
        self._translate(slots, to_translate)
        for slot in slots:
            if slot.source.translated and not slot.checked:
                self._check(slot)   # every translated block is checked against its source; unchanged ones from their stored results
        self._converge(slots)
        return self._outcome(slots, None, None, characters)

    # --- stage 3: translate --------------------------------------------------------------------------------------------------------------------

    def _translate(self, slots: list[_Slot], to_translate: list[_Slot]) -> None:
        if not to_translate:
            return
        index = {id(slot): position for position, slot in enumerate(slots)}
        pending = {slot.source.id: slot for slot in to_translate}
        problems: dict[str, str] = {}
        for attempt in range(1, MAXIMUM_ATTEMPTS + 1):
            blocks = []
            for block_id, slot in pending.items():
                entry = {"id": block_id, "kind": slot.source.kind, "text": slot.protected.text}
                if block_id in problems:
                    entry["problem"] = f"Your previous translation of this block was refused: {problems[block_id]}."
                blocks.append(entry)
            context = []
            for slot in pending.values():
                position = index[id(slot)]
                for neighbour in slots[max(0, position - 1):position] + slots[position + 1:position + 2]:
                    if neighbour.source.id not in pending and neighbour.source.translated:
                        context.append({"source": neighbour.source.text, "translation": neighbour.text})
            entries = self.request.glossary.entries_in([slot.source.text for slot in pending.values()], self.request.source.language)
            payload = {"languages": self.languages, "registerNotes": self.request.register_notes, "blocks": blocks, "context": context,
                       "glossary": self.request.glossary.prompt_lines(entries)}
            key = stage_key("translate", self.models.model, PROMPT_VERSION, payload)
            answer = self.stages.get(key)
            if answer is None:
                answer = self.models.translate(payload)
                self.stages.put(key, answer)
            replies = {reply.get("id"): reply.get("text") for reply in answer.get("blocks") or [] if isinstance(reply, dict)}
            problems = {}
            for block_id, slot in list(pending.items()):
                text = replies.get(block_id)
                if not isinstance(text, str) or not text.strip():
                    problems[block_id] = "it was missing from your answer"
                    continue
                try:
                    slot.text = self._normalize(slot.protected.restore(text))
                except PlaceholderError as error:
                    problems[block_id] = str(error)
                    continue
                del pending[block_id]
            if not pending:
                return
        raise RunFailed(f"the translator did not return a usable translation of {len(pending)} block(s) after {MAXIMUM_ATTEMPTS} attempts: "
                        + "; ".join(f"{block_id}: {problem}" for block_id, problem in list(problems.items())[:3]))

    def _normalize(self, text: str) -> str:
        return closing_emphasis(text, _spaced(self.request.language))

    # --- stages 4 to 6: the checks ---------------------------------------------------------------------------------------------------------------

    def _findings(self, source: str, target: str) -> list[Finding]:
        checker = self.request.checker
        key = stage_key("check", self.models.model, checker.versions, source, target)
        stored = self.stages.get(key)
        if stored is None:
            faithful, _ = checker.faithfulness(source, target)
            copy_edit, _ = checker.copy_edit(target)
            stored = {"findings": [_finding_payload(f) for f in faithful + copy_edit]}
            self.stages.put(key, stored)
        return [_finding_from(payload) for payload in stored["findings"]]

    def _check(self, slot: _Slot) -> None:
        findings = self._findings(slot.source.text, slot.text)
        if slot.owner == "human":   # a person's wording: advice only
            findings = [Finding(**{**f.__dict__, "drives_rewrite": False, "replacement": None}) for f in findings]
        slot.findings, slot.checked = findings, True

    # --- stages 7 and 8: refine until it converges ----------------------------------------------------------------------------------------------

    def _converge(self, slots: list[_Slot]) -> None:
        machine = [slot for slot in slots if slot.owner == "machine" and slot.source.translated and not slot.conflict]
        before = tally(f for slot in machine for f in slot.findings)
        number = 0
        while True:
            if self._over_budget():
                return
            candidates = [slot for slot in machine if any(f.drives_rewrite or f.replacement is not None for f in slot.findings)]
            if not candidates:
                return
            number += 1
            proposals = self._proposals(candidates)
            changed, reverted, fixes = 0, 0, 0
            for slot in candidates:
                proposal = proposals.get(slot.source.id)
                if proposal is None or proposal == slot.text:
                    continue
                findings = self._findings(slot.source.text, proposal)
                if faithfulness_worse(slot.findings, findings):
                    reverted += 1   # the rewrite changed what the block says: the earlier wording stays
                    continue
                fixes += 1 if any(f.replacement is not None for f in slot.findings) else 0
                slot.text, slot.findings = proposal, findings
                changed += 1
            after = tally(f for slot in machine for f in slot.findings)
            self.reverted += reverted
            self.rounds.append({"round": number, "blocks": len(candidates), "changed": changed, "reverted": reverted,
                                "findingsBefore": list(before), "findingsAfter": list(after)})
            if changed == 0 or not after < before:
                return   # converged: nothing changed, or the round did not reduce the findings
            before = after

    def _proposals(self, candidates: list[_Slot]) -> dict[str, str]:
        """Each candidate's next text: certain repairs applied by code, then the model's repair for findings that may drive a rewrite."""
        proposals: dict[str, str] = {}
        for slot in candidates:
            fixed, applied = apply_fixes(slot.text, slot.findings)
            proposals[slot.source.id] = self._normalize(fixed) if applied else slot.text
        needing = [slot for slot in candidates if any(f.drives_rewrite for f in slot.findings)]
        if not needing:
            return proposals
        pending = {slot.source.id: slot for slot in needing}
        problems: dict[str, str] = {}
        for _ in range(MAXIMUM_ATTEMPTS):
            blocks = []
            for block_id, slot in pending.items():
                current = protect_like(slot.protected, proposals[block_id])
                entry = {"id": block_id, "source": slot.protected.text, "current": current.text,
                         "problems": [f"{f.message}" + (f" (translation: {f.excerpt!r})" if f.excerpt else "") + (f" (source: {f.source_excerpt!r})" if f.source_excerpt else "")
                                      for f in slot.findings if f.drives_rewrite]}
                if block_id in problems:
                    entry["problem"] = f"Your previous repair of this block was refused: {problems[block_id]}."
                blocks.append(entry)
            entries = self.request.glossary.entries_in([slot.source.text for slot in pending.values()], self.request.source.language)
            payload = {"languages": self.languages, "registerNotes": self.request.register_notes, "blocks": blocks,
                       "glossary": self.request.glossary.prompt_lines(entries)}
            key = stage_key("refine", self.models.model, PROMPT_VERSION, payload)
            answer = self.stages.get(key)
            if answer is None:
                answer = self.models.refine(payload)
                self.stages.put(key, answer)
            replies = {reply.get("id"): reply.get("text") for reply in answer.get("blocks") or [] if isinstance(reply, dict)}
            problems = {}
            for block_id, slot in list(pending.items()):
                text = replies.get(block_id)
                if not isinstance(text, str) or not text.strip():
                    problems[block_id] = "it was missing from your answer"
                    continue
                try:
                    proposals[block_id] = self._normalize(slot.protected.restore(text))
                except PlaceholderError as error:
                    problems[block_id] = str(error)
                    continue
                del pending[block_id]
            if not pending:
                return proposals
        raise RunFailed(f"the refine model did not return a usable repair of {len(pending)} block(s) after {MAXIMUM_ATTEMPTS} attempts")

    def _over_budget(self) -> bool:
        spent = self.spend.cost_usd
        ceiling = self.request.ceiling_usd
        if ceiling is not None and spent >= ceiling:
            self.held_for_cost = f"the run's cost ${spent:.4f} reached its ceiling ${ceiling:.4f}"
            return True
        prediction = self.request.prediction
        if prediction is not None and prediction.upper_usd is not None and spent > prediction.upper_usd:
            self.held_for_cost = f"cost far above prediction: ${spent:.4f} spent, ${prediction.upper_usd:.4f} is the upper band for {prediction.language}"
            return True
        return False

    # --- stages 9 and 10: assemble, check whole, gate ----------------------------------------------------------------------------------------

    def _outcome(self, slots: list[_Slot], stopped: str | None, stopped_reason: str | None, characters: int) -> dict[str, Any]:
        request = self.request
        title = next((slot.text for slot in slots if slot.source.kind == "title"), "")
        deck = next((slot.text for slot in slots if slot.source.kind == "deck"), "")
        body_slots = [slot for slot in slots if slot.source.kind not in ("title", "deck")]
        body = join_body([slot.text for slot in body_slots])
        findings = [f for slot in slots for f in slot.findings]
        document: list[Finding] = []
        if stopped is None:
            document, _ = request.checker.faithfulness_document(request.source.body, body)
        remaining = [f for f in findings + document if f.category == "faithfulness" and f.severity == "error" and f.status == "violation"]
        hold_reasons = []
        if remaining:
            hold_reasons.append("faithfulness: " + "; ".join(f"{f.policy}: {f.message}" for f in remaining[:5]))
        if self.held_for_cost:
            hold_reasons.append(self.held_for_cost)
        outcome = "waiting" if stopped == "waiting" else ("held" if hold_reasons else "saved")
        report_back = self._report_back(slots) if stopped is None else []
        cost = self.spend.cost_usd
        provenance = {
            "schemaVersion": 1,
            "procedure": {"key": PROCEDURE_KEY, "version": request.procedure_version},
            "runKey": request.run_key,
            "source": {"lineageId": request.source.lineage_id, "versionId": request.source.version_id, "versionNumber": request.source.version_number,
                       "contentHash": request.source.content_hash, "language": request.source.language},
            "target": {"language": request.language, "lineageId": request.localization_lineage},
            "blocks": {"translated": sum(1 for s in slots if s.translate), "reused": sum(1 for s in slots if not s.translate and s.owner == "machine" and s.source.translated),
                       "pinned": sum(1 for s in slots if s.owner == "human"), "conflicted": sum(1 for s in slots if s.conflict),
                       "copied": sum(1 for s in slots if not s.source.translated), "sourceCharactersTranslated": characters},
            "models": {"translate": self.models.model, "judge": self.models.model, "refine": self.models.model, "promptVersion": PROMPT_VERSION},
            "versions": request.checker.versions,
            "rounds": self.rounds,
            "revertedBlocks": self.reverted,
            "findings": _counts(findings + document),
            "remaining": [f.payload() for f in findings + document if f.category == "faithfulness" or f.drives_rewrite or f.severity in ("error", "warn")][:200],
            "reportBack": report_back,
            "cost": {"totalUsd": round(cost, 6), "byPurpose": self.spend.by_purpose(),
                     "prediction": request.prediction.payload() if request.prediction else None, "ceilingUsd": request.ceiling_usd},
            "outcome": outcome, "reason": stopped_reason or "; ".join(hold_reasons),
            "alignment": [{"sourceBlock": s.source.id, "owner": s.owner, "pinned": s.pinned, **({"conflict": True} if s.conflict else {})} for s in slots],
            "checklist": _checklist(outcome, findings + document, request.source.content_hash),
        }
        result = {"story": request.localization_lineage, "language": request.language, "hold": outcome == "held", "reason": provenance["reason"],
                  "outcome": outcome, "published": False, "rounds": len(self.rounds), "revertedBlocks": self.reverted, "costUsd": round(cost, 6),
                  "findings": provenance["findings"], "runKey": request.run_key,
                  "translation": {"title": title, "deck": deck, "body": body, "blocks": [s.text for s in slots]},
                  "provenance": provenance}
        return result

    def _report_back(self, slots: list[_Slot]) -> list[dict[str, Any]]:
        """Stock phrasing the copy edit keeps finding in the translation that the English block has too: advice for the English Story's editor
        (Ryan, 2026-11-13). Fixing it in the English is the cure; fixing it per language would make the languages differ."""
        checker = self.request.source_checker
        if checker is None:
            return []
        advice = []
        for position, slot in enumerate(slots):
            if not any(f.category == "slop" for f in slot.findings):
                continue
            for finding in checker(slot.source.text):
                if finding.category == "slop":
                    advice.append({"block": position, "sourceBlock": slot.source.id, "phrase": finding.excerpt, "policy": finding.policy,
                                   "message": finding.message})
        return advice


def finish(request: LocalizeRequest, stages: StageStore, outcome: dict[str, Any]) -> None:
    """Marks the run key finished, so the same run started again does nothing (no model call, no save). Called after the save succeeded."""
    if outcome["outcome"] in ("saved", "held"):
        stages.put(f"run/{request.run_key}", {key: value for key, value in outcome.items() if key != "translation"})


def _counts(findings: list[Finding]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for finding in findings:
        out.setdefault(finding.category, {}).setdefault(finding.severity, 0)
        out[finding.category][finding.severity] += 1
    return out


def _checklist(outcome: str, findings: list[Finding], source_hash: str) -> dict[str, dict[str, Any]]:
    """The localization's checklist steps (PPY-c61c9c), each proven by this run's records, none markable by hand."""
    faithful = not any(f.category == "faithfulness" and f.severity == "error" and f.status == "violation" for f in findings)
    return {
        "translate": {"done": outcome in ("saved", "held"), "proof": f"provenance names source {source_hash}"},
        "faithfulness": {"done": outcome in ("saved", "held") and faithful, "proof": "parity rules and the bilingual judge on every block"},
        "copy_edit": {"done": outcome in ("saved", "held"), "proof": "the convergence loop's final copy-edit check of every block"},
        "publish": {"done": False, "proof": "this procedure never publishes"},
        "corrector_review": {"done": False, "optional": True, "proof": "a corrector's correction or Looks right"},
    }


def _finding_payload(finding: Finding) -> dict[str, Any]:
    return {**finding.__dict__, "span": list(finding.span) if finding.span else None}


def _finding_from(payload: Mapping[str, Any]) -> Finding:
    return Finding(**{**payload, "span": tuple(payload["span"]) if payload.get("span") else None})


def _language_name(tag: str) -> str:
    import humanus

    return humanus.resolve_language(tag).name
