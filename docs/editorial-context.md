# Editorial context for agents

Use one resolved private policy context before research or writing. Policy remains editable publication data; static skills describe how to fetch it.

```sh
papyrus editorial context --backend cloud --publication PUBLICATION_KEY --story STORY_LINEAGE --format json
papyrus editorial context --backend cloud --publication PUBLICATION_KEY --assignment ASSIGNMENT_ID --format text
papyrus editorial context --backend local --publication PUBLICATION_KEY --section SECTION_ID --format json
```

`PUBLICATION_KEY` is the selected publication configuration's `canonicalTopicSet.corpusKey`. Run from that publication's configured root and existing authoring environment. The command checks the requested key against that configuration, then requires exactly one hosted canonical `KnowledgeCorpus` whose ID matches the requested key using the existing corpus ID convention. The hosted response uses that corpus's normalized key and current name, plus corpus ID, endpoint and configured tenant scope. A missing, different or ambiguous canonical corpus fails. Multi-canonical-corpus backends need an explicit publication ownership model before this resolver can support them; it fails instead of guessing. Existing IAM authoring authorization is unchanged. This command configures no credentials, transport or endpoint.

Hosted resolution reads private, current mission and policy Items by canonical slugs and uses current `NewsroomSection` policy, guidance and kill criteria. Optional Assignment and story selectors resolve their section and reject contradictory scopes. Assignment snapshots cannot replace live policy. Missing, empty or ambiguous required publication policy is an error. Missing requested records and API authorization errors propagate; there is no local seed fallback. Empty optional section mission/policy slots produce warnings. This does not perform semantic conflict detection: the precedence instruction requires agents to surface conflicts in narrower assignment instructions.

Tenant selection comes from the existing configured client/environment, never a request parameter. Every consumed doctrine, story and section must match that scope, including rejecting tenant-stamped records when no tenant is configured. Tenant doctrine uses the existing tenant-slug index. Assignments have no tenant field; a tenant assignment therefore requires its linked story or section to establish scope. Brief/instruction attachments must belong to the requested Assignment; missing storage, empty content, ambiguity and read failures stop resolution. These checks constrain this resolver and do not replace backend authorization.

Local mode reads the publication's existing `corpora/papyrus-steering.yml`, `corpora/papyrus-publication-doctrine.yml` and, when requested, `corpora/papyrus-newsroom-sections.yml`. It records Git HEAD when available, actual file/content hashes and an explicit warning that local configuration is not current hosted policy. It cannot resolve live story or Assignment records.

The `editorial-context/v1` response includes publication and scope, ordered entries, source IDs/revisions/timestamps/content hashes, precedence, warnings, render version, `contextHash`, `resolvedAt` and generated `text`. The hash covers the rendered content and provenance, excluding fetch time. `--max-characters` fails if required text exceeds its limit; it never trims policy. Record the hash and source revisions in the story's reporting Messages. Private doctrine shapes editorial decisions; it is not evidence to quote in reader copy.

## Workers and existing API

`prepare_editorial_worker_input` resolves live context before the research/reporting and story-cycle procedure dispatches. It overrides caller-supplied policy fields and supplies text, hash and full provenance JSON in the run input. Standard researcher, reporter and copywriter procedures require text/hash and prepend them to the agent message, including retries. A direct procedure caller must fetch the same resolved context and provide those inputs. This is a clean contract change: updating local procedure source does not update already-stored ProcedureVersion rows. Release/review owners must synchronize procedure versions through the normal approved workflow; this change performs no seeding or deployment.

The Tactus host exposes `editorial_context{ assignment_id = "..." }` (also optional `section_id`/`story_lineage_id`) and `papyrus.editorial.context`. Existing Assignment context uses this resolver; the evidence pack includes its rendered text as one required block and fails if compaction drops required blocks. Source resolution is deterministic; no model calls are made to assemble policy.

GraphQL source exposes `getEditorialContext(publicationKey: String!, sectionId: ID, storyLineageId: ID, assignmentId: ID, maxCharacters: Int): AWSJSON`. Its JSON response is the same complete rendered/provenance contract as the CLI. `getAssignmentContext` and related queue contexts also return it in required `editorialContext: AWSJSON`, alongside doctrine summaries derived from that pack. The API uses the existing private assignment handler and the same authoring groups as assignment context. No public/guest route, public file or cache is added. The handler takes the endpoint from its existing generated backend configuration and tenant from its existing environment. Source schema and handler changes require the normal separately approved release; no deployed API availability is claimed here.

Both runtimes test the same synthetic contract fixture, including non-ASCII character counts, source revisions, generated text and canonical SHA-256 hash. Hashing uses recursively sorted compact JSON with UTF-8 text; `resolvedAt` is excluded. Adapter tests cover pagination, publication/tenant mismatches and attachment failures. The TypeScript test needs no Python environment or model access.

## Copywriting

The static `.agents/skills/copywriting/SKILL.md` fetches this context and delegates copy editing to the editorial-checks cycle (`papyrus editorial check` / `suggest`, backed by Limatus and the site's `EditorialPolicy` rows). Editorial policies stay separate from this doctrine context, and no editing option is applied without a person choosing it. Save substantive article revisions as new Papyrus versions and keep citation promotion independent from classifier feedback.

## Verification

- `PYTHONPATH=src:. python -m behave features_backend/editorial-context.feature`
- `PYTHONPATH=src python -m pytest procedures/newsroom/tests/test_editorial_context.py`
- `node --import tsx scripts/test-editorial-context-api.ts`

These use synthetic scoped records/local files and no cloud writes or model calls. End-to-end live worker execution requires the separately available Tactus runtime, approved procedure synchronization and the selected publication's authoring environment. It has not been implied by unit tests.
