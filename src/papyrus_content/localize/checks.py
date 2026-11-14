"""The checks of a translation, block by block, and what each finding may make the machine do (PPY-843a7c).

Two checks per block, both Humanus:

* **faithfulness**: the translated block against its source block with the ``translation-faithfulness`` pack: the parity rules (structure,
  links, citations, directives, numbers as values, names, glossary, quotations, emphasis, hedges, attributions) and the bilingual judge
  (span-level, quoting both sides, repeated passes must agree). Findings have category ``faithfulness``; at error severity they hold
  publication.
* **copy edit**: the translated block alone with the language's own policies (typography, translationese, AI-writing tells, house words).

What a finding may do:

* a finding with a certain repair (a ``replacement`` from a typography rule, a fixed attribute put back) is applied by code (:func:`apply_fixes`),
  and the block is checked against the source again;
* a faithfulness finding at error severity asks the model to repair the block (each repair is checked against the source again);
* any other finding asks for a rewrite only when its rule has been measured right about nine times in ten on held-out examples in that
  language (Ryan, 2026-11-13; ``evidence.precision`` on the policy); below that, and while unmeasured, it is advice only.

A block a person corrected (``owner: human``) is never rewritten: its findings are advice only.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

import humanus

REWRITE_PRECISION_BAR = 0.9   # Ryan, 2026-11-13 (decision 5): a rule drives rewrites at about nine in ten correct on held-out examples, per language
FAITHFULNESS_PACK = "translation-faithfulness"
SEVERITY_ORDER = ("error", "warn", "info")
CATEGORY_BY_PACK_PREFIX = (("typography", "typography"), ("word-choice", "typography"), ("translationese", "translationese"),
                           ("ai-writing-tells", "slop"))


@dataclass(frozen=True)
class Finding:
    category: str            # faithfulness | typography | translationese | slop | house
    policy: str
    severity: str
    status: str              # violation | review
    message: str
    excerpt: str
    source_excerpt: str = ""
    replacement: str | None = None
    span: tuple[int, int] | None = None   # UTF-16 offsets in the block
    drives_rewrite: bool = False

    def key(self) -> tuple[str, str]:
        """What makes two findings the same problem across rewrites of a block: a faithfulness finding is about a place in the source (which a
        rewrite does not change), any other finding about its words in the translation."""
        side = self.source_excerpt if self.category == "faithfulness" else self.excerpt
        return (self.policy, re.sub(r"\s+", " ", side).strip())

    def payload(self) -> dict[str, Any]:
        out = {"category": self.category, "policy": self.policy, "severity": self.severity, "status": self.status, "message": self.message,
               "excerpt": self.excerpt}
        if self.source_excerpt:
            out["sourceExcerpt"] = self.source_excerpt
        if self.replacement is not None:
            out["replacement"] = self.replacement
        if self.drives_rewrite:
            out["drivesRewrite"] = True
        return out


def tally(findings: Iterable[Finding]) -> tuple[int, int, int, int]:
    """What the loop must strictly reduce, compared in order: faithfulness errors, faithfulness warnings, other findings that drive a rewrite,
    and findings with a certain repair. A strictly decreasing tuple of whole numbers cannot decrease forever, so the loop always ends."""
    findings = list(findings)
    return (sum(1 for f in findings if f.category == "faithfulness" and f.severity == "error"),
            sum(1 for f in findings if f.category == "faithfulness" and f.severity == "warn"),
            sum(1 for f in findings if f.category != "faithfulness" and f.drives_rewrite),
            sum(1 for f in findings if f.replacement is not None))


def faithfulness_worse(before: Iterable[Finding], after: Iterable[Finding]) -> bool:
    """Whether a rewrite made faithfulness worse: it added a faithfulness finding the earlier text did not have, or more errors."""
    old = {f.key() for f in before if f.category == "faithfulness"}
    new = [f for f in after if f.category == "faithfulness"]
    added = [f for f in new if f.key() not in old and f.severity in ("error", "warn")]
    errors = lambda findings: sum(1 for f in findings if f.category == "faithfulness" and f.severity == "error")  # noqa: E731
    return bool(added) or errors(new) > errors(before)


def category_map(pack_names: Iterable[str]) -> dict[str, str]:
    """policy id -> category, from the Humanus starter packs a site's language policies come from."""
    out: dict[str, str] = {}
    for name in pack_names:
        category = next((value for prefix, value in CATEGORY_BY_PACK_PREFIX if name.startswith(prefix)), "house")
        for policy in humanus.builtin_pack(name)["policies"]:
            out.setdefault(policy["id"], category)
    return out


