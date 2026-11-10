---
name: reporting
description: Research a Papyrus story while recording immutable draft versions, consulted and cited references, and attributed reporting notes in its publication.
---

# Reporting

Work on the assigned topic and publication. Inspect repository instructions and active work; preserve other agents' edits. The reusable skill belongs in Papyrus, but editorial records belong in the selected publication's backend, never its product tracker. Before writing, verify the publication repository/configuration, endpoint and authoring identity, then read the existing Item to resolve its actual `lineageId`; an Item version id is not the story lineage. Keep the assigned stage and unpublished status unless authorized otherwise. Use project Kanbus for scoped development work, not as an alternative editorial store.

A story is an Item lineage. All drafts, Reference links and Messages hang off that lineage. Never overwrite historical article text: every article change is a new version. The supported save operation marks the previous version superseded without replacing its text. Attribute agent work as "AI"; do not invent human authorship. Messages come only from people: never write a `Message` for machine work, and never run `papyrus stories note` (that is a person's note, and under a person's login it would carry their name). Record your own notes with `papyrus stories agent-note`.

## Current editorial context

Before research, fetch current guidance from the selected publication:

```bash
papyrus editorial context --backend cloud --story STORY_LINEAGE --format json
```

Apply its `text` and precedence, surface conflicts/warnings, and record `contextHash` plus source revisions in the change reason of the version you save. Stop on unavailable required policy, scope mismatch or authorization errors. Never silently replace hosted policy with local seeds. Keep evolving policy out of this static skill and private doctrine out of reader copy.

## Preflight and source registration

Use the installed `papyrus` CLI or the project's existing Python environment (`poetry run papyrus` where configured). Inspect current help/source before execution; mutations currently write by default, with `--dry-run` for preview and no `--apply`. Do not repair deployment/schema/authentication problems or bypass the supported CLI to make a write succeed. If unavailable or blocked, provide each unexecuted command and the complete contents of every input file, clearly identifying what actually ran.

Name the site when more than one is signed in: `papyrus --site SITE_HOST <group> <command>` (or `PAPYRUS_SITE`); the flag goes before the group. Use only commands in this skill or in `papyrus <group>` listings. If your CLI has `papyrus guide`, read it first. On older builds `--help` may print only a usage line: then `docs/operator-cli.md` and `docs/story-reporting.md` in the Papyrus repository are the reference. Never invent a command, flag or relation name; if one is missing, say so in the handoff.

Find existing References by exact source URL in the selected publication. `stories link-reference --reference` takes a **Reference record id**: it loads that record and derives its lineage. `stories agent-note --reference` takes the **Reference lineage id**. Resolve both from records, never guess them.

If a source needs registration, inspect current `papyrus references create-from-catalog` support and the publication's steering configuration. The supported intake is:

```bash
papyrus references create-from-catalog --config PUBLICATION_STEERING.yml --corpus-key CORPUS --catalog catalog.json --status pending --ingestion-rationale "why this source matters"
```

The current catalog shape is `{"items":[{"item_id":"stable-source-id","source_uri":"https://example.org/source","title":"Source title","media_type":"text/html","ingestion_rationale":"Reporting relevance"}]}`; verify it against the current CLI/source and read back the resulting Reference id and lineage. Do not fabricate a Reference id or silently accept a pending source; follow the publication's intake policy before promoting it to evidence. Record the concrete registration command and catalog contents in the handoff.

## Reporting sequence

The order of the steps for a Story, who does each and what comes next is defined once in [docs/story-procedure.md](../../../docs/story-procedure.md). Run `papyrus stories next --story LINEAGE` to see it for this Story; the outline is the editor's step and comes after the research. Every Story has a checklist made from it: record a step you skip or find not applicable with `papyrus stories step --story LINEAGE --step KEY --state skipped|not_applicable --reason "why" --agent NAME` (a skip without a reason is refused), and a review step is done only with a findings note. An open required step blocks publishing.

