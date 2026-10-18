---
name: reporting
description: Research a Papyrus story while recording immutable draft versions, consulted and cited references, and attributed reporting notes in its publication.
---

# Reporting

Work on the assigned topic and publication. Inspect repository instructions and active work; preserve other agents' edits. The reusable skill belongs in Papyrus, but editorial records belong in the selected publication's backend, never its product tracker. Before writing, verify the publication repository/configuration, endpoint and authoring identity, then read the existing Item to resolve its actual `lineageId`; an Item version id is not the story lineage. Keep the assigned stage and unpublished status unless authorized otherwise. Use project Kanbus for scoped development work, not as an alternative editorial store.

A story is an Item lineage. All drafts, Reference links and Messages hang off that lineage. Never overwrite historical article text: every article change is a new version. The supported save operation marks the previous version superseded without replacing its text. Attribute agent work accurately (use `ChatGPT` for this agent); do not invent human authorship.

## Current editorial context

Before research, fetch current guidance from the selected publication:

```bash
papyrus editorial context --backend cloud --publication PUBLICATION_KEY --story STORY_LINEAGE --format json
```

Apply its `text` and precedence, surface conflicts/warnings, and record `contextHash` plus source revisions in a story Message. Stop on unavailable required policy, scope mismatch or authorization errors. For explicitly offline work use `--backend local --publication PUBLICATION_KEY [--section SECTION_ID]`; this is Git configuration, not proof of current hosted edits. Never silently replace hosted policy with local seeds. Keep evolving policy out of this static skill and private doctrine out of reader copy.

## Preflight and source registration

Use the installed `papyrus` CLI or the project's existing Python environment (`poetry run papyrus` where configured). Inspect current help/source before execution; mutations currently write by default, with `--dry-run` for preview and no `--apply`. Do not repair deployment/schema/authentication problems or bypass the supported CLI to make a write succeed. If unavailable or blocked, provide each unexecuted command and the complete contents of every input file, clearly identifying what actually ran.

Find existing References by exact source URL in the selected publication. `stories link-reference --reference` takes a **Reference record id**: it loads that record and derives its lineage. `stories note --reference` takes the **Reference lineage id**. Resolve both from records, never guess them.

If a source needs registration, inspect current `papyrus references create-from-catalog` support and the publication's steering configuration. The supported intake is:

```bash
papyrus references create-from-catalog --config PUBLICATION_STEERING.yml --corpus-key CORPUS --catalog catalog.json --status pending --ingestion-rationale "why this source matters"
```

The current catalog shape is `{"items":[{"item_id":"stable-source-id","source_uri":"https://example.org/source","title":"Source title","media_type":"text/html","ingestion_rationale":"Reporting relevance"}]}`; verify it against the current CLI/source and read back the resulting Reference id and lineage. Do not fabricate a Reference id or silently accept a pending source; follow the publication's intake policy before promoting it to evidence. Record the concrete registration command and catalog contents in the handoff.

## Reporting sequence

1. Read back the story and versions. Save a first outline draft with frontmatter `title`, `deck` (subtitle), and `blurb` (two or three lines for board/listings). On an existing story, this means the next version, preserving earlier versions.
2. Research. Immediately attach every source you read as `consulted`; register it through supported intake if missing. After each meaningful finding or decision, append a Message with a short summary and the relevant Reference lineage or draft version. There is no separate insight type: a note is a Message. Separate source findings, attributed claims, inference and open questions; never claim more than the source establishes.
3. After each substantial article change, save a new version with a clear reason. Use valid Markus citation syntax and keys supported by the current renderer.
4. Change every Reference actually cited in the draft to `cited` with its matching Markus citation key. Leave uncited sources `consulted`.
5. Finish with a Message listing unresolved questions, limitations and next reporting steps. Read back versions, Reference roles/keys and notes; verify the publication, stage and unpublished status. Report the lineage, versions, references, notes, all commands executed, input files and any blockers.

```bash
papyrus stories show --story LINEAGE
papyrus stories versions --story LINEAGE
papyrus stories save-version --story LINEAGE --body-file draft.md --front-matter-file front-matter.yml --reason "what changed" --author-label "ChatGPT"
papyrus stories link-reference --story LINEAGE --reference REFERENCE_ID --role consulted --note "why it matters" --author-label "ChatGPT"
papyrus stories note --story LINEAGE --author-label "ChatGPT" --summary "one line" --body-file note.md --reference REFERENCE_LINEAGE --version N
papyrus stories link-reference --story LINEAGE --reference REFERENCE_ID --role cited --citation-key KEY --author-label "ChatGPT"
```

For notes, `--reference` and `--version` are optional; use either or both when applicable. `--front-matter-file` is optional after the initial outline when unchanged. Keep an auditable record of command results and inputs; do not claim a dry run or prepared command was executed as a write.