def starter_pack(language: str) -> dict[str, Any]:
    """The pack a site checks text in ``language`` with when its policies are the language's starter packs (``editorial_languages``)."""
    from ..editorial_languages import starter_packs_for

    names = starter_packs_for(language)
    policies = [policy for name in names for policy in humanus.builtin_pack(name)["policies"]]
    version = hashlib.sha256(json.dumps({"names": names, "policies": policies}, sort_keys=True).encode()).hexdigest()[:12]
    return {"schemaVersion": 1, "packId": "papyrus-starters", "version": f"{language}-starters-{version}", "language": language, "policies": policies,
            "papyrusStarterPacks": list(names)}


def pack_fingerprint(pack: Mapping[str, Any]) -> str:
    return f"{pack['packId']}@{pack['version']}"


def _precise(policy: Mapping[str, Any]) -> bool:
    precision = (policy.get("evidence") or {}).get("precision")
    return isinstance(precision, (int, float)) and precision >= REWRITE_PRECISION_BAR


class BlockChecker:
    """Runs the two checks on one block. The judge is the run's model; the copy-edit pack is the site's pack for the language."""

    def __init__(self, *, source_language: str, target_language: str, glossary, copy_edit_pack: Mapping[str, Any], judge: Callable | None,
                 lanes: Mapping[str, bool], decision_model: Any = None):
        self.source_language, self.target_language = source_language, target_language
        self.glossary = glossary
        self.copy_edit_pack = dict(copy_edit_pack)
        self.copy_edit_pack.pop("papyrusStarterPacks", None)
        self.categories = category_map(copy_edit_pack.get("papyrusStarterPacks") or [])
        self.precise = {policy["id"] for policy in copy_edit_pack["policies"] if _precise(policy)}
        self.faithfulness_pack = humanus.builtin_pack(FAITHFULNESS_PACK)
        self.judge = judge
        self.lanes = dict(lanes)
        self.decision_model = decision_model

    @property
    def versions(self) -> dict[str, str]:
        """Everything a stored check result depends on besides the two texts."""
        return {"humanus": humanus.__version__ if hasattr(humanus, "__version__") else _humanus_version(),
                "faithfulnessPack": pack_fingerprint(self.faithfulness_pack), "copyEditPack": pack_fingerprint(self.copy_edit_pack),
                "glossary": self.glossary.version, "sourceLanguagePack": humanus.resolve_language(self.source_language).version,
                "targetLanguagePack": humanus.resolve_language(self.target_language).version,
                "lanes": ",".join(sorted(name for name, on in self.lanes.items() if on))}

    def faithfulness(self, source: str, target: str) -> tuple[list[Finding], dict[str, Any]]:
        request = {"schemaVersion": 1, "content": {"text": target, "format": "markdown", "language": self.target_language},
                   "source": {"text": source, "format": "markdown", "language": self.source_language},
                   "glossary": self.glossary.humanus(self.glossary.entries_in([source], self.source_language)),
                   "pack": self.faithfulness_pack, "options": {"lanes": {"rules": False, "classifier": False, "parity": True, "judge": True}}}
        result = humanus.check(request, decision_model=None, bilingual_judge=self.judge)
        judge = result["lanes"].get("judge") or {}
        if judge.get("status") != "ran":
            raise JudgeUnavailable(f"the bilingual judge did not run: {judge.get('reason') or judge.get('status')}")
        return [self._finding(f, "faithfulness") for f in result["findings"]], result["lanes"]

    def faithfulness_document(self, source: str, target: str) -> tuple[list[Finding], dict[str, Any]]:
        """The whole translated body against the whole source with the parity rules only (the judge has read every block already): the
        structure, links and directives of the document as a whole."""
        request = {"schemaVersion": 1, "content": {"text": target, "format": "markdown", "language": self.target_language},
                   "source": {"text": source, "format": "markdown", "language": self.source_language},
                   "glossary": self.glossary.humanus(self.glossary.entries_in([source], self.source_language)),
                   "pack": self.faithfulness_pack, "options": {"lanes": {"rules": False, "classifier": False, "parity": True, "judge": False}}}
        result = humanus.check(request, decision_model=None)
        document_wide = {"structure", "links", "citations", "code", "directives"}
        return [self._finding(f, "faithfulness") for f in result["findings"] if f["policyId"] in document_wide], result["lanes"]

    def copy_edit(self, target: str) -> tuple[list[Finding], dict[str, Any]]:
        request = {"schemaVersion": 1, "content": {"text": target, "format": "markdown", "language": self.target_language},
                   "pack": self.copy_edit_pack,
                   "options": {"lanes": {"rules": bool(self.lanes.get("rules", True)), "classifier": bool(self.lanes.get("classifier", False))}}}
        result = humanus.check(request, decision_model=self.decision_model if self.lanes.get("classifier") else None)
        return [self._finding(f, self.categories.get(f["policyId"], "house")) for f in result["findings"]], result["lanes"]

    def _finding(self, raw: Mapping[str, Any], category: str) -> Finding:
        span = raw.get("span") or {}
        faithful = category == "faithfulness"
        drives = (faithful and raw["severity"] == "error") or (not faithful and raw["policyId"] in self.precise)
        return Finding(category=category, policy=raw["policyId"], severity=raw["severity"], status=raw["status"], message=raw["message"],
                       excerpt=raw.get("excerpt") or "", source_excerpt=(raw.get("source") or {}).get("excerpt") or "",
                       replacement=raw.get("replacement"), span=(span.get("start"), span.get("end")) if span else None,
                       drives_rewrite=drives and raw.get("replacement") is None)


