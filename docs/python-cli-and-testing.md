# Python CLI, authoring recipes and tests

Poetry setup, the `papyrus` CLI recipes for content, corpora, references and assignments, local sandbox seeding and the BDD suites. Moved out of the README.

## Python Newsroom Package

Papyrus now packages its Python newsroom tooling as the Poetry-managed
`papyrus` module.

Use Poetry as the canonical Python entrypoint:

```bash
poetry install --extras newsroom
export BIBLICUS_WORKDIR=/path/to/biblicus-workdir
poetry run papyrus --help
poetry run papyrus assignments build-context --assignment <assignment-id>
poetry run papyrus procedures execute-tactus 'return api_list{}'
poetry run papyrus knowledge signals trend-report --corpus-key <key> --topic "<topic>" --sections culture,methods --json
poetry run papyrus editions plan --date YYYY-MM-DD --sections culture,methods --section-budgets culture:2,methods:1 --signal-report <signal-report.json> --json
poetry run papyrus assignments run-story-cycle --date YYYY-MM-DD --topic "<topic>" --category <category-key> --coverage-key <coverage.key> --sections culture,methods --section-budgets culture:2,methods:1 --through plan|research|reporting --json
poetry run papyrus assignments story-cycle-output --run-id <coverage-theme-run-id> --json
poetry run python procedures/newsroom/tests/test_newsroom_tools.py
```

Newsroom agents use the single-tool Tactus pattern from Plexus. Their Tactus
procedures load only `execute_tactus` from `procedures/newsroom/tactus_tools/`;
inside that tool, snippets use the packaged `papyrus` host module for GraphQL
reads, section context assembly, Biblicus evidence, docs/API discovery, and dry-run
record-plan builders. The older compatibility shims under
`procedures/newsroom/tools/` still exist for path-based tooling, but the
canonical implementation now lives in `src/papyrus_newsroom/`.

Story tools in `src/papyrus_newsroom/tactus_tools.py` (a procedure loads the
module as a plugin toolset; every public function is a tool) include
`papyrus_check_story_version`, which a copy-edit procedure uses to run the
editorial checks on one saved version. Name the version with `version` (an item
id) or with `story` (the lineage id) plus an optional `version_number` (0 means
the newest). It calls the site's `checkItemVersion` mutation, the same call as
`papyrus editorial check-version`, then reads the stored check back and returns
`status` (`checked`, `skipped` when editorial checks are off, or `pending` if
no stored result appears within `wait_seconds`), `clean` (true only when
checked with no violations and nothing for review), `versionId`, `lineageId`,
`versionNumber`, `packVersion`, `contentHash`, `checkedAt`, `violations`,
`reviews`, `lanes` and `findings`. Each finding has `id`, `rule` (the policy
id), `severity`, `status`, `message`, `quote`, `scope` and `probability`. `scope` is `quote` when the
finding quotes the text and `document` when `quote` is empty: that finding is about the
whole document (review rules such as general-meaning-first), so a bot judges it against
the full text instead of searching for a quote; a `paragraph` is returned only when the
stored finding names one. The stored
check does not keep character spans, the detecting lane per finding, or
suggested fixes. The loop is: check, fix with `papyrus_save_story_version`,
check the new version id, stop when `clean` is true. Specs:
`features_backend/tactus-check-story-version.feature`.

Coverage Theme orchestration is Python-first. `signals trend-report` is the
assignment-section signal feed, `editions plan` turns signals plus section slots
into private assignment graphs, `assignments run-story-cycle` advances that graph
through research or reporting packet creation, and `assignments story-cycle-output`
rediscovers the applied private state from GraphQL. The older
`poetry run papyrus assignments run-story-cycle` and
`assignments story-cycle-output` commands remain compatibility surfaces while
operators migrate.

Fresh external web research is a Tactus standard-library capability, not a
Papyrus adapter. Researcher and reporter snippets should use
`local web = require("tactus.web")` and then call `web.search{...}` or
`web.synthesize{...}` with `provider = "openai"` when the assignment context
requests current web evidence. Web results stay in private `research_packet` or
`reporting_context_packet` proposed-reference fields until reference intake
registers them; Papyrus does not write accepted evidence records directly from
web search.

Copy `.env.example` to `.env` when you need local overrides. `.env*` is ignored
by git, while `.env.example` is intentionally committed as the template.

`npm run test:bdd` runs the Gherkin layout scenarios against a running app. It
defaults to `http://127.0.0.1:3001`; set `PAPYRUS_BASE_URL` to test another
server.

