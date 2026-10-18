# Editorial context for agents

Use one resolved private policy context before research or writing. Policy remains editable publication data; static skills describe how to fetch it.

```sh
papyrus editorial context --backend cloud --publication PUBLICATION_KEY --story STORY_LINEAGE --format json
papyrus editorial context --backend cloud --publication PUBLICATION_KEY --assignment ASSIGNMENT_ID --format text
papyrus editorial context --backend local --publication PUBLICATION_KEY --section SECTION_ID --format json
```

`PUBLICATION_KEY` is the selected publication configuration's `canonicalTopicSet.corpusKey`. Run from that publication's configured root and existing authoring environment. The command checks the requested key against that configuration; hosted authorization remains enforced by the existing IAM authoring client. No credentials, transport or endpoint are configured by this command. The response records the selected endpoint as part of publication provenance; this identifies the binding rather than claiming an independent server-side publication attestation.

Hosted resolution reads private, current mission and policy Items by canonical slugs and uses current `NewsroomSection` policy, guidance and kill criteria. Optional Assignment and story selectors resolve their section and reject contradictory scopes. Assignment snapshots cannot replace live policy. Missing, empty or ambiguous required publication policy is an error. Missing requested records and API authorization errors propagate; there is no local seed fallback. Empty optional section mission/policy slots produce warnings. This does not perform semantic conflict detection: the precedence instruction requires agents to surface conflicts in narrower assignment instructions.

Local mode reads the publication's existing `corpora/papyrus-steering.yml`, `corpora/papyrus-publication-doctrine.yml` and, when requested, `corpora/papyrus-newsroom-sections.yml`. It records Git HEAD when available, actual file/content hashes and an explicit warning that local configuration is not current hosted policy. It cannot resolve live story or Assignment records.

The `editorial-context/v1` response includes publication and scope, ordered entries, source IDs/revisions/timestamps/content hashes, precedence, warnings, render version, `contextHash`, `resolvedAt` and generated `text`. The hash covers the rendered content and provenance, excluding fetch time. `--max-characters` fails if required text exceeds its limit; it never trims policy. Record the hash and source revisions in the story's reporting Messages. Private doctrine shapes editorial decisions; it is not evidence to quote in reader copy.

## Workers and existing API

`prepare_editorial_worker_input` resolves live context before the research/reporting and story-cycle procedure dispatches. It overrides caller-supplied policy fields and supplies text, hash and full provenance JSON in the run input. Standard researcher, reporter and copywriter procedures require text/hash and prepend them to the agent message, including retries. A direct procedure caller must fetch the same resolved context and provide those inputs. This is a clean contract change: updating local procedure source does not update already-stored ProcedureVersion rows. Release/review owners must synchronize procedure versions through the normal approved workflow; this change performs no seeding or deployment.

The Tactus host exposes `editorial_context{ assignment_id = "..." }` (also optional `section_id`/`story_lineage_id`) and `papyrus.editorial.context`. Existing Assignment context uses this resolver; the evidence pack includes its rendered text as one required block and fails if compaction drops required blocks. Source resolution is deterministic; no model calls are made to assemble policy.

Existing GraphQL `getAssignmentContext` and related queue contexts retain their existing response schema but now read current private publication doctrine and `NewsroomSection` slots, rather than category-based desk Items. Its TypeScript adapter is tested for the same selection/error semantics. That API returns doctrine records, not the full rendered/provenance contract; use the Python CLI or Tactus host for generated text. A generated-text GraphQL query is a remaining API extension, not part of this initial slice.

## Copywriting

The static `.agents/skills/copywriting/SKILL.md` fetches this context and delegates copy editing to `limatus skill`, using the publication's existing style profile. No policy-to-style-profile converter or automatic selection of editing options is introduced. Limatus's explicit human option/id/anchor selection requirement remains. Save substantive article revisions as new Papyrus versions and keep citation promotion independent from classifier feedback.

## Verification

- `PYTHONPATH=src:. python -m behave features_backend/editorial-context.feature`
- `PYTHONPATH=src python -m pytest procedures/newsroom/tests/test_editorial_context.py`
- `node --import tsx scripts/test-editorial-context-api.ts`

These use synthetic scoped records/local files and no cloud writes or model calls. End-to-end live worker execution requires the separately available Tactus runtime, approved procedure synchronization and the selected publication's authoring environment. It has not been implied by unit tests.
