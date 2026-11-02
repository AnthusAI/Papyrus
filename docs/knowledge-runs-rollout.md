# Knowledge runs on every site: rollout

Goal: every Papyrus site runs a daily [knowledge run](knowledge-cloud-run.md) from its monitor feeds, configuration only: routed monitor records on the Knowledge Map (`monitorSources: ["routed"]`), a few cited story ideas a day from the top routed items (`monitorStories`), and trend ideas (all filed as Items at the `idea` stage).

Checked read-only against account 712236451410 (`AWS_PROFILE=papyrus-production`, us-east-1) on 2026-10-27, after the corpus key (`knowledgeRun.corpusKey`), the default vocabulary and `amplify_outputs.json` seeding, the empty-corpus success and the `infra/site.json` pin fallback landed. Nothing was created or changed in AWS. Every site's example config under `infra/amplify-app-shell/examples/` now carries its `knowledgeRun` block (`anth-us`, `distinctive` and `dataparade` have new example files mirroring their site repos' `infra/site.json`), and `npm run test:scheduled-job-synth` synthesizes all eight.

## Readiness

| Site (`siteId`) | CloudFormation stack | Schedule (UTC) | Corpus (References; routed = `monitor-*` import runs) | OpenAI key (SSM name; values never read) | Projection pin | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `shipped` | `papyrus-scheduled-job-knowledge-run-shipped` | `cron(0 5 * * ? *)` | `knowledge-corpus-shipped`: 2,597 (5 routed) | `/papyrus/shipped/openai-api-key` | requirements-publication.txt 5.42.1 | Ready (stack deployed; adds routed records and monitor stories) |
| `anth-us` | `papyrus-scheduled-job-knowledge-run-anth-us` | `cron(0 6 * * ? *)` | `knowledge-corpus-anth-us`: 26 (25 routed) | `/papyrus/shipped/openai-api-key (Ryan's decision: shared with Shipped)` | infra/site.json 1.0.0-next.41 = 1.0.0.dev41: no projection lease | Blocked: the projection pin (see Pins) |
| `threat-intelligence` | `papyrus-scheduled-job-knowledge-run-threat-intelligence` | `cron(0 7 * * ? *)` | `knowledge-corpus-threat-intelligence`: 1,939 (26 routed) | `/amplify/shared/d12wnrx15qbcc2/OPENAI_API_KEY` | infra/site.json 5.42.1 (fallback) | Ready |
| `distinctive` | `papyrus-scheduled-job-knowledge-run-distinctive` | `cron(0 8 * * ? *)` | `knowledge-corpus-distinctive`: 54 (33 `monitor-*`); not in the HN router | `/amplify/shared/d2xke8ygmrzqpp/OPENAI_API_KEY` | requirements-publication.txt 3.2.0: no projection lease | Blocked: the projection pin (see Pins) |
| `pilobol-us` | `papyrus-scheduled-job-knowledge-run-pilobol-us` | `cron(0 9 * * ? *)` | `knowledge-corpus-pilobol-us`: 0 | `/papyrus/shipped/openai-api-key (Ryan's decision: shared with Shipped)` | infra/site.json 5.42.1 (fallback) | Ready; no-op until the router delivers (the corpus has 0 References) |
| `p-apyr-us` | `papyrus-scheduled-job-knowledge-run-p-apyr-us` | `cron(0 10 * * ? *)` | `knowledge-corpus-ai-ml-research`: 6,052 (23 routed) | `/papyrus/p-apyr-us/openai-api-key` | infra/site.json 5.41.5 (fallback) | Ready (`corpusKey` `ai-ml-research`) |
| `machines-on-machines` | `papyrus-scheduled-job-knowledge-run-machines-on-machines` | `cron(0 12 * * ? *)` | `knowledge-corpus-ai-ml-research` (shared with `p-apyr-us`; copied 2026-11-01): about 6,864 | `/papyrus/shipped/openai-api-key (shared with Shipped)` | requirements-publication.txt 5.69.0 | Prepared, not deployed (`corpusKey` `ai-ml-research`; plugin `home-page`) |
| `dataparade` | `papyrus-scheduled-job-knowledge-run-dataparade` | `cron(0 11 * * ? *)` | `knowledge-corpus-data-parade`: 181 (none routed) | `/amplify/shared/d35q7zv4zad2we/OPENAI_API_KEY` | requirements-publication.txt 5.42.1 | Ready (`corpusKey` `data-parade`); no routed records yet |

