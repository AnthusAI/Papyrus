# Newsroom cloud procedures runbook

How seeded Tactus procedures reach cloud `ProcedureVersion` records and how to verify a run.

Papyrus newsroom procedures are cloud records (`ProcedureDefinition` and
`ProcedureVersion`) managed in `/newsroom` Administration under the
`Procedures` panel.

A site's deploy registers every core procedure and the site's own, with no step by hand (see
[the procedure runner](procedure-runner.md#registering-procedures-the-deploy-does-it)). The Amplify build runs
`papyrus procedures seed-required` after the backend deploys; the version's source is stored as a `code` attachment,
and unchanged procedures write nothing.

The 14 core procedures (the file under `src/papyrus_content/data/procedures/`, which `procedures/newsroom/` links to):

| Kind | File | What it does |
| --- | --- | --- |
| `newsroom.research.explorer` | `research_explorer.tac` | Builds structured research packets for assignment-backed newsroom workflows |
| `newsroom.reporting.context` | `reporter.tac` | Builds reporting context packets from assignment-backed runs |
| `newsroom.researcher` | `researcher.tac` | Builds a research packet payload for one assignment (dry run) |
| `newsroom.copywriter` | `copywriter.tac` | Turns a reporting packet into a draft payload (dry run) |
| `newsroom.editor` | `editor.tac` | Plans an edition's assignments (dry run) |
| `newsroom.reference.summarization` | `reference_summarization.tac` | Source-voice Reference summaries, titles and subtitles |
| `newsroom.rotating.section.selector` | `rotating_section_selector.tac` | Recommends the rotating desk for an edition |
| `references.curate` | `reference_curation.tac` | Captures, summarizes and extracts one Reference before review |
| `story.editor-review` | `editor_review.tac` | The stage bot that reviews a story version |
| `story.localize` | `story_localize.tac` | Translates one published Story into one language |
| `ontology.relationship-explainer` | `ontology_relationship_explainer.tac` | Explains semantic relations |
| `ontology.concept-profiler` | `ontology_concept_profiler.tac` | Builds concept profiles |
| `ingestion.reference.register` | `ingestion_reference_register.tac` | Normalizes one reference intake payload (dry run) |
| `submissions.email.process` | `email_submission_processor.tac` | Turns inbound submission emails into Reference intake |

A site's own procedures are listed in the site's `papyrus-site-procedures.json`. The worked example is Distinctive Mark's
`distinctive.ttab.ruling-analysis` (`procedures/ttab_ruling_analysis.tac` plus the skill `.claude/skills/ttab-ruling-analysis/`):

```json
{"version": 1, "procedures": {"distinctive.ttab.ruling-analysis": "procedures/ttab_ruling_analysis.tac"}}
```

A site kind cannot take a core kind's name unless the file lists it under `"overrides"`.

After editing a `.tac` file, the next deploy publishes it as a new version. To see what a deploy would do, or to fail on drift between Git
and the site (a published version that differs from the file, or a procedure never registered):

```bash
poetry run papyrus procedures seed-required --dry-run
poetry run papyrus procedures seed-required --check
```

Procedure kinds and the registry:

- The first line of every procedure file declares its kind:
  `-- papyrus-procedure-kind: <kind>`.
- `corpora/papyrus-required-procedures.json` lists, under `procedures`, the file name that
  runs for each kind, and under `requiredCliProcedures` the kind each CLI command needs.
- `poetry run python -m papyrus_content.procedure_registry` checks that the three agree
  (a file without a kind, two files with one kind, a registry entry whose file declares
  another kind or does not exist, a file the registry does not list, a CLI command whose
  kind has no entry, a kind with no `procedureMetadata`, metadata for a kind that is not
  registered). CI runs it, and `papyrus procedures seed-required` runs it first.
- `procedureMetadata` holds each kind's title, category, description, parameter schema and
  defaults. A default may be the token `$defaultLlmModel` or `$defaultCorpusKey`, filled in
  from the site when it registers. A test compares each schema with the `input` block of its file.
- The procedure files live in `src/papyrus_content/data/procedures/` so the wheel
  carries them (a PyPI install, a container job and a local pod have no checkout);
  `procedures/newsroom/<name>.tac` is a link to each, so every path in docs and
  commands still works. Code asks for a kind (`procedure_file_for_kind`) and gets
  the checkout's file when `PAPYRUS_ROOT/procedures/newsroom/<name>` exists, else the
  packaged one through importlib.resources. Edit the file under either path.

CLI cloud resolution contract:

- Required CLI procedure aliases are defined in
  `corpora/papyrus-required-procedures.json`
- `papyrus` resolves required procedure keys by alias, fetches
  cloud definitions by key, writes the selected `ProcedureVersion.tactusSource`
  into the run directory, executes that source with `tactus run`, and records
  the parsed output/error back on `ProcedureRun`
- If a required key is missing, CLI fails hard with explicit remediation:
  `Run poetry run papyrus procedures seed-required to preload standard procedures.` (a deploy has already done it)

Operator verification checklist:

1. Open `/newsroom` -> Administration -> Procedures.
2. Select a procedure row and verify `Version Draft -> Tactus/Lua Source`
   shows real code, not a placeholder.
3. Run `poetry run papyrus assignments run-research --assignment <id> ...` and
   confirm it resolves and runs the cloud procedure.
4. Inspect `.papyrus-runs/<run-id>/llm-context/summary.json` and
   `.papyrus-runs/<run-id>/llm-context/calls.jsonl` to verify the exact per-call
   LLM message history (including system prompt and user/tool messages) used during
   the agent run.
5. Use `.papyrus-runs/<run-id>/llm-context/execute_tactus_calls.jsonl` to verify
   tool-level context inputs (`assignment_context`, `assignment_agent_context`,
   `knowledge_query`, and any web calls) used during the run.

Current execution limitation (important):

- CLI-backed research/reporting runs execute cloud `ProcedureVersion.tactusSource`
  as user-editable Tactus code.
- Direct Lambda immediate execution still dispatches by procedure marker/key in
  `amplify/functions/assignment-action/handler.ts`; it does not yet execute
  arbitrary Tactus source inside Lambda.