`npm run test:bdd:backend` runs deterministic backend Behave features (Python)
and excludes live-agent scenarios.

`npm run test:bdd:agent-live` runs only the backend live-agent Gherkin smoke
suite via Behave (Python).
The live-agent suite is sandbox-only (a dedicated sandbox checkout, never a production workspace)
and defaults the chat-agent model policy to `gpt-5-nano`.
Live scenarios persist tagged test records by default for dogfooding
(`behave-live-agent-*` prefixes); set `PAPYRUS_LIVE_AGENT_CLEANUP=1` to delete
records after each run.
`npm run test:bdd:agent-local` runs the same live-agent Behave scenarios but
invokes the local Rust console responder binary directly (no Lambda deploy).
This uses a dedicated local responder lane (`responseTarget=local`) so cloud
Lambda processing does not interfere with local runs, while still writing
Message rows through the configured GraphQL endpoint.
Use focused local loops for faster iteration:
`npm run test:bdd:agent-local:hello`, `:docs`, `:create`, `:get`, `:update`,
and `:error-shape`.
Before local/live agent runs, validate the reference action GraphQL contract
with `npm run check:reference-action-contract`.

In development, no query string means the live GraphQL edition. Use
`/?scenario=current-edition` or another named scenario id only when you need a
reproducible fixture layer for testing.

For Amplify development, run `npm run sandbox` to provision a local cloud
sandbox. After the sandbox has generated `amplify_outputs.json`, run
`npm run seed:amplify` to seed users, sections, doctrine and procedures, then
`poetry run papyrus ops content seed-edition` to seed the fixture edition, articles
(as Markus `bodyMarkus`/`bodyIr`) and media.

Seed content supports optional profiles so one Papyrus-based site can keep
custom fixture content without overwriting the base default fixture:

- Set `PAPYRUS_SEED_PROFILE=<profile-id>` before `poetry run papyrus ops content seed-edition`
- Optional profile file path:
  `amplify/seed/profiles/<profile-id>/seed-edition-content.json`
- Fallback path (always available):
  `amplify/seed/seed-edition-content.json`

For content inspection and admin against a deployed API:

```bash
poetry run papyrus ops content inspect
poetry run papyrus ops content list articles
poetry run papyrus ops corpora worker-bootstrap --config corpora/papyrus-steering.yml --json
poetry run papyrus ops corpora status --config corpora/papyrus-steering.yml --corpus-key <key> --json
poetry run papyrus ops corpora sync-from-cloud --config corpora/papyrus-steering.yml --corpus-key <key> --dry-run
poetry run papyrus ops corpora sync-to-cloud --config corpora/papyrus-steering.yml --corpus-key <key> --dry-run
poetry run papyrus ops categories import-config --config corpora/papyrus-steering.yml
poetry run papyrus sections import --config corpora/papyrus-newsroom-sections.yml
poetry run papyrus ops categories import-steering --config corpora/papyrus-steering.yml --corpus-key <key>
poetry run papyrus assignments research-packets --assignment <assignment-id>
poetry run papyrus knowledge signals trend-report --corpus-key <key> --topic "<topic>" --sections culture,methods --json
poetry run papyrus assignments run-story-cycle --date YYYY-MM-DD --topic "<topic>" --category <category-key> --coverage-key <coverage.key> --sections culture,methods --section-budgets culture:2,methods:1 --through reporting --json
poetry run papyrus assignments story-cycle-output --run-id <coverage-theme-run-id> --json
poetry run papyrus assignments run-story-cycle --date YYYY-MM-DD --topic "<topic>" --category <category-key> --coverage-key <coverage.key> --sections culture,methods,business,law --section-budgets culture:2,methods:1,business:1,law:1 --through plan|research|reporting [--refresh-packets] --json
poetry run papyrus assignments story-cycle-output --run-id <story-cycle-run-id> --json
poetry run papyrus assignments review-reporting-packet --assignment <assignment-id> --message <message-id> --decision select|merge|brief|hold|kill --note "<editor rationale>" --dry-run
poetry run papyrus assignments run-copywriting --assignment <copywriting-assignment-id> --dry-run --json
poetry run papyrus assignments copywriting-output --run-id <story-cycle-run-id> --json
poetry run papyrus references curate-recent --corpus-key <key> --since-hours 48 --max-count 25 --dry-run --json
poetry run papyrus references curate-recent --corpus-key <key> --since-hours 48 --max-count 25 --json
poetry run papyrus references register-catalog --config corpora/papyrus-steering.yml --corpus-key <key> --catalog <metadata/catalog.json> --status pending --ingestion-rationale "<summary, research focus, editorial mission fit>"
poetry run papyrus references export-analysis-manifest --config corpora/papyrus-steering.yml --corpus-key <key> --output accepted-reference-manifest.json
poetry run papyrus references export-scope-training --config corpora/papyrus-steering.yml --corpus-key <key> --output reference-scope-training.json
poetry run papyrus knowledge topics export-category-set --category-set <id> --output accepted-category-set.json
poetry run papyrus ops categories import-projection --config corpora/papyrus-steering.yml --target-corpus-key <key> --authority-corpus-key <key> --bundle projection-results.json
poetry run papyrus ops content delete all --yes
```