1. Read back the story and its versions (`papyrus stories show`, `papyrus stories versions`).
2. Research. Immediately attach every source you read as `consulted`; register it through supported intake if missing. Record findings with `papyrus stories agent-note` and in each saved version's change reason; do not append Messages. Separate source findings, attributed claims, inference and open questions; never claim more than the source establishes.
3. After each substantial article change, save a new version with a clear reason. Use valid Markus citation syntax and keys supported by the current renderer.
4. Change every Reference actually cited in the draft to `cited` with its matching Markus citation key. Leave uncited sources `consulted`.
5. Associate (below): tag Concepts, then link related Stories and References. Do it once the Story has a draft or a settled outline, and again if its subject changes.
6. Finish with a handoff (your final report, not a Message) listing unresolved questions, limitations and next reporting steps; raise a review request (`papyrus reviews raise --subject-type item --subject-id <version id> --mode soft_review ...`) when a person must decide something. Read back versions, Reference roles/keys and notes; verify the publication, stage and unpublished status. Report the lineage, versions, references, notes, all commands executed, input files and any blockers.

```bash
papyrus stories show --story LINEAGE
papyrus stories versions --story LINEAGE
papyrus stories save-version --story LINEAGE --body-file draft.md --front-matter-file front-matter.yml --reason "what changed" --author-label "AI"
papyrus stories link-reference --story LINEAGE --reference REFERENCE_ID --role consulted --note "why it matters" --author-label "AI"
papyrus stories link-reference --story LINEAGE --reference REFERENCE_ID --role cited --citation-key KEY --author-label "AI"
papyrus stories agent-note --story LINEAGE --agent "AI" --summary "one line" --body-file note.md [--reference REFERENCE_LINEAGE_ID] [--version N]
```

An agent note is saved on the story and shown labelled as AI in `stories show` and the Reporting trail. `--agent` is only a label; the newsroom records who ran the agent from the sign-in.

`--front-matter-file` is optional after the initial outline when unchanged. Keep an auditable record of command results and inputs; do not claim a dry run or prepared command was executed as a write.

## Associations: Concepts and related content

Three different things; never mix them up.

| Association | Command | Relation | Meaning |
| --- | --- | --- | --- |
| Concept tag | `stories link-concept` | `tagged_with` | the Story is about this accepted Concept |
| See also | `stories link-story` | `see_also` | "read this too": another published Story or Post (`--to`), or an accepted Reference (`--reference`) |
| Evidence | `stories link-reference` | `consulted` / `cited` | the reporting trail: sources you read or cite (never see-also) |

The only relation names are `see_also` and `tagged_with` (plus `mentions`, which the system writes). Never pass or invent a relation name; no command takes one. Rows named `related_to` are legacy being migrated: never write one, and report any that `check-links` shows. No purging: a link command changes the record, and the page refreshes by itself within about five minutes. Do not run any purge or invalidation.

### 1. Find the Concepts

A Concept is an accepted node in the site's knowledge graph. You can only tag with one that exists: matching is exact (name, alias, #hashtag or node key, case ignored); nothing is created, guessed or fuzzily matched.

```bash
papyrus knowledge concepts search "what the story is about, in a sentence" --limit 10
papyrus knowledge concepts search --list            # every accepted Concept, alphabetical; works without any key
papyrus knowledge concepts related --concept "Waymo" --limit 10
```