Every block has `monitorSources: ["routed"]`, no `monitorWeeks` (all history counts), `monitorStories: {"limit": 3}` and `alarmEmailParameter: /papyrus/shipped/knowledge-run/alarm-email` (one mailbox for every alarm; each new SNS subscription still has to be confirmed once from it). Each stack is 41 resources (42 in a `cdk synth` template, which adds `CDKMetadata`), the same as Shipped's, except that every stack after Shipped's sets `knowledgeRun.reuseImageRepository: true`: the account has one `papyrus-scheduled-jobs/knowledge-run` ECR repository (Shipped's stack created it), so a second stack that tried to create it would fail change-set validation. Such a stack imports the repository by name and has 40 resources. `machines-on-machines` sets it; the other five sites' example configs need it too before they deploy. `conceptKinds` and `beatsConfig` are left to the default vocabulary the first run seeds; add them when a site writes its own `vocabulary.yml`.

## Pins

The projection stage installs `papyrus-newsroom` at the site's pin before it writes, and stops if that release lacks the projection lease. A site repo without `requirements-publication.txt` (Threat-Intelligence, Anth.us-web, Pilobol.us, p.apyr.us) is pinned to `papyrus-newsroom==<papyrusVersion>` of its `infra/site.json`. The lease is in 5.28.0 and later; it is not in 3.2.0 or 1.0.0.dev41 (checked by listing the wheels). So:

- `anth-us`: `infra/site.json` says `1.0.0-next.41`. Bump `papyrusVersion` in Anth.us-web (or add `requirements-publication.txt`) to a 5.x release before the first run, or the projection stage fails before it writes and, because the story steps run after it, no ideas are filed.
- `distinctive`: Distinctive-web's `requirements-publication.txt` pins 3.2.0. Bump it to 5.42.1 before the first run.
- Anth.us builds its pages with its own `web/build_via_papyrus.py`; the first manual run's projection output should be reviewed before the schedule is left on.

## Prerequisites that are not configuration

| Item | Applies to | State |
| --- | --- | --- |
| OpenAI key parameters | all | Exist: `/papyrus/shipped/openai-api-key`, `/papyrus/p-apyr-us/openai-api-key`, and the three `/amplify/shared/<appId>/OPENAI_API_KEY` (SecureString; names only were listed). The task role reads whichever the block names. |
| Alarm e-mail | all | `/papyrus/shipped/knowledge-run/alarm-email` exists (String). |
| Vocabulary, stop words, `amplify_outputs.json` | all | Seeded with defaults by the first run. A site-specific `vocabulary.yml` can be uploaded to `publications/<site>/config/` later; the public wiki publishes only the kinds that vocabulary declares, so a site copied from another one needs its own (`machines-on-machines` has an AI/ML-research vocabulary: organization, model, model_family, technique, task, benchmark, dataset, software, topic, person). |
| Knowledge Map page in the site repo | all but Shipped | Not needed for a run to succeed or for the snapshot at `_data/knowledge/index.json`; without the map and topic pages the site just does not show them. |
| HN router entry | `distinctive` | Absent from `MONITOR#hn` / `CONFIG#router`; a write to the monitoring table, so Ryan's. Until then only its existing 33 `monitor-*` records count. |
| Image | all | Build and push from develop at or after the merge of #749 and #747: `PAPYRUS_SPEC='papyrus-newsroom[markus] @ git+https://github.com/AnthusAI/Papyrus@<sha>' infra/knowledge-run/build_image.sh`. Deploy a backend with `listStoryDrafts` before the image. |

## Which CloudFront distribution p-apyr-us invalidates

`E2EM0JLBC2W9WW` (alias `read.p.apyr.us`), the reader distribution. Its origin is the CMS site bucket (`amplify-ds6yswxui41yi-main-bran-sitebucket397a1860-y3dzuduvsux5`), the bucket the projection writes, and its viewer-request function (`papyrus-edge-p-apyr-us-reader-site-viewer-request`) uses the redirects store in the block. The other distribution, `E17ZRAI87DN065` (`p.apyr.us`, `apyr.us`), serves the product site from `papyrus-web-marketing-712236451410-us-east-1` (default behavior) and the Amplify app (`/newsroom*`, `/_next/*`, `/api/*`); it never reads the site bucket, so invalidating it would do nothing. The snapshot URL is therefore `https://read.p.apyr.us/_data/knowledge/index.json`.

## Deploy commands

From `infra/scheduled-jobs` with the production profile. Assert the account first (`aws sts get-caller-identity --query Account --output text` must print 712236451410), read the change set, then deploy. Nothing here has been run. `TrendDraftsEndpoint` is the AppSync GraphQL URL (`https://<appsync host>/graphql`), not the API id the block holds.

```bash
export AWS_PROFILE=papyrus-production
cd infra/scheduled-jobs && npm ci
IMAGE_TAG=$(PAPYRUS_SPEC='papyrus-newsroom[markus] @ git+https://github.com/AnthusAI/Papyrus@<develop sha>' ../knowledge-run/build_image.sh)   # arm64; prints the tag
```

### shipped

```bash
SITE=../amplify-app-shell/examples/shipped.site.json
npx cdk diff   -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-shipped
npx cdk deploy -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-shipped \
  --parameters KnowledgeRun-shipped:TrendDraftsEnabled=true \
  --parameters KnowledgeRun-shipped:TrendDraftsEndpoint=https://imnmexcbrzcddk2g4vl6hsn7ie.appsync-api.us-east-1.amazonaws.com/graphql \
  --parameters KnowledgeRun-shipped:TrendDraftsSnapshotUrl=https://shipped.anth.us/_data/knowledge/index.json \
  --parameters KnowledgeRun-shipped:MonitorStoriesEnabled=true
```

### anth-us

```bash
SITE=../amplify-app-shell/examples/anth-us.site.json
npx cdk diff   -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-anth-us
npx cdk deploy -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-anth-us \
  --parameters KnowledgeRun-anth-us:TrendDraftsEnabled=true \
  --parameters KnowledgeRun-anth-us:TrendDraftsEndpoint=https://2m5fh2nqlnfxlfg2mxepp7tdbm.appsync-api.us-east-1.amazonaws.com/graphql \
  --parameters KnowledgeRun-anth-us:TrendDraftsSnapshotUrl=https://anth.us/_data/knowledge/index.json \
  --parameters KnowledgeRun-anth-us:MonitorStoriesEnabled=true
```

### threat-intelligence

```bash
SITE=../amplify-app-shell/examples/threat-intelligence.site.json
npx cdk diff   -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-threat-intelligence
npx cdk deploy -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-threat-intelligence \
  --parameters KnowledgeRun-threat-intelligence:TrendDraftsEnabled=true \
  --parameters KnowledgeRun-threat-intelligence:TrendDraftsEndpoint=https://2neu5y2cjrbnbkord2mdaetysi.appsync-api.us-east-1.amazonaws.com/graphql \
  --parameters KnowledgeRun-threat-intelligence:TrendDraftsSnapshotUrl=https://threat-intelligence.anth.us/_data/knowledge/index.json \
  --parameters KnowledgeRun-threat-intelligence:MonitorStoriesEnabled=true
```

### distinctive

```bash
SITE=../amplify-app-shell/examples/distinctive.site.json
npx cdk diff   -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-distinctive
npx cdk deploy -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-distinctive \
  --parameters KnowledgeRun-distinctive:TrendDraftsEnabled=true \
  --parameters KnowledgeRun-distinctive:TrendDraftsEndpoint=https://lzc75j6qdjboblirpdtsalilnq.appsync-api.us-east-1.amazonaws.com/graphql \
  --parameters KnowledgeRun-distinctive:TrendDraftsSnapshotUrl=https://distinctive-mark.com/_data/knowledge/index.json \
  --parameters KnowledgeRun-distinctive:MonitorStoriesEnabled=true
```

### pilobol-us

```bash
SITE=../amplify-app-shell/examples/pilobol-us.site.json
npx cdk diff   -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-pilobol-us
npx cdk deploy -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-pilobol-us \
  --parameters KnowledgeRun-pilobol-us:TrendDraftsEnabled=true \
  --parameters KnowledgeRun-pilobol-us:TrendDraftsEndpoint=https://sivqwif4onbdnoh3fm3nrl437q.appsync-api.us-east-1.amazonaws.com/graphql \
  --parameters KnowledgeRun-pilobol-us:TrendDraftsSnapshotUrl=https://pilobol.us/_data/knowledge/index.json \
  --parameters KnowledgeRun-pilobol-us:MonitorStoriesEnabled=true
```

### p-apyr-us

```bash
SITE=../amplify-app-shell/examples/p-apyr-us.site.json
npx cdk diff   -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-p-apyr-us
npx cdk deploy -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-p-apyr-us \
  --parameters KnowledgeRun-p-apyr-us:TrendDraftsEnabled=true \
  --parameters KnowledgeRun-p-apyr-us:TrendDraftsEndpoint=https://632qpvm7w5emhb2zo2vomc5rae.appsync-api.us-east-1.amazonaws.com/graphql \
  --parameters KnowledgeRun-p-apyr-us:TrendDraftsSnapshotUrl=https://read.p.apyr.us/_data/knowledge/index.json \
  --parameters KnowledgeRun-p-apyr-us:MonitorStoriesEnabled=true
```

### machines-on-machines

The site's reader distribution is `E1PTZ8B9ZF9GCU` (`machines-on-machines.anth.us`, origin the site bucket the projection writes); the `newsroom.` distribution is the console. `TrendDraftsEndpoint` is the AppSync GraphQL host from the site's `amplify_outputs.json`, which is not the API id the block holds.

```bash
SITE=../amplify-app-shell/examples/machines-on-machines.site.json
npx cdk diff   -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-machines-on-machines
npx cdk deploy -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-machines-on-machines \
  --parameters KnowledgeRun-machines-on-machines:TrendDraftsEnabled=true \
  --parameters KnowledgeRun-machines-on-machines:TrendDraftsEndpoint=https://vuagbw3fmvalta762m4zsacxce.appsync-api.us-east-1.amazonaws.com/graphql \
  --parameters KnowledgeRun-machines-on-machines:TrendDraftsSnapshotUrl=https://machines-on-machines.anth.us/_data/knowledge/index.json \
  --parameters KnowledgeRun-machines-on-machines:MonitorStoriesEnabled=true
```

### dataparade

```bash
SITE=../amplify-app-shell/examples/dataparade.site.json
npx cdk diff   -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-dataparade
npx cdk deploy -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-dataparade \
  --parameters KnowledgeRun-dataparade:TrendDraftsEnabled=true \
  --parameters KnowledgeRun-dataparade:TrendDraftsEndpoint=https://lncgpg57sndelgnygygdoilm7i.appsync-api.us-east-1.amazonaws.com/graphql \
  --parameters KnowledgeRun-dataparade:TrendDraftsSnapshotUrl=https://dataparade.anth.us/_data/knowledge/index.json \
  --parameters KnowledgeRun-dataparade:MonitorStoriesEnabled=true
```

For a site whose `infra/site.json` lives in its own repo, point `SITE` at that file instead once it carries the same `knowledgeRun` block. Shipped is a redeploy of the existing stack: the new `MonitorStoriesEnabled` parameter defaults to `false`, so the command above turns it on in the same change set.

## Starting a run by hand

```bash
STACK=papyrus-scheduled-job-knowledge-run-<site>
ARN=$(aws cloudformation describe-stacks --stack-name $STACK --query "Stacks[0].Outputs[?OutputKey=='StateMachineArn'].OutputValue" --output text)
aws stepfunctions start-execution --state-machine-arn $ARN \
  --name manual-$(date -u +%Y%m%dT%H%M%S) --input '{"publication":"<site>"}'
```

Use the `siteId` for `<site>` (`shipped`, `anth-us`, `threat-intelligence`, `distinctive`, `pilobol-us`, `p-apyr-us`, `machines-on-machines`, `dataparade`). Run one by hand after each deploy and read the ledger and the `monitor-stories` log before leaving the schedule on.

## Order

1. Image: build one from develop; check the backends have `listStoryDrafts`.
2. Shipped: deploy and watch the 05:00 run (routed records in `corpus-sync`, ideas in the `monitor-stories` log).
3. Ready sites, in schedule order: `threat-intelligence`, `p-apyr-us`, `machines-on-machines`, `dataparade`, `pilobol-us` (a no-op until the router delivers).
4. After their pins are bumped: `anth-us`, then `distinctive` (and its router entry).
