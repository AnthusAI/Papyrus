# Knowledge runs on every site: rollout

Goal: every Papyrus site runs a daily [knowledge run](knowledge-cloud-run.md) from its monitor feeds, configuration only: routed monitor records on the Knowledge Map (`monitorSources: ["routed"]`), a few cited story drafts a day from the top routed items (`monitorStories`), and trend drafts.

Checked read-only against account 712236451410 (`AWS_PROFILE=papyrus-production`, us-east-1) on 2026-10-27. Nothing was created or changed in AWS. Only Shipped is ready today; the rest are blocked by prerequisites that are not configuration (see below), so only Shipped's example config carries a `knowledgeRun` change.

## Sites and prerequisites

Every site below is a live Papyrus site in 712236451410 (Amplify CMS app, AppSync API, content-actions Lambda, S3 projection).

| Site (`siteId`) | CMS Amplify app | AppSync API id | Corpus (refs; routed = `monitor-*` import runs) | In HN router | OpenAI key (SSM name) | Alarm e-mail parameter | Site repo has Knowledge Map | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `shipped` | `dkycd9pntgo6d` | `6sw6454pozbgvdgm233gqkxsxu` | `knowledge-corpus-shipped`: 2,597 (2,592 Hub, 5 routed) | yes | `/papyrus/shipped/openai-api-key` | `/papyrus/shipped/knowledge-run/alarm-email` | yes (map page, `scoring.json`, state seeded) | **Ready** (stack deployed; adds routed + monitor stories) |
| `anth-us` | `d7s858igkyct5` | `4qiunzl7drcedaz22rl4xu56ga` | `knowledge-corpus-anth-us`: 26 (25 routed) | yes | missing | missing | no | Missing: key, alarm e-mail, vocabulary, map |
| `threat-intelligence` | `d12wnrx15qbcc2` | `gillpcb565fqrdrvqrijhqaily` | `knowledge-corpus-threat-intelligence`: 1,939 current (26 routed) | yes | only `/amplify/shared/d12wnrx15qbcc2/OPENAI_API_KEY` | missing | no | Missing: key (path), alarm e-mail, vocabulary, map |
| `distinctive` | `d2xke8ygmrzqpp` | `xcobakwl4jagvhdq54qc55flii` | `knowledge-corpus-distinctive`: 54 (33 `monitor-*`, from other monitors) | **no** | only `/amplify/shared/d2xke8ygmrzqpp/OPENAI_API_KEY` | missing | no | Missing: HN router entry, key (path), alarm e-mail, vocabulary, map |
| `pilobol-us` | `d1eiwl0gedkmnj` | `2tvll2u5ejafbmawb3v2sdonvi` | `knowledge-corpus-pilobol-us`: 0 refs | yes | missing | missing | no | Missing: key, alarm e-mail, no references yet, vocabulary, map |
| `dataparade` | `d35q7zv4zad2we` | `rgfkmmyyyrc7fb55qd5smbfrpm` | `knowledge-corpus-data-parade`: 181, none routed yet | yes (as `data-parade`) | only `/amplify/shared/d35q7zv4zad2we/OPENAI_API_KEY` | missing | no | Blocked: `siteId` `dataparade` is not the corpus key `data-parade` |
| `p-apyr-us` | `ds6yswxui41yi` | `36xh4ckhhvfyrlxxbltoy246ea` | no `knowledge-corpus-p-apyr-us`; the router delivers to `knowledge-corpus-ai-ml-research` (6,052 current, 23 routed) | yes | `/papyrus/p-apyr-us/openai-api-key` | missing | no | Blocked: the corpus key is `ai-ml-research`, not the `siteId` |
| `pretext-example` | none | none | none | no | none | none | no | Example config only, not a live site |

Notes on how the table was filled:

- **AppSync endpoint** is `https://<api id>.appsync-api.us-east-1.amazonaws.com/graphql` (the `TrendDraftsEndpoint` value); the id column is what `appSyncApiId` takes. The API ids were matched to sites by the HN router entries and the Amplify apps.
- **Router**: `MONITOR#hn` / `CONFIG#router` lists publications `anth-us`, `p-apyr-us`, `threat-intelligence`, `data-parade`, `pilobol-us`, `shipped`. Distinctive is absent. Only `p-apyr-us`, `data-parade` and `shipped` carry an explicit `corpusId`.
- **Corpus** counts are current References from `listReferencesByCorpusAndExternalItem`. "Routed" counts References whose `importRunId` starts with `monitor-`; all are `pending`. Shipped's other 2,592 are Hugging Face records.
- **Live site bucket / distribution / redirects store** were taken from the CloudFront distribution that serves each site and the content-actions Lambda's `PAPYRUS_SITE_BUCKET`, not from the stale `sitebucket` leftovers (DataParade and Shipped each have several).
- The deployed Shipped stack has `TrendDraftsEnabled=true`; it has no `MonitorStoriesEnabled` parameter yet.

