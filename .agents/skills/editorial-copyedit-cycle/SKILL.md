---
name: editorial-copyedit-cycle
description: >-
  Run Papyrus's editorial diagnose -> decisions -> options -> apply -> verify
  copy-editing cycle on a publication draft, for any Papyrus publication (not
  just Anth.us). Use this whenever the user asks to copy-edit, proofread,
  clean up, tighten, or "run a slop scan" on a draft article/story in Papyrus;
  when they mention `editorial diagnose`, `editorial options`, redundancy or
  voice-mismatch findings, a style profile, or a before/after redline; or when
  they ask why a generated rewrite "doesn't sound like them" and want the
  editing tooling itself improved. Trigger even if they don't name the exact
  CLI commands or this skill explicitly -- "can you tighten up this draft
  without changing my voice" or "does this article pass the style checker"
  are both this skill.
---

# Editorial Copyedit Cycle

Papyrus's `papyrus editorial diagnose` is a **read-only slop scan** of a draft
against a publication's style profile. The scan/options engine is
**[Limatus](https://github.com/AnthusAI/Limatus)** (public SDK: `limatus.diagnose`,
`limatus.generate_options`, or `python -m limatus editorial …`). Papyrus loads
house drafts and `style-profile.yml` files and calls that SDK; it does not
host a forked editorial engine. Diagnose never rewrites anything itself — it
emits structured findings (redundancy, voice mismatch, vague claims, empty
lead-ins, density) with a stable `finding-*` id, a span, an excerpt, and a
rationale. Everything after that — what to skip, what to rewrite, which
rewrite to actually use — is editorial judgment. That judgment is the point of
this skill; the CLI commands are just plumbing.

**Never rewrite prose "by feel" without running diagnose first** when you're
doing the fine-grained, one-article, id-by-id version of this cycle (Steps
2-6 below). The scan catches real repetition and voice drift that's easy to
miss on a read-through, and it gives you a stable id to reason about instead
of vague back-and-forth about "the third paragraph."

At larger scale — reviewing many articles, or making bigger holistic edits
per the user's direction rather than fine-grained redlines — running the full
CLI pipeline on every single article isn't always the best use of time, and a
careful read-through catches things diagnose doesn't check for at all:
outright typos, doubled words, corrupted/orphaned sentence fragments, broken
markdown/JSX syntax, and factual inconsistencies (a stat or date that
contradicts itself elsewhere in the same piece). None of that is a redundancy
or voice-mismatch finding — it just requires reading the whole thing like an
editor would. In a full-site pass across 79 articles, these were often the
most valuable catches: a genuinely broken opening sentence, a leftover
internal draft note left in published copy, a citation's date cited two
different ways in the same article.

**Banned lexicon is worth a deliberate pass even when you skip diagnose.**
The style profile's `rules.bannedIntensifiers` / `bannedPhrases` (e.g.
"leverage," "seamless," "revolutionary," "cutting-edge," "unlock," "game-
changing") turned up repeatedly across older articles in that same full-site
pass — more often than any other single issue. Diagnose does check for these,
but if you're skimming quickly across many pieces, it's cheap enough to just
skim for the banned list directly (or grep it) rather than skip it entirely
because you didn't run the full scan.

## Prerequisites

Run everything from the Papyrus repo root:

```bash
export PAPYRUS_ALLOW_CROSS_ROOT=1
export PYTHONPATH=src
```

`editorial diagnose` needs nothing else. `editorial options` (Step 4) calls an
LLM and needs `OPENAI_API_KEY`. **If it isn't set, stop and ask the user to
set it** — in Papyrus's own `.env` or exported in the shell. Do not go looking
through sibling projects' `.env` files for a key on your own initiative, even
if you've done that once before in this environment with explicit sign-off.
That was a one-time, explicitly-granted exception, not a standing permission —
borrowing a key from an unrelated project is exactly the kind of action that
needs a fresh, explicit yes each time.

## Step 1 — Locate the draft and profile

You need:
- **Draft path**: the article's `.md` file (e.g. a Newsroom story's `article.md`).
- **Profile path**: `publications/<publication>/style-profile.yml` for whichever
  publication the draft belongs to. Don't assume Anth.us — check the draft's
  location or ask.

If either is ambiguous, ask rather than guessing — a scan against the wrong
profile produces findings that don't apply.

## Step 2 — Run diagnose

```bash
ART="<path to article.md>"
PROFILE="publications/<pub>/style-profile.yml"
BASE="/tmp/<slug>-<id>"   # or wherever you're keeping scratch output

python3 -m papyrus.cli editorial diagnose \
  --draft "$ART" \
  --profile "$PROFILE" \
  --output "$BASE.json" \
  --markup-out "$BASE.diagnosis.md" \
  --xml-out "$BASE.diagnosis.xml"
```

`$BASE.json` is the machine contract you'll actually work from. The `.md`/`.xml`
outputs are the same findings in human-readable markup — nice for a quick
read, not needed for the steps below.

## Step 3 — Review findings and write decisions.json

Read `$BASE.json`. Every finding needs a decision: `skip`, `rewrite`, `delete`,
`keep`, or `add`. Decisions are keyed by the **leaf finding id** — each member
of a `repetition_groups` group carries its own `id` (plus the group's id under
`group`); decide on the leaf id, not the group id, since that's what the
markup and the options step both address.

