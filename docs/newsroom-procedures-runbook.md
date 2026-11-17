# Newsroom cloud procedures runbook

How seeded Tactus procedures reach cloud `ProcedureVersion` records and how to verify a run.

Papyrus newsroom procedures are cloud records (`ProcedureDefinition` and
`ProcedureVersion`) managed in `/newsroom` Administration under the
`Procedures` panel.

Source of truth for seeded procedure code:

- `procedures/newsroom/research_explorer.tac`
- `procedures/newsroom/reporter.tac`
- `procedures/newsroom/ingestion_reference_register.tac`

The seed process copies those files into `ProcedureVersion.tactusSource`:

- `amplify/seed/seed.ts` loads source files from `procedures/newsroom/`
- `npm run seed:amplify` upserts `ProcedureDefinition` + published v1
  `ProcedureVersion` rows

After editing local `.tac` files, reseed to refresh cloud procedure source:

```bash
AWS_PROFILE=<profile> AWS_REGION=<region> npm run seed:amplify -- --identifier <sandbox-id>
```

Procedure kinds and the registry:

- The first line of every procedure file declares its kind:
  `-- papyrus-procedure-kind: <kind>`.
- `corpora/papyrus-required-procedures.json` lists, under `procedures`, the file name that
  runs for each kind, and under `requiredCliProcedures` the kind each CLI command needs.
- `poetry run python -m papyrus_content.procedure_registry` checks that the three agree
  (a file without a kind, two files with one kind, a registry entry whose file declares
  another kind or does not exist, a file the registry does not list, a CLI command whose
  kind has no entry). CI runs it, and `papyrus procedures seed-required` runs it first.
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
  `Run npm run seed:amplify to preload standard procedures.`

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
