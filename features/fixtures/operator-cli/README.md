# Operator CLI fixtures

Executable specs in `features/operator-cli.feature` use these fixtures. They are
not production data and do not revive a local Markdown content store.

## Cloud backend fixture

Simulates AppSync GraphQL responses for:

- `cloud-references.json` — two `Reference` rows (`ref-cloud-001`, `ref-cloud-002`)
- `cloud-assignments.json` — one `Assignment` row (`asg-cloud-001`)

Default corpus key: `threat-intelligence` (from `corpora/papyrus-steering.yml`).

## Local pod backend fixture

Simulates a Kanbus newsroom pod project (example layout: `pods/anthus-blog`):

- `.kanbus.yml` with story workflow stages
- Story `ANTH-33c4de` with pod reference artifacts (`ref-pod-001`, `ref-pod-002`)

The local backend reads the pod Kanbus project and story-owned artifacts. It does
not read `content/articles/` or any resurrected Papyrus-local corpus directory.

## Config fixture

`operator-cli.config.yaml` example:

```yaml
backend: cloud          # or local
defaultCorpusKey: threat-intelligence
publicationKey: threat-intelligence
local:
  podPath: pods/anthus-blog
cloud:
  graphqlEndpoint: https://example.appsync-api.example.com/graphql
```

Resolution order: `--backend` flag, then `PAPYRUS_BACKEND`, then config file,
then `cloud` when GraphQL env is present, else `local` when a pod path is
configured.

## Object kinds

Operator output uses explicit `kind` values so cloud and local rows are not
confused:

| kind | backend | meaning |
| --- | --- | --- |
| `cloud-reference` | cloud | GraphQL `Reference` record |
| `pod-reference` | local | Pod evidence/source row from story artifacts |
| `newsroom-assignment` | cloud | GraphQL `Assignment` work record |
| `pod-story` | local | Kanbus story row in the pod project |

Kanbus board operations (`kbs list`, transitions, columns) stay in `kbs`, not
`papyrus`.