This is the step that actually requires judgment. Two things worth knowing
before you start marking things `rewrite`:

**A repeated phrase is not automatically redundancy.** Real prose reuses
structure on purpose:
- An anecdote opened at the top of a piece and echoed at the close (a
  narrative bookend) will trip the redundancy detector — that's usually the
  piece's actual payoff, not a mistake.
- A heading restated as its paragraph's topic sentence ("Kanbus organized the
  work" as a heading, then "But Kanbus organized the work..." as the next
  paragraph's opener) is a standard thesis-then-develop pattern.
- A recurring rhetorical device (e.g. a "not A, but B" contrast used two or
  three times across a long piece) is a rhythm choice, not a crutch — unless
  the *specific wording* is reused with no rhetorical purpose, which is a
  different and real problem.
- Two sentences flagged together because they share proper nouns or markdown
  links, but make genuinely different points, are usually false positives —
  check what each sentence actually *claims* before trusting the flag.

**Passive voice is not automatically wrong.** The style profile probably
prefers active voice, and usually should — but check whether the passive is
doing real work first: withholding an actor on purpose for a later reveal, or
avoiding misattribution when the actor is genuinely ambiguous (one of several
possible agents did something, and naming one would overclaim).

Write `decisions.json`:

```json
[
  {"schemaVersion": 1, "finding_id": "finding-...", "decision": "skip", "note": "why"},
  {"schemaVersion": 1, "finding_id": "finding-...", "decision": "rewrite", "note": "why"}
]
```

Always fill in `note` — it's the paper trail for why a finding was skipped or
flagged, and it's what you'll want to show the user later.

## Step 4 — Generate options (only for findings marked `rewrite`)

```bash
python3 -m papyrus.cli editorial options \
  --draft "$ART" \
  --profile "$PROFILE" \
  --diagnosis "$BASE.json" \
  --decisions "$BASE.decisions.json" \
  --output "$BASE.options.json"
```

This returns 2–3 patch options per rewrite finding, each with a `reason` and
(if the pipeline includes the voice-fidelity check) a `voiceFidelityWarning`
that fires when an option drops a contraction the flagged text had. Read that
warning — it's telling you the option may not sound like the author even
though it's otherwise a fine sentence.

## Step 5 — Choose and apply: options are candidates, not mandates

**You are not required to pick one of the 2–3 generated options verbatim.**
The options step is a suggestion engine, not a constraint. If you can see a
better replacement than any of the three — because it keeps a contraction the
author actually uses, or matches phrasing from elsewhere in the piece, or is
just tighter — write that instead. When you do, say so explicitly (call it a
manual override and say why) so whoever reviews this later knows the
generated options weren't good enough on their own, rather than assuming you
picked the top-ranked one.

Apply chosen replacements to a **working copy**, never the source draft,
using the finding's span:

```python
draft_path = "..."
with open(draft_path, encoding="utf-8") as f:
    text = f.read()

patches = [
    (start, end, "replacement text"),
    # ...
]
# apply from the end so earlier offsets stay valid
for start, end, repl in sorted(patches, key=lambda p: -p[0]):
    text = text[:start] + repl + text[end:]

with open("/tmp/.../working-copy.md", "w", encoding="utf-8") as f:
    f.write(text)
```

Do not touch the real draft file unless the user explicitly asks you to apply
changes to the source — this whole cycle is designed to produce a reviewable
working copy first.

## Step 6 — Verify: re-run diagnose on the edited copy

Don't just assert the edit helped — check:

```bash
python3 -m papyrus.cli editorial diagnose \
  --draft "/tmp/.../working-copy.md" \
  --profile "$PROFILE" \
  --output "$BASE-after.json" \
  --markup-out "$BASE-after.diagnosis.md" \
  --xml-out "$BASE-after.diagnosis.xml"
```

Compare finding counts and `density` metrics (`wordCount`, `lexicalDensity`,
`gzipRatio`) between the before and after scans. You want to see the findings
you targeted resolved, no *new* findings appearing elsewhere, and density
metrics holding steady or improving. If something new shows up, look at it
before calling the edit done — an edit that trades one problem for another
isn't actually finished.

## Step 7 (optional) — Build a visual before/after artifact

For a reviewable redline (inline strikethrough/insertion in the article body,
a findings apparatus explaining every skip/rewrite decision, and the re-scan
comparison table), assemble a `redline_input.json` per
[`references/redline_input_schema.md`](references/redline_input_schema.md) and run:

```bash
python3 scripts/build_redline.py redline_input.json /tmp/redline-output.html
```

Then publish the output with the Artifact tool. This is a documented add-on,
not a default step — build it when the user wants something to actually look
at, not for every quick edit.

## When this keeps happening, fix Papyrus instead of special-casing it

If the same kind of gap shows up across multiple articles — the model keeps
missing a voice pattern, keeps flattening a specific construction, keeps
mishandling a category of finding — that's a signal to improve
`publications/<pub>/style-profile.yml`, `editorial-rewrite-skill.yml`, or the
prompt/lint logic in **Limatus** (`limatus` package / AnthusAI/Limatus repo),
rather than re-litigating it in `decisions.json` every single time. That's a
separate, occasional activity from running the cycle — mention it to the user
if you notice the pattern, but don't go patch Limatus or Papyrus uninvited.
