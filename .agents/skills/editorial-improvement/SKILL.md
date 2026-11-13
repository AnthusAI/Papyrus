---
name: editorial-improvement
description: >
  Take full editorial ownership of one published or drafted Papyrus Story and
  make it better in every way that matters, then publish the result: a
  sharper thesis and structure, rewritten headline, dek and blurb, copy
  editing, fact checking and new sources, figures and headline-picture
  candidates, and typesetting (pull quotes, two-column comparisons, notes,
  callouts). The agent decides and acts on its own, and a person reviews the
  finished article as a whole, not each edit. Use this whenever someone
  hands an agent an article URL or Story and says to improve it, rework it,
  make it more engaging or accessible, give it a point, restructure it, fix
  its pictures or layout, or "do an editorial pass", even when they only name
  one problem (a headline word, a missing thesis, a confusing section) and
  say the agent may change anything else. Also use it for a batch of such
  articles, or to write approved article ideas end to end in the same
  trusted mode.
---

# Editorial improvement

> **CLI syntax:** the exact `papyrus` commands are in [docs/agent-cli-guide.md](../../../docs/agent-cli-guide.md) (or run `papyrus guide`). Write commands run by default. Preview with `--dry-run`. Never guess a flag.

This skill is the trusted, whole-article mode. Whoever assigned the work has
handed you editorial judgment. They want to come back to a finished,
published article that is clearly better, and review it as a whole. They do
not want a list of proposed edits or a question every few minutes.

So act. Choose the thesis, rewrite the headline, cut the weak section, redraw
the diagram, add the pull quote, publish, check the live page, and then
report what you did and why. Be assertive about quality. Be careful about
what is true and about anything that is hard to undo. The rest of this page
says where that line falls.

It is the opposite of the [editorial copy-edit cycle](../editorial-copyedit-cycle/SKILL.md),
where findings are advice and a person picks each change. Use that skill when
someone wants to choose edits one by one. Use this one when they said "make
it better, I trust you." For drawing a figure, follow the [figures
skill](../figures/SKILL.md). For new sources and reporting notes, see
[reporting](../reporting/SKILL.md).

## What you may change without asking

- **Thesis and structure.** What the piece argues, the order of sections,
  which examples stay, which go, and what gets added.