## What each missing prerequisite needs

| Prerequisite | Applies to | What it needs | Needs Ryan? |
| --- | --- | --- | --- |
| Corpus key must equal `siteId` | `dataparade`, `p-apyr-us` | The knowledge run uses the `siteId` as the corpus key (`--corpus-key`), the S3 state prefix and the SSM names. DataParade's corpus is `data-parade` and Papyrus's is `ai-ml-research`. Fix with a code change (an optional `corpusKey` in `knowledgeRun`, passed as `KNOWLEDGE_CORPUS_KEY`, with state/SSM names still keyed by `siteId`), or by renaming the site/corpus. Not done here: it touches the cloud-run Python, not configuration. | Decision: yes (rename vs. new setting) |
| OpenAI key at `/papyrus/<site>/openai-api-key` | `anth-us`, `pilobol-us` (nothing); `threat-intelligence`, `distinctive`, `dataparade` (Amplify shared secret exists) | Create the SecureString by IaC (never by hand) for the first two. For the other three the Amplify shared secret `/amplify/shared/<appId>/OPENAI_API_KEY` exists: either point `knowledgeRun.openAiKeyParameter` at it (the task role then reads an Amplify-owned secret) or provision a `/papyrus/<site>/openai-api-key`. Only the names were checked, never the values. | Yes: which of the two, and the key itself |
| Alarm e-mail parameter | all but Shipped | `/papyrus/<site>/knowledge-run/alarm-email` is read at deploy time and must exist. The address is never committed. The draft blocks below point `alarmEmailParameter` at Shipped's parameter so one mailbox gets every alarm and nothing new is created. Each new SNS subscription still has to be confirmed once from the mailbox. | Yes: confirm the shared mailbox |
| Vocabulary and config seed | all but Shipped | Per-publication state lives in each stack's own bucket under `publications/<site>/config/`: `vocabulary.yml` (the closed entity vocabulary, kinds matching `conceptKinds`), `stop-words.txt`, `amplify_outputs.json` (endpoint only). Shipped's are 773, 116 and 395,351 bytes. A site needs its own `vocabulary.yml` written for its subject; the other files can be generated. | Yes: the subject vocabularies |
| Knowledge Map in the site repo | all but Shipped | `corpus-sync`/`projection` render from the repo's `web/` (templates, hooks, optional `beatsConfig`). Only Shipped-web has the map and topic pages, `map-view.json` and `scoring.json`. Without them a run counts routed records but shows nothing on the site. | Yes: whether each site wants a map |
| HN router entry | `distinctive` | Add the publication to `CONFIG#router` (`publicationId`, `appsyncEndpoint`, `site`; a `corpusId` only when the corpus is not `knowledge-corpus-<publicationId>`). This is a write to the monitoring table. | Yes |
| References to count | `pilobol-us` | The corpus is empty; the router must deliver first. A run on an empty corpus has nothing to do. | No (wait for the router) |
| Image with routed records and monitor stories | all | Build and push an image from develop at or after `883f8be5` (PR #743): `PAPYRUS_SPEC='papyrus-newsroom[markus] @ git+https://github.com/AnthusAI/Papyrus@<sha>' infra/knowledge-run/build_image.sh`. The latest image in ECR was pushed 2026-10-26 12:42; whether it contains #742/#743 was not checked. Deploy a backend with `listStoryDrafts` before the image. | No |

Everything the stack needs per site that is plain configuration was confirmed from AWS and is in the draft blocks below: `siteBucket`, `edgeDistributionId`, `redirectsKvsArn`, `appSyncApiId`, `amplifyAppId`, `contentActionsFunction`, `plugins` (from `PAPYRUS_PLUGINS` on each Lambda), `siteRepo`, `siteBranch` (`main`, which has a successful Amplify deploy on every app), `staticSubdir` (`web`). The state bucket, ledger table and alarm topic are created by the stack. `conceptKinds` for the draft blocks are deliberately left out: they must match each site's vocabulary, which only the site's editors can write.

## Config in this change

Only Shipped's example changed (`infra/amplify-app-shell/examples/shipped.site.json`): `monitorSources` is now `["huggingface", "routed"]` and `monitorStories` is `{"limit": 3}`. The schedule was already the daily `cron(0 5 * * ? *)`; `monitorWeeks` is no longer set (all history counts, since 2026-10-27) and trend drafts are on via the stack parameters. `scripts/test-scheduled-job-synth.ts` was adjusted so its base stack removes `monitorStories` (the optional step is still asserted separately) and expects `huggingface,routed`.

### Draft blocks for the other sites (add when the prerequisites are met)

The redirects store ARN is shortened here (a full id is a bare UUID, which the repository scanner rejects): it is the CloudFront KeyValueStore named `amplify<appId>main...RedirectsKeyValueStore...` (`aws cloudfront list-key-value-stores`). Merge into the site's `knowledgeRun`, with `siteRepo` defaulting to the site's `repository`. Times are staggered one hour apart (UTC) so Fargate runs do not overlap: Shipped 05:00, `anth-us` 06:00, `threat-intelligence` 07:00, `distinctive` 08:00, `pilobol-us` 09:00. Add `conceptKinds` for the site's subject, `beatsConfig` if it has one, and replace `alarmEmailParameter`/`openAiKeyParameter` per the table above. These five were synthesized (`cdk synth`, 42 resources each, the same as Shipped's stack).