- Search by meaning needs a vector index and an embedding key. Without them the command prints a NOTE and matches names only. When you see that note, do not conclude "no Concept exists": run it with several short phrases (the product, the method, the field, the people or organizations, the problem), then read `--list` and choose from the names yourself.
- Search with the Story's main subjects, not pasted paragraphs. Try the title, then each named organization, method and domain term from the body.
- `concepts related` shows Concepts near one you already trust (confirmed links with the editor's explanation, aliases, co-occurrence): use it to find the sibling Concepts you did not think of.
- `stories show` does not list Concepts. The Concepts a Story already carries are the `direct` ones on the `concepts:` line of `stories suggest-links`; `link-concept` also reports `exists` for a tag already there.
- A Reference can be tagged the same way: `papyrus references link-concept --reference REFERENCE_ID --concept "Name" --note "why" --dry-run`.

Tag the Concepts the Story is substantively about (usually 3 to 8): its central subject, the methods and organizations it analyses, not every term it mentions. Prefer a specific Concept over a broad parent, and add the broad one only if readers would browse by it.

```bash
papyrus stories link-concept --story LINEAGE --concept "Name" --concept "#hashtag" --note "why it fits" --dry-run
papyrus stories link-concept --story LINEAGE --concept "Name" --concept "#hashtag" --note "why it fits"
```

Read each result line: `exists` means it was already tagged (nothing written); `rejected` means a person rejected that tag, so leave it; a warning that the Concept "has no public wiki page" is information, the tag is still valid. An unknown name lists the closest accepted Concepts: choose one of those or drop the tag. If the right Concept does not exist, do not create it and do not substitute a vaguer one; name it in your findings note as "Concept wanted: NAME (why)" for an editor.

### 2. Find related Stories, Posts and References

```bash
papyrus stories suggest-links --story LINEAGE --limit 8
papyrus stories suggest-links --story LINEAGE --kinds references --limit 10 --json
papyrus references search "short topic phrase" --limit 10 --json     # find a specific Reference by keyword and meaning
```

`suggest-links` is read only and needs no key. It starts from the Story's tagged Concepts (so do step 1 first; a Story with no Concepts returns nothing), widens to nearby Concepts, and ranks published articles, posts and accepted References that carry them. Each line shows the shared Concepts, the path (`direct`, or `via A, then B`: weaker) and the exact command to link it. It leaves out the Story itself and what is already linked. The score only orders the list: you judge each candidate. `references search` is the way to look for one particular source the ranking missed; its `--json` gives each Reference's `id` and `lineageId`.

Judge each candidate by reading its title and, for anything you will link, its summary (`papyrus stories show --story CANDIDATE` for a Story; `papyrus references show REFERENCE_ID` for a Reference). Link when a reader finishing this Story would want that one next: it extends, contradicts, supplies the method or data behind, or is the same case from another angle. Do not link when:

- the only overlap is a broad shared Concept or a `via` path through an unrelated Concept;
- it is the same document or the same finding the Story already cites (cite or consult it instead);
- it is thin, off-topic, a restated headline, or says the opposite without the Story addressing it;
- a better candidate covers the same ground (link the best one or two per angle, not all).

```bash
papyrus stories link-story --story LINEAGE --to OTHER_LINEAGE_OR_SLUG --note "why" --dry-run
papyrus stories link-story --story LINEAGE --to OTHER_LINEAGE_OR_SLUG --reference REFERENCE_ID --note "why" --author-label "AI"
```

`link-story` checks every target before writing anything; a Story target should be published (an unpublished one gets a warning and will not show), and a Reference must be accepted. Repeating a link writes nothing. A Reference you relied on for the draft is evidence, not see-also: use `link-reference` (Reporting sequence). Linking is add-only; there is no unlink command, so be sure first.

Audit what you did: `papyrus stories check-links --story LINEAGE` (read only) lists links and tags that are not the official shape.

### 3. The checklist steps

Every Story's checklist has steps for these two associations (`papyrus stories next --story LINEAGE` lists the exact keys on your build: `concepts`, "Associate with relevant Concepts", and `related_content`, "Add related associations"; older builds have only `related_content`, and it may be optional). Where required they block publishing like the review steps. Close each one with a findings note, or skip it with a reason:

```bash
papyrus stories step --story LINEAGE --step concepts --state done --note "Tagged: A, B, C. Considered and left out: D (too broad). Wanted but missing: E." --agent "AI"
papyrus stories step --story LINEAGE --step related_content --state done --note "Linked X, Y (why). Left out Z (same finding we cite)." --agent "AI"
papyrus stories step --story LINEAGE --step related_content --state skipped --reason "No published Story or accepted Reference shares more than a broad Concept." --agent "AI"
```

Mark `done` when you did the work, even if the answer was "link nothing", and the note says what you linked and what you left out and why. Mark `skipped` only when you did not do the step (for example the Story has no accepted Concept that fits, or the site has nothing published yet) and `not_applicable` when the step cannot apply to this Story; both need a specific reason, and a skip without one is refused. A `step --dry-run` previews it.

### 4. Create a Story, a note

`papyrus stories create --title TEXT --type post|article [--section KEY] [--stage idea|assignment|reporting] [--reference REFERENCE_ID] --dry-run` makes a Story at a stage (default `idea`); `--type` names the Story type, and a Story with no type cannot be published (`papyrus stories set-type --story LINEAGE --type post` fixes an unpublished one). A post has no byline: never put "By ..." or an invented author in a post body or front matter. Write your reasoning on the record with `stories agent-note` (not `stories note`).
