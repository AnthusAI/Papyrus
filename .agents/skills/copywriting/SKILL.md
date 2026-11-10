---
name: copywriting
description: Turn Papyrus reporting and References into reader-facing story copy for a publication — evidence-first, in the publication's voice, attributed to AI, checked against the site's editorial policies before every save, saved as a new version, never published. Use when writing or rewriting a story, the body of a story that started as an idea, or a trend story drawn from several References.
---

# Copywriting

> **CLI syntax:** the exact `papyrus` commands for this work, with the flags each takes, are in [docs/agent-cli-guide.md](../../../docs/agent-cli-guide.md) (or run `papyrus guide`). `papyrus <group> <command> --help` prints a command's real usage, its lane and whether it writes. Do not guess a flag.

Stories live in the publication's newsroom backend, not in Git. Resolve the
publication and the story lineage from its configuration and live records (an
item version id is not a lineage). Read the story's current version, its linked
References (`papyrus stories show --story LINEAGE`), and any reporting packets.
Do not substitute assumptions for missing reporting. Name the site when several are signed in (`papyrus --site SITE_HOST <group> <command>`). Use only documented commands and never invent a command, flag or relation name. A post has no byline: never write "By ..." or an invented author into a post.

The order of the steps for a Story, and what comes next, is defined once in [docs/story-procedure.md](../../../docs/story-procedure.md); run `papyrus stories next --story LINEAGE` to see it. Every Story has a checklist made from it: record a step you skip or find not applicable with `papyrus stories step --story LINEAGE --step KEY --state skipped|not_applicable --reason "why" --agent NAME` (a skip without a reason is refused), and a review step is done only with a findings note. An open required step blocks publishing.

## Fetch guidance first

```bash
papyrus editorial context --backend cloud --story STORY_LINEAGE --format json
papyrus editorial pack
```

The context `text` is the publication's mission and policy (and the section's,
when the story has one), in precedence order. The pack's policies carry the
house voice, banned phrases and judgment questions. **The same data instructs the
writer and the checker**: read each policy's guidance before writing, not only
after the check flags you. Required-policy or authorization failures stop the
pass. There is no offline policy mode, and doctrine is never copied into reader copy, public
repositories or logs.

## The writing contract

These hold for every publication. The site's policies add its own rules on top.

- **Evidence first.** Every external claim is cited to a Reference with a valid
  Markus citation key. Prefer primary sources (papers, model cards, code,
  documentation, datasets) over coverage of them. Keep the source's
  qualifications, such as sample sizes, conditions and limits.
- **Say what the publication adds.** A story that only restates a source's
  headline is not ready. Bring the comparison across sources, the worked example,
  the measurement, or the failure case the publication's mission asks for. If the
  evidence for that is missing, stop and say what is missing; don't write around
  it.