```json
"anth-us": {
  "schedule": "cron(0 6 * * ? *)", "siteBucket": "amplify-d7s858igkyct5-main-bran-sitebucket397a1860-9qdsd4orbwi7",
  "edgeDistributionId": "E3UMOOJRMY7FK7", "redirectsKvsArn": "arn:aws:cloudfront::712236451410:key-value-store/363702bd-<rest of the id>",
  "appSyncApiId": "4qiunzl7drcedaz22rl4xu56ga", "amplifyAppId": "d7s858igkyct5",
  "contentActionsFunction": "amplify-d7s858igkyct5-mai-papyruscontentactionsE8B-RwNHN0KC1Zoi"
},
"threat-intelligence": {
  "schedule": "cron(0 7 * * ? *)", "siteBucket": "amplify-d12wnrx15qbcc2-main-bra-sitebucket397a1860-xjgv47daarzs",
  "edgeDistributionId": "E20NJAIXZ1WKWD", "redirectsKvsArn": "arn:aws:cloudfront::712236451410:key-value-store/cbee416b-<rest of the id>",
  "appSyncApiId": "gillpcb565fqrdrvqrijhqaily", "amplifyAppId": "d12wnrx15qbcc2",
  "contentActionsFunction": "amplify-d12wnrx15qbcc2-ma-papyruscontentactionsE8B-0UOYOpOwOChS",
  "openAiKeyParameter": "/amplify/shared/d12wnrx15qbcc2/OPENAI_API_KEY"
},
"distinctive": {
  "schedule": "cron(0 8 * * ? *)", "siteBucket": "amplify-d2xke8ygmrzqpp-main-bra-sitebucket397a1860-dbdg2ccpq0bc",
  "edgeDistributionId": "EHJUVNTK7AFXH", "redirectsKvsArn": "arn:aws:cloudfront::712236451410:key-value-store/81c593f0-<rest of the id>",
  "appSyncApiId": "xcobakwl4jagvhdq54qc55flii", "amplifyAppId": "d2xke8ygmrzqpp", "plugins": ["newsletter"],
  "contentActionsFunction": "amplify-d2xke8ygmrzqpp-ma-papyruscontentactionsE8B-8zprEcWtpmPK",
  "openAiKeyParameter": "/amplify/shared/d2xke8ygmrzqpp/OPENAI_API_KEY"
},
"pilobol-us": {
  "schedule": "cron(0 9 * * ? *)", "siteBucket": "amplify-d1eiwl0gedkmnj-main-bra-sitebucket397a1860-j6tjklhirzk3",
  "edgeDistributionId": "E2GKJ877IAH2I8", "redirectsKvsArn": "arn:aws:cloudfront::712236451410:key-value-store/63811e87-<rest of the id>",
  "appSyncApiId": "2tvll2u5ejafbmawb3v2sdonvi", "amplifyAppId": "d1eiwl0gedkmnj",
  "contentActionsFunction": "amplify-d1eiwl0gedkmnj-ma-papyruscontentactionsE8B-npf9ha5PkkSG"
}
```