`references curate-recent` is assignment-only for re-curation operations:
Default apply mode dispatches `curation.reference-refresh` assignments and returns queue
status; it does not execute inline curation stages.

`references register-catalog` is the canonical bridge from corpus accession
files into Papyrus workflow state. In default apply mode, it creates a
`KnowledgeImportRun`, sanitized `KnowledgeRawPayload`, `Reference` and
`ReferenceAttachment` records, workflow
`SemanticRelation` links, and one open `curation.reference-intake` `Assignment`
per pending reference. The filesystem catalog is not the queue after
registration; pending references and assignments are.

For routine reference curation, use the operator runbook:

1. `poetry run papyrus ops content inspect`
2. `poetry run papyrus references curate-recent --corpus-key <key> --since-hours 48 --max-count 25 --dry-run --json`
3. rerun without `--dry-run` once dry-run output looks correct.

Common curation command recipes:

```bash
# List candidate references (newest first)
poetry run papyrus references list --corpus-key <key> --status accepted --limit 25

# Curate one specific reference (dry-run)
poetry run papyrus references curate-recent --corpus-key <key> --reference <reference-lineage-id> --dry-run --json

# Curate a recent batch (dry-run)
poetry run papyrus references curate-recent --corpus-key <key> --since-hours 48 --max-count 25 --dry-run --json

# Curate all references in a corpus (dry-run; add to dispatch)
poetry run papyrus references curate-recent --corpus-key <key> --all --max-count 250 --dry-run --json
```

`references curate-recent` runs identifier prepass first, then title/subtitle,
summary, and quality in order. It writes resumable manifests under
`.papyrus-runs/reference-curation-<run-id>/manifest.json` and returns nonzero
when any reference fails so automation can detect degraded runs.
Reference subtitle display is canonical: the Newsroom UI shows `metadata.subtitle`
from the reference metadata attachment verbatim when present.

Knowledge search quick recipes:

```bash
# General semantic knowledge search
poetry run papyrus knowledge query --query "text classifier benchmarking" --max-tokens 600 --format both

# Section-anchored semantic knowledge search (section anchor)
poetry run papyrus knowledge query --query "AI in games" --anchor newsroomSection:technology --max-tokens 600 --format structured

# Build the exact section-aware assignment agent context used by research/reporting
poetry run papyrus assignments build-assignment-agent-context --assignment-id <assignment-id> --max-tokens 4000 --recent-days 30
```

Set `PAPYRUS_GRAPHQL_ENDPOINT` and `AWS_PROFILE` before running authoring
commands. Requests are signed with SigV4 (IAM) from the standard AWS credential
chain: an SSO profile that assumes the site's `<siteId>-papyrus-authoring` role,
an OIDC role, or an Amplify build role. No Papyrus editor login, stored token,
or local auth-session cache is involved. See
[Running the CLI locally](site-hosting.md#running-the-cli-locally).

The CLI still contains legacy `diff` and `sync` commands for source-driven
publishing, but those commands require a local source adapter. The runtime no
longer has a committed `content/articles` Markdown store, so do not cite
`content sync edition current` as the production publishing path unless a
current source payload exists and has been validated.

`content delete all --yes` removes CMS records through the same IAM authoring
credentials. Use it only for an explicitly requested
reset. Do not use it for production content refreshes.

For local cloud work, use an AWS profile, for example:

```bash
AWS_PROFILE=default AWS_REGION=us-east-1 npm run sandbox
AWS_PROFILE=default AWS_REGION=us-east-1 npm run seed:amplify
AWS_PROFILE=default npm run dev:127
```