- **Tense is a claim.** Write about the publisher's own systems in the past tense
  for history ("we ran", "we measured"). Use the future tense for offers ("we'll
  run this for you"). Use the present tense only for what you verified is true
  today. Never write a present-tense production claim from memory or from an older
  article.
- **No boilerplate.** Don't reuse a closing section, call to action or paragraph
  from another story. Write each one for this story. Copied text goes stale in
  every story at once.
- **Current names.** Use product and proper names as the site's policies and
  glossary give them. Old names in older articles are not a source.
- **Label illustrative figures, composites and pilot results as such.** Keep
  opinion apart from evidence. Don't promise what hasn't shipped.
- **No speed bragging and no hype.** Describe the problem, the mechanism and the
  honest limits.
- **A generated image has no credit line at all; leave credit off.** A real third-party credit
  is written as the source gives it.
- A story based on a Reference has its own text: never seed it from the
  Reference's captured text (the copy guard refuses runs of 12 or more shared words).

## Check before you save

Run the site's checks on your own draft and fix what you can before anyone sees
it:

```bash
papyrus editorial check --draft draft.md
```

Read `lanes`: if the judgment lane ran with zero detectors, or did not run,
claims and voice were not checked. Say so in your handoff. Fix rule and judgment
violations yourself. For anything you can't fix without new evidence, leave the
finding and report it. Then follow
`.agents/skills/editorial-copyedit-cycle/SKILL.md` for options a person chooses.

## Social preview review (`review_social`)

Run `papyrus stories lens-check --story LINEAGE --lens social --static web`. Check C4 fetches the planned share picture; read its finding, do not assume. A built address proves nothing about the file. A WebP, AVIF, small, oddly shaped, missing, invalid or unreachable picture is a warning or "Could not check" (not verified), never a pass: make a JPEG or PNG share rendition and keep modern formats for the page, and do not pad or upscale a small image without recording it. Read title, description and picture together for relevance, legibility, alt text and misleading context. Record the tested URL, format, dimensions and result in the `--note` of `stories step --step review_social`, saying what you verified directly and what you only infer about a platform. After publishing, fetch the live page, check `og:image` and `twitter:image` match the tested address and that the address fetches publicly; report CDN or platform preview-cache staleness separately. A separate share picture needs front matter `image` (`ogImage` is only a fallback after `image` and `cover`). Details: [docs/agent-cli-guide.md](../../../docs/agent-cli-guide.md).

## Save, record, hand off

```bash
papyrus stories save-version --story LINEAGE --body-file draft.md \
  --front-matter-file front-matter.yml --reason "what changed; context hash; sources" --author-label "AI" --dry-run
```

Then save without `--dry-run`. Every substantial change is a new version; earlier
versions are kept. Attribute your work as "AI" and never invent human authorship.

- **Record provenance on the record, not in Messages.** Messages come only from
  people. Put the context hash and source revisions in the version's change
  reason. Report open evidence gaps and unresolved questions in your handoff.
  When a person must decide something, raise a review request:
  `papyrus reviews raise --subject-type item --subject-id <version id> --mode soft_review --reason "…" --ask "…"`.
- Keep the assigned stage and unpublished status unless separately authorized.
  **Never publish as a side effect of writing or editing.** Publishing is a
  person's decision, or a site's explicit automatic-publish setting.
- **Required, after every save-version and before you ask anyone to approve a publish: show the editor the console link of the version you just saved.** `stories save-version` prints it as a `console ... story <url>` row (the exact VERSION id link; the `story-board` row means only "latest"). The editor reviews the draft in the web console, not on a production page. If the row says `unavailable` (the console address is unknown) say so and give `papyrus links --story LINEAGE --version N --console-url ...` once they supply it; never guess an address, and say plainly if you did not open the link. Details: [docs/console-links.md](../../../docs/console-links.md).
- Read back the result: `papyrus stories versions --story LINEAGE`.

## Associate before publish

After the draft and the copy edit, the Story needs its Concepts and related associations. The full procedure, with decision rules, is in the reporting skill (`../reporting/SKILL.md`, "Associations"). In short:

```bash
papyrus knowledge concepts search "main subject of the story" --limit 10     # or: --list; names only if no vector index
papyrus stories link-concept --story LINEAGE --concept "Name" --note "why" --dry-run
papyrus stories suggest-links --story LINEAGE --limit 8
papyrus stories link-story --story LINEAGE --to OTHER_LINEAGE --reference REFERENCE_ID --note "why" --dry-run
papyrus stories check-links --story LINEAGE
papyrus stories step --story LINEAGE --step concepts --state done --note "Tagged A, B. Left out C (too broad)." --agent "AI"
papyrus stories step --story LINEAGE --step related_content --state skipped --reason "specific reason" --agent "AI"
```

- Relations are `tagged_with` (Concept tag, exact existing Concepts only, never created) and `see_also` (read this too, Story or accepted Reference). Sources you relied on are evidence (`link-reference` with `consulted`/`cited`), not see-also. `related_to` is legacy: never write it.
- Tag the Story first: `suggest-links` starts from the Story's Concepts and returns nothing without them.
- Do not purge anything; a link shows on the page within about five minutes.
- The checklist steps "Associate with relevant Concepts" (`concepts`) and "Add related associations" (`related_content`) are closed with a findings note (what you added and what you left out, and why) or skipped with a reason. A step skipped without a reason is refused. Run `papyrus stories next --story LINEAGE` for the keys on your build.
