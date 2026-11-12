# Illustration and typesetting

The two stages between copywriting and publication. This page says what each stage is, who does it, what the command line can do today, and what is not built. The reporting stage has [story-reporting.md](story-reporting.md); the whole sequence is in [story-procedure.md](story-procedure.md).

## What exists

Both are values of `Item.stage` (`illustration`, then `typesetting`, then `published`) and both are columns on the stories board. In [the Story procedure](story-procedure.md) typesetting is a step marked "not built, optional": `papyrus stories next` reports it as `unknown`, never lists it as skipped, and the context pack says "(not built)" next to it. Illustration is a live step (template version 5): required for the Story types that need a cover, closed by an approved cover or by a person's recorded exception, and checked when a Story publishes ([The Illustration step](story-procedure.md#the-illustration-step)). The illustration and typesetting stages themselves are still places an editor moves a Story to by hand.

Nothing moves a Story into either stage by itself, and no agent or procedure works in them. An editor places a Story there by hand.

## Illustration

**What it should produce.** (Intent only.) The pictures a Story needs: a hero or inline image, diagram or chart, each with alt text and a credit, stored as `MediaAsset` rows and referenced from the Markus body. Where a Story was made from a Reference, a post carries the Reference's preview image as a remote, credited address; the illustration stage is the place to replace it or host a licensed copy ([reference-curation-pipeline.md](reference-curation-pipeline.md)).

**Who does it.** An editor, by hand, or an agent following the [figures skill](../.agents/skills/figures/SKILL.md) for a diagram, chart or illustration ([figures.md](figures.md)); a person approves each figure. There is no image generation in the repository.

**What the CLI can do today.**

- Draw a figure: `papyrus figures render FOLDER --design-system DIR` writes a light and a dark picture from one SVG source and checks both; `papyrus figures directive FOLDER` prints the `::image{}` line. See [figures.md](figures.md).
- Move the Story: `papyrus stories move --story LINEAGE --stage illustration [--reason "why"]`, or `stories save-version ... --stage illustration`.
- Save pictures with a draft: `papyrus stories save-version --story LINEAGE --body-file draft.md --images ./pictures` uploads each local picture the text uses, with an optional dark version, exactly as the editor's "Insert image" does ([saving a draft with its pictures](story-reporting.md#saving-a-draft-with-its-pictures)). This is the same command at any stage; it is not specific to illustration.
- In the newsroom editor, "Insert image" does the same by hand.
- In the newsroom editor, **Cover image** (on a saved Story) offers four royalty-free pictures from Wikimedia Commons at a time (PPY-5c9e9a): Accept one, reload for four more, type search words, or give up. With no words it searches from the title and summary and says so. Accept copies the picture into the site's own media with the same upload as "Insert image", puts it first in the body as `::image{... credit="Image: creator, licence, via Wikimedia Commons"}`, sets front matter `image` to the copy (and clears any Night counterpart of the old one) and records `coverImage` (source, file page, creator, licence, licence address, who and when). Saving makes the new Story version. The credit shows under the picture on the article page only; cards and index pages draw `image` and show no credit. Offered licences: public domain, CC0, CC BY; CC BY-SA is not offered until Ryan decides on share-alike (`lib/stock-images/licences.ts`). The search runs in the newsroom's Next server (`app/api/newsroom/stock-images`, editor or admin only, no key, one request at a time, User-Agent with `PAPYRUS_WIKIMEDIA_CONTACT`), not in the browser.

**What is not built.**

- Any command or agent that decides what a Story needs, makes or finds the picture, or checks rights and credit.
- Any use of the editor review's `illustrationPlan` (below).
- A check that alt text and credit are present.

## Typesetting

**What it should produce.** (Intent only; the editor review's plan fields name tables on phones, figures and pull-outs.) The reader-facing form of the copy: tables that work on a phone, figures placed, pull-outs chosen, so the Markus body renders as the editor intends before publication.

**Who does it.** An editor, by hand, in the newsroom editor. Publishing follows: `papyrus ops content publish --id ITEM_ID`, which is what makes a Story live; moving a Story to `published` does not.

**What the CLI can do today.**

- Move the Story: `papyrus stories move --story LINEAGE --stage typesetting`, or `--advance` on `save-version` for the next stage.
- A story-state automation can end a chain at `typesetting` ("no bot waits there"), as in the example chain in [automations.md](automations.md#story-state-triggers). That is a place to stop, not typesetting work.

**What is not built.**

- Any command or agent that lays out, checks or previews a Story's typesetting.
- Any use of the editor review's `typesettingPlan`.

## The editor review's two plans

The optional `editor_review.tac` procedure (off on every site) records an `illustrationPlan` and a `typesettingPlan` in `Item.metadata.editorReview` on the version it reviewed. They are advice written for a person. Nothing reads them: no later step acts on them, and `stories next` ignores them. See [editor agents](editor-agents.md#editor-review-stage-bot-beta), which lists "the illustration and typesetting stages acting on the plans" as not built.

## What a reporting agent should do

Guide the Story to copywriting and the draft. If an editor wants illustration or typesetting, say so in the Story's agent note and leave the move and the work to the editor; do not invent a procedure. Run `papyrus stories next --story LINEAGE` for the live state of every step.