class JudgeUnavailable(RuntimeError):
    """The bilingual judge did not run on a block: a translation is never checked without it."""


def _humanus_version() -> str:
    from importlib.metadata import version

    return version("humanus")


def apply_fixes(text: str, findings: Iterable[Finding]) -> tuple[str, int]:
    """``text`` with every certain repair applied (a finding's ``replacement`` over its span), from the end so earlier spans stay valid;
    overlapping repairs after the first are left for the next round. Returns the text and the number applied."""
    from humanus.check import Utf16Offsets

    offsets = Utf16Offsets(text)
    chosen: list[tuple[int, int, str]] = []
    for finding in sorted((f for f in findings if f.replacement is not None and f.span), key=lambda f: f.span[0], reverse=True):
        start, end = offsets.to_index(finding.span[0]), offsets.to_index(finding.span[1])
        if chosen and end > chosen[-1][0]:
            continue
        chosen.append((start, end, finding.replacement))
    for start, end, replacement in chosen:
        text = text[:start] + replacement + text[end:]
    return text, len(chosen)


_CLOSING_EMPHASIS = re.compile(r"(?<=[^\s*_])([\.,:;!?。，：；！？、）」』》”’]+)(\*\*|\*|__|_)(?=\w)")


def closing_emphasis(text: str, spaced: bool) -> str:
    """Emphasis that closes after punctuation and runs straight into a word does not render (CommonMark's flanking rule: the translation
    experiment's ``**7 月 9 日：**Hugging Face``). The punctuation moves outside the emphasis; a language written with spaces also gets a
    space after it when the punctuation is a Latin one. A marker is a closer when an odd number of the same marker comes before it in the
    paragraph; an opener after punctuation (``他说，**重要**``) is left alone."""
    out, last = [], 0
    for match in _CLOSING_EMPHASIS.finditer(text):
        punctuation, marker = match.group(1), match.group(2)
        paragraph_start = text.rfind("\n\n", 0, match.start()) + 1
        before = text[paragraph_start:match.start()]
        if len(re.findall(re.escape(marker) if len(marker) == 2 else rf"(?<![*_]){re.escape(marker)}(?![*_])", before)) % 2 == 0:
            continue
        space = " " if spaced and punctuation[-1] in ".,:;!?" else ""
        out.append(text[last:match.start()] + f"{marker}{punctuation}{space}")
        last = match.end()
    return "".join(out) + text[last:]
