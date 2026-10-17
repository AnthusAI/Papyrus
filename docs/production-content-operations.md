# Production content operations

Targeted refreshes of production content through the IAM authoring CLI. Never repair production with a runtime Markdown source.

Production content lives in Amplify Data. The reader path uses API-key GraphQL
reads through `ContentRepository`; production writes and repairs should use the
IAM-signed authoring CLI or an explicit AWS-backed maintenance script. Do not repair production by adding a runtime Markdown content source.

Production authoring uses the deployed AppSync API, not the sandbox:

```bash
export AWS_PROFILE=default
export AWS_REGION=us-east-1
export PAPYRUS_GRAPHQL_ENDPOINT=https://ur2anu47d5f67eq7sjzoqpyuze.appsync-api.us-east-1.amazonaws.com/graphql
```

`AWS_PROFILE` must resolve to credentials that may assume the production site's
authoring role (`aws sso login --profile <profile>` for SSO profiles).

The full production authoring and category/graph steering guide lives in the
agent skill at [skills/category-steering/SKILL.md](../skills/category-steering/SKILL.md).

Then verify the authoring credentials before writing:

```bash
poetry run papyrus ops content inspect
poetry run papyrus ops content list articles
```

Treat `poetry run papyrus ops content inspect` as a hard preflight gate for live
CLI smoke runs. If it fails (for example `401 Unauthorized` or no credentials),
fix the AWS profile or role first and do not continue with live write/read smoke
commands.

For production content refreshes, use targeted GraphQL upserts. The safe pattern
is:

1. Dump or inspect `edition-current`, its `EditionItem` records, referenced
   `Item` records, media, and tags.
2. Generate a planned diff before mutations.
3. Confirm the diff targets only `edition-current` and the intended
   `Item`, `Tag`, `ItemTag`, `EditionItem`, and `MediaAsset` records.
4. Apply only targeted upserts/deletes. Do not run `npm run seed:amplify`, do
   not run sandbox provisioning, and do not run `content delete all --yes`.
5. Re-run `content list articles` and smoke-check the deployed site.

Sections are editor-configured newsroom objects, not inferred taxonomy labels.
When publishing an edition, set `Item.section`, `Tag.label`, and
`ItemTag.tagSlug` to the configured editorial sections chosen for that issue.

If the deployed production code is older than the local layout-plan schema, a
newer `Edition.layoutPlan` can make production return `500` during layout-plan
validation. Prefer deploying the current app before publishing advanced
layout-plan fields. If production must be restored without a deploy, make a
targeted compatibility repair to `edition-current.layoutPlan`, then re-smoke the
site and document exactly which fields were removed.

The production archive has one important invariant: a published edition must
have all of these fields set:

- `Edition.status = "published"`
- `Edition.editionDate`, for canonical date routes such as `/2026/may/13`
- `Edition.publishedAt`, for archive listing and freshness sort order

If the home page or a date route can load an edition but `/archive` says
`No published editions are available yet`, check `publishedAt` first. The
archive API lists editions through the `status + publishedAt` index, so records
created before that field was populated can be published and still absent from
the archive. Backfill the edition with a stable timestamp such as
`2026-05-13T12:00:00.000Z`, then verify the archive endpoint returns at least
one preview:

```bash
curl -sS "$PAPYRUS_BASE_URL/api/archive/editions?limit=1"
```

For local sandbox content, use `npm run seed:amplify` (users, sections,
doctrine, procedures) and `poetry run papyrus ops content seed-edition` (fixture
edition, articles and media). The seed-edition path uploads media to Storage and
sets `publishedAt` on the seeded edition. Treat it as a sandbox/dev workflow,
not as an implicit production publish command.
