"""Spike PPY-1e2f29: block alignment and human-edit pinning without Markus block identifiers.

A localization is a list of target blocks. Each records the hash of the source block it came from (None for a block a person
added), its owner (machine | human) and whether it is pinned. Two events change it:

- a person saves new target text   -> diff old target vs new target; changed or added blocks become human and pinned.
- the source gets a new version    -> diff old source vs new source by block hash; plan per target block:
    keep (source unchanged), move (same hash elsewhere), retranslate (machine block whose source changed or is new),
    drop (machine block whose source was deleted), conflict (pinned human block whose source changed or was deleted).

Usage: python3 -I align_spike.py SOURCE.md   (runs the scenarios on that Story and prints the outcome)
"""
import difflib
import hashlib
import sys
from dataclasses import dataclass, field


def blocks_of(markdown: str) -> list[str]:
    blocks, current, depth = [], [], 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith(":::") and stripped != ":::":
            depth += 1
        elif stripped == ":::" and depth:
            depth -= 1
        if not stripped and depth == 0:
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def h(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()[:12]


@dataclass
class Target:
    text: str
    source: str | None  # hash of the source block
    owner: str = "machine"
    pinned: bool = False


@dataclass
class Plan:
    blocks: list = field(default_factory=list)  # (action, Target|None, new_source_text|None)

    def counts(self):
        out = {}
        for action, _, _ in self.blocks:
            out[action] = out.get(action, 0) + 1
        return out


def machine_translate(text: str) -> str:
    return "«ES» " + text  # stand-in: alignment does not depend on translation quality


def ids(blocks):
    """Block identity = content hash plus its occurrence number, so identical blocks (rules, repeated lines) stay distinct."""
    seen, out = {}, []
    for b in blocks:
        key = h(b)
        seen[key] = seen.get(key, 0) + 1
        out.append(f"{key}#{seen[key]}")
    return out


def localize(source_blocks):
    return [Target(machine_translate(b), i) for b, i in zip(source_blocks, ids(source_blocks))]


def human_save(targets: list[Target], new_texts: list[str]) -> list[Target]:
    """A person saved new target text: carry provenance for unchanged blocks, pin changed or added ones."""
    old = [t.text for t in targets]
    out = []
    matcher = difflib.SequenceMatcher(a=[h(x) for x in old], b=[h(x) for x in new_texts], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.extend(targets[i1:i2])
        elif tag == "replace" and (i2 - i1) == (j2 - j1):
            for k in range(j2 - j1):  # edited in place: keeps its source, becomes human
                out.append(Target(new_texts[j1 + k], targets[i1 + k].source, "human", True))
        elif tag == "replace":
            sources = {t.source for t in targets[i1:i2]}
            source = sources.pop() if len(sources) == 1 else None  # split of one block keeps its source; a merge does not
            for k in range(j1, j2):
                out.append(Target(new_texts[k], source, "human", True))
        elif tag == "insert":
            for k in range(j1, j2):
                out.append(Target(new_texts[k], None, "human", True))  # a local-only paragraph
        # delete: the person removed blocks; nothing carried
    return out


def plan_source_change(targets: list[Target], old_src: list[str], new_src: list[str]) -> Plan:
    old_h, new_h = ids(old_src), ids(new_src)
    by_source: dict[str, list[Target]] = {}
    local_after: dict[str | None, list[Target]] = {}
    last = None
    for t in targets:
        if t.source is None:
            local_after.setdefault(last, []).append(t)  # local-only blocks ride after their preceding source block
        else:
            by_source.setdefault(t.source, []).append(t)
            last = t.source
    plan = Plan()
    used = set()
    matcher = difflib.SequenceMatcher(a=old_h, b=new_h, autojunk=False)
    deleted = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            for k in range(i1, i2):
                deleted[old_h[k]] = k
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        pairs = []
        if tag == "equal":
            pairs = [(old_h[i1 + k], new_src[j1 + k], "keep") for k in range(i2 - i1)]
        elif tag == "replace" and (i2 - i1) == (j2 - j1):
            pairs = [(old_h[i1 + k], new_src[j1 + k], "changed") for k in range(i2 - i1)]
        elif tag in ("replace", "insert"):
            olds = old_h[i1:i2]
            for k in range(j1, j2):
                if new_h[k] in deleted and new_h[k] not in used:
                    pairs.append((new_h[k], new_src[k], "move"))
                else:
                    pairs.append((None, new_src[k], "new"))
            for o in olds:
                if o not in new_h:
                    pairs.append((o, None, "deleted"))
        elif tag == "delete":
            pairs = [(old_h[k], None, "deleted") for k in range(i1, i2) if old_h[k] not in new_h]
        for old_hash, new_text, kind in pairs:
            if old_hash is not None:
                used.add(old_hash)
            tlist = by_source.get(old_hash, []) if old_hash else []
            if kind in ("keep", "move"):
                for t in tlist:
                    plan.blocks.append((kind, t, None))
            elif kind == "new":
                plan.blocks.append(("retranslate", None, new_text))
            elif kind == "changed":
                if not tlist:
                    plan.blocks.append(("retranslate", None, new_text))
                for t in tlist:
                    plan.blocks.append(("conflict" if t.pinned else "retranslate", t, new_text))
            elif kind == "deleted":
                for t in tlist:
                    plan.blocks.append(("conflict" if t.pinned else "drop", t, None))
            for t in local_after.get(old_hash, []) if old_hash else []:
                plan.blocks.append(("keep-local", t, None))
    for t in local_after.get(None, []):
        plan.blocks.insert(0, ("keep-local", t, None))
    return plan


def scenario(name, src, mutate_target, mutate_source):
    targets = localize(src)
    targets = mutate_target(targets)
    new_src = mutate_source(list(src))
    plan = plan_source_change(targets, src, new_src)
    human_kept = sum(1 for a, t, _ in plan.blocks if t is not None and t.pinned and a in ("keep", "move", "keep-local"))
    human_lost = sum(1 for t in targets if t.pinned) - human_kept - sum(1 for a, t, _ in plan.blocks if a == "conflict")
    print(f"{name:52} {plan.counts()}  human kept={human_kept} human silently lost={human_lost}")
    return plan


def main():
    src = blocks_of(open(sys.argv[1]).read())
    n = len(src)
    print(f"source blocks: {n}")
    mid = n // 2

    def edit_target(idx):
        def f(targets):
            texts = [t.text for t in targets]
            for i in idx:
                texts[i] = texts[i] + " (ajuste local)"
            return human_save(targets, texts)
        return f

    def add_local(targets):
        texts = [t.text for t in targets]
        texts.insert(mid, "Nota para lectores hispanohablantes.")
        return human_save(targets, texts)

    same = lambda s: s
    scenario("1 person tweaks 2 blocks, source edits another", src, edit_target([3, mid]),
             lambda s: s[:5] + [s[5] + " Updated."] + s[6:])
    scenario("2 source rewrites a block a person tweaked", src, edit_target([mid]),
             lambda s: s[:mid] + [s[mid] + " Corrected figure."] + s[mid + 1:])
    scenario("3 source adds a paragraph", src, edit_target([3]), lambda s: s[:mid] + ["A brand new paragraph."] + s[mid:])
    scenario("4 source removes a paragraph a person tweaked", src, edit_target([mid]), lambda s: s[:mid] + s[mid + 1:])
    scenario("5 source reorders two paragraphs (one pinned)", src, edit_target([mid]),
             lambda s: s[:mid - 2] + [s[mid], s[mid - 2], s[mid - 1]] + s[mid + 1:])
    scenario("6 source splits a pinned paragraph in two", src, edit_target([mid]),
             lambda s: s[:mid] + [s[mid][: len(s[mid]) // 2], s[mid][len(s[mid]) // 2:]] + s[mid + 1:])
    scenario("7 source merges two paragraphs", src, edit_target([3]),
             lambda s: s[:mid] + [s[mid] + " " + s[mid + 1]] + s[mid + 2:])
    scenario("8 person adds a local-only paragraph; source edits", src, add_local,
             lambda s: s[:2] + [s[2] + " Edit."] + s[3:])
    scenario("9 duplicate identical blocks (two '---' rules)", src + ["---", "Tail.", "---"], edit_target([]),
             lambda s: s[:-1] + ["Extra.", "---"])
    scenario("10 nothing changed", src, edit_target([mid]), same)


if __name__ == "__main__":
    main()
