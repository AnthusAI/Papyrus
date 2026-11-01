---
name: copywriting
description: Turn Papyrus reporting and References into reader-facing story copy for a publication — evidence-first, in the publication's voice, attributed to AI, checked against the site's editorial policies before every save, saved as a new version, never published. Use when writing or rewriting a story, the body of a story that started as an idea, or a trend story drawn from several References.
---

# Copywriting

Stories live in the publication's newsroom backend, not in Git. Resolve the
publication and the story lineage from its configuration and live records (an
item version id is not a lineage). Read the story's current version, its linked
References (`papyrus stories show --story LINEAGE`), and any reporting packets.
Do not substitute assumptions for missing reporting.

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
- Read back the result: `papyrus stories versions --story LINEAGE`.