Each also takes `"monitorSources": ["routed"], "monitorStories": {"limit": 3}`, `"alarmEmailParameter": "/papyrus/shipped/knowledge-run/alarm-email"` (shared mailbox, if Ryan agrees), and the site's own `siteRepo`/`conceptKinds`. For `dataparade` (bucket `amplify-d35q7zv4zad2we-main-bra-sitebucket397a1860-a2pz5pepxir0`, distribution `EIAVDLXO64F62`, redirects store `7a9a0125-...`, API `rgfkmmyyyrc7fb55qd5smbfrpm`, app `d35q7zv4zad2we`, Lambda `amplify-d35q7zv4zad2we-ma-papyruscontentactionsE8B-98vQtfpumJd8`) and `p-apyr-us` (bucket `amplify-ds6yswxui41yi-main-bran-sitebucket397a1860-y3dzuduvsux5`, reader distribution `E2EM0JLBC2W9WW`, redirects store `27bad446-...`, API `36xh4ckhhvfyrlxxbltoy246ea`, app `ds6yswxui41yi`, Lambda `amplify-ds6yswxui41yi-mai-papyruscontentactionsE8B-l8LUa08YMLSs`) the corpus-key blocker comes first. The p.apyr.us public origin is the marketing distribution, so confirm which distribution the projection should invalidate before using `E2EM0JLBC2W9WW`.

## Deploy commands

All from `infra/scheduled-jobs` with the production profile; assert the account first (`aws sts get-caller-identity --query Account --output text` must print 712236451410) and read the change set before deploying. Nothing here has been run.

```bash
export AWS_PROFILE=papyrus-production
cd infra/scheduled-jobs && npm ci
IMAGE_TAG=$(PAPYRUS_SPEC='papyrus-newsroom[markus] @ git+https://github.com/AnthusAI/Papyrus@<develop sha>' ../knowledge-run/build_image.sh)   # arm64; prints the tag
```

Shipped (existing stack; the new `MonitorStoriesEnabled` parameter defaults to `false`, then turn it on as a second change set; trend drafts stay on because CDK keeps the previous parameter values):

```bash
SITE=../amplify-app-shell/examples/shipped.site.json
npx cdk diff   -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-shipped
npx cdk deploy -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-shipped
npx cdk deploy -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-shipped --parameters KnowledgeRun-shipped:MonitorStoriesEnabled=true
```

Every other site, once its prerequisites are met and its block is in `infra/site.json` or an example file (`<site>` is the `siteId`; the endpoint and snapshot URL are the site's own):

```bash
SITE=<path to the site's site.json>
npx cdk diff   -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-<site>
npx cdk deploy -c site=$SITE -c imageTag=$IMAGE_TAG KnowledgeRun-<site> \
  --parameters KnowledgeRun-<site>:TrendDraftsEnabled=true \
  --parameters KnowledgeRun-<site>:TrendDraftsEndpoint=https://<appSyncApiId>.appsync-api.us-east-1.amazonaws.com/graphql \
  --parameters KnowledgeRun-<site>:TrendDraftsSnapshotUrl=https://<site origin>/_data/knowledge/index.json \
  --parameters KnowledgeRun-<site>:MonitorStoriesEnabled=true
```

Then seed `publications/<site>/config/` in the new stack's state bucket (`vocabulary.yml`, `stop-words.txt`, `amplify_outputs.json`) and start one `manual-...` execution (see [Operating it](knowledge-cloud-run.md#operating-it)) before the first scheduled run. The `ProjectionLock` stack is shared and already deployed.

## Order

1. Image: build one from develop at or after #743; check the backends have `listStoryDrafts`.
2. Shipped: deploy the stack, then enable `MonitorStoriesEnabled`; watch the 05:00 run (routed records in `corpus-sync`, drafts in the `monitor-stories` log).
3. Decide the two blockers (the corpus key for `dataparade` and `p-apyr-us`) and the shared items (alarm mailbox, OpenAI key paths).
4. `anth-us` first of the rest (smallest, routed already flowing), then `threat-intelligence`, `distinctive` (after its router entry), `pilobol-us` (after its first deliveries), then `dataparade` and `p-apyr-us`. For each site: vocabulary and map in the site repo, seed state, deploy, manual run, then leave the schedule on.