- **Headline, dek and blurb.** The dek sits under the headline. The blurb is
  shown on index pages and cards. Each makes the point at once, and the two
  must say it differently (see [Write the dek and the blurb
  differently](../../../docs/agent-cli-guide.md#write-the-dek-and-the-blurb-differently)).
- **Body copy.** Copy editing, plain-language rewrites, tone, length and a
  little humour where it fits.
- **Facts and sources.** New research, new References, corrected or narrowed
  claims, and citations.
- **Pictures.** New or redrawn figures, a different headline picture,
  captions and alt text.
- **Typesetting.** Pull quotes, two-column comparisons, notes and callouts,
  image layout and section headings.
- **Links.** Internal links to related Stories, and see-also relations.
- **Publishing.** Publish the improved version and verify it live.

## What stays the person's call

These are hard to undo or belong to someone else. Leave them alone, and say
in the report if you think one should change.

- **The slug.** Changing it breaks links unless a redirect is written. Keep
  it even when the headline changes.
- **Retiring, unpublishing or merging Stories.**
- **Star ratings, and accepting or rating References in an editor's name.**
  File new References as pending.
- **Approval records.** Never write an `approvedBy` record, an "Approved by
  NAME" credit or a figure approval for a person who did not give one. If a
  publish gate demands one, stop and report the gate. Do not satisfy it.
- **CDN purges beyond the Story's own pages, and new sections or concepts.**
  Use the nearest existing ones and say what is missing.
- **Anything the site's AGENTS.md or the assigner's brief reserves.**

## How to work

### 1. Read before you touch anything

- **The live page.** Fetch it, and look at it the way its reader will.
- **The current stored version.** Run `stories show --story LINEAGE` for its
  state, then pull the current version's stored body and front matter with
  `stories pull --story LINEAGE --body-file body.md --front-matter-file front.yaml`
  (read only; `--version N` pulls an older one). Edit from that stored text. Never
  rebuild it from the live page or its Markdown twin: those have rewritten
  picture paths and no citation data.
- **The site's mission, policies and audience.** Run
  `editorial pack --section SECTION --output pack.json`. The audience in the
  pack is who you write for. Many sites' readers are not technical: if a
  reader in their eighties could not follow a paragraph, rewrite it.
- **The site repository's AGENTS.md, from `origin/develop`.** It says which
  CLI version to use against that site's backend, how figures are rendered
  and what is live. A CLI newer than the site's backend can fail on reads,
  so use the version it names.
- **Related Stories on the site.** Link to them, and never duplicate them.

### 2. Diagnose, then choose a thesis

Most weak articles are a list of sourced examples that never add up to
anything. Ask what the examples have in common that no single one shows.
Before rewriting, write down two or three candidate theses with a line of
evidence for each. Choose the one every example supports. If the evidence
only supports one, choose that.

Analysis is welcome, framed as the publication's reading ("Our reading of
the evidence…") and backed by the sources. Do not moralize, and do not hedge
everything until it says nothing.

If the assigner named a specific problem, solve that first and most visibly.
The named problem is what they will check.

### 3. Research and fact-check

- Every claim needs a source you actually opened. Read the passage, not the
  search snippet.
- Mark company-supplied numbers as the company's.
- When two sources disagree, say so instead of choosing one silently.
- If a claim cannot be supported, narrow it or cut it. Report what you left
  out.
- File new References from a catalog (`references create-from-catalog`),
  link them with roles, and cite them in front matter.
- When a fetch tool is refused, try another reader (a browser pane, `curl`),
  not a different claim.

### 4. Rewrite

Restructure so that:
- the opening sets up the thesis
- each section moves it forward
- the ending pays it off with a conclusion or a test the reader can watch,
  not a summary

Write plainly:

- **Explain jargon.** Give each technical idea an everyday comparison: a MIDI
  file is a player-piano roll, firmware is the program in a microwave.
- **Short paragraphs.** One idea each.
- **No AI-slop phrasing.** Cut lines that state the obvious for effect
  ("nobody could do it for him"), staged reveals ("Here is the catch", "Then
  came…", "They found something else"), punchline couplets, "It is X, and it
  is not Y" contrasts, and a clever closing kicker. Say plainly what
  happened, as the sources support it. Read every sentence you add, and ask
  whether a careful human editor would have written it.
- **No self-reference.** Phrases like "in this story", "our report on…" and
  "the sources used here" trip the policy check. Work references to other
  pieces into the prose as links.
- **No speed bragging.**

### 5. Pictures

The headline picture and the diagrams often decide whether anyone reads the
piece, and sites run A/B tests on them. So over-produce:

- Make at least one diagram that carries the thesis. A diagram that explains
  beats a decorative one.
- Make two or more alternative headline pictures.
- Put the best one or two live. Keep the rest as source files in your
  working folder and list them in the report. Do not save candidates as
  unpublished draft versions.

Follow the site's figure rules and the [figures skill](../figures/SKILL.md),
with these always on:
- Light and dark pictures every time.
- Never colour alone: use labels and marks, because some readers are
  colourblind.
- The site's own drawn and generated figures carry no credit line unless
  the site's rules say otherwise. Third-party pictures always carry their
  licence and credit.
- Use a generated image only where the site has image generation set up and
  you can see the result before applying it.

### 6. Typesetting

Use Markus directives where they help a reader skim and understand. The
names Markus accepts are `callout` (with `note`, `tip`, `warning` and
`caution`), `pull-quote`, `two-up` with `column`, `figure`, `details`,
`tabs`, `card`, `step-list`, `timeline`, `metric` and `bar-chart`. `::image`
and `::video` handle pictures and video (see
[markus-content-markup.md](../../../docs/markus-content-markup.md) and the
Markus language reference for attributes).

Good uses:
- A short "the short version" note near the top of a long piece.
- One or two pull quotes: short lines from the article, set away from the
  sentence they repeat.
- A `two-up` to set two attributed statements or a before-and-after side by
  side.
- A `details` block for material most readers can skip.

Each site styles these differently, and a site may not style some of them at
all. After publishing, look at every component on the live page. If one
renders as plain text, that is a site defect. Report it rather than
rewriting the article around it. Use `>` only where the site defines what a
blockquote means; on some sites it draws the large pull-quote panel.

### 7. Check, save, publish, verify

1. Run `editorial check --draft BODY.md` on the draft. Fix real violations.
   Reword false positives when the rewording is no worse, and note them when
   it would be.
2. Save the version with `stories save-version --story L --body-file B
   --front-matter-file F --images DIR --reason R`. Pass `--images` with
   every picture the body names, day and Night versions, whenever the body
   names pictures by local file name.
3. Close the Story's checklist steps honestly. A skip needs a real reason.
   Re-record the review steps against the version you publish.
4. Publish with `ops content publish --id L-vN --json`. Saving alone does
   not publish.
5. Fetch the live page with a cache-busting query. Check the headline, the
   new passages, every picture in both themes and every component. A
   "timed out" publish often still finishes within a minute, so check
   before re-running anything.

If Papyrus misbehaves (a refused save, a missing carried-forward picture, a
gate that cannot be met honestly), stop that step and report it with the
exact command and output. Do not work around it: no hand-written records,
no hand purges, no direct database or bucket writes.

## Report

The assigner reviews the whole article from your report and the live page,
so make the report easy to check:

- **Live URL and version.** The published version id, and the URL you
  verified.
- **Thesis.** The candidate theses you considered, the one you chose, and
  why.
- **What the assigner named.** How you solved the specific problem they
  raised, with the new passage quoted.
- **Opening and closing.** The new opening and closing paragraphs, quoted
  verbatim.
- **Structure.** A short summary of what moved, what was added and what was
  cut.
- **Sources.** Sources added, and claims narrowed or dropped, with why.
- **Pictures.** What is live, plus the candidate pictures and alternative
  headlines for A/B tests, each with its path.
- **Problems hit.** Policy flags, Papyrus defects and site rendering
  problems.
- **Left alone.** What you chose not to do, and anything on the person's-call
  list that you think should change.

## Assigning this work

When briefing an agent with this skill, give it:
- the article URL or lineage
- the specific problem, in the person's own words
- the site, and the CLI version to use if it differs from the default
- a working folder
- anything else reserved for a person

Then let it work, and review the published result.
