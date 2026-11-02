# Operating Papyrus without an AWS login

An operator signs in with `papyrus login`. The site API holds narrow server-side permissions, checks staff groups and does the work. An AWS login on a person's machine is the exception, because it grants far more than any one task needs.

This page is the inventory behind epic PPY-2069d6. Each operation has one home:

- **Existing CLI:** already works on the signed-in lane.
- **New CLI and server API:** needs a command and a narrow server endpoint.
- **Pipeline:** deploys and infrastructure, run by CI/CD and not by a person.
- **Break-glass:** stays on AWS, for the reason given.

## Monitoring and routing

| Operation | Today | Home |
|---|---|---|
| Read runs, queue, routing state and decision counts | `papyrus monitors overview` and `page` | Existing CLI |
| Waiting jobs, job ages, router failures | DynamoDB and CloudWatch | New CLI and server API (PPY-1cb311) |
| Pause, resume or sweep a router; seed router and web monitor config | `infra/monitoring/seed_*.py`, `aws lambda invoke` | New CLI and server API (PPY-2df137) |
| Draft and store web-search queries | `papyrus monitors web-queries` (reads SSM and DynamoDB) | New CLI and server API |
| Decision-relation and history backfills | `papyrus monitors backfill*` | Break-glass: one-off repairs over raw rows |
| Local monitor worker | `papyrus monitors run --auth iam` | Pipeline: a scheduled job |
| Stack changes and Lambda bundles | Change sets, `build.py --upload` | Pipeline |

## Knowledge runs

| Operation | Today | Home |
|---|---|---|
| Start a run, read runs and cost | `aws stepfunctions start-execution`, `papyrus knowledge runs` | New CLI and server API (PPY-e529c4) |
| Knowledge query | `papyrus knowledge query` (always IAM-signed) | Existing CLI, moved to the user lane (PPY-544564) |
| Publish-run, entity and cluster review | `papyrus knowledge ... --auth user` | Existing CLI |
| Snapshot and archive file writes | `papyrus knowledge snapshot`, `archive` | New CLI and server API (PPY-029a99) |
| Vector index | `papyrus knowledge vector-index` | New CLI and server API, or a job |
| Finding a site's outputs, bucket and distribution | `ampx generate outputs`, `aws lambda get-function-configuration` | New: the CLI discovery document `papyrus login` already reads |
| Stacks and images | `cdk deploy`, `build_image.sh` | Pipeline |

## Content and projection

| Operation | Today | Home |
|---|---|---|
| Publish, unpublish, set a slug, upload story images | `papyrus ops content`, `stories` | Existing CLI |
| Re-project a site, home-page snapshot, reader snapshot | `ops content project`, `home-page snapshot`, `proposals publish` | New CLI and server API (PPY-029a99) |
| Automations | `papyrus automations` (Lambda invoke and table reads) | Existing server API; move the CLI to it (PPY-544564) |
| Markus import and export, procedure registration, reference text and corpora sync | Direct S3 from the laptop | New CLI and server API, with signed URLs |
| Renditions backfill | `ops content renditions` | New CLI and server API, or a job |
| App rebuild, preview upload | `ops content rebuild`, `upload-preview` | Pipeline |
| Stuck projection lease | `aws dynamodb` | Break-glass, with a server command later |
| Whole-site and cross-account copies | `ops site copy`, `ops content copy-backend` | Break-glass: they bypass the API across accounts |

## Secrets, identity, email and debugging

| Operation | Today | Home |
|---|---|---|
| Model and search keys read on the laptop | SSM fallback in several commands | New: the server makes the call (PPY-6bdd4c) |
| Rotating generated secrets | `aws ssm put-parameter` | Pipeline |
| First-time secrets from a person; Google sign-in secrets | `aws ssm put-parameter`, `papyrus site google-secrets` | Break-glass: the first value has to come from a person, and sign-in can't depend on itself |
| Sign in | `papyrus login`, `whoami`, `doctor` | Existing CLI |
| Email replay, console chat triage | `aws lambda invoke`, `logs tail`, `dynamodb` | New CLI and server API |
| SES and console-chat smoke checks | `scripts/` | Pipeline |
| SES identities during sandbox | `aws sesv2` | Break-glass until SES leaves the sandbox |
| App-shell, edge, newsletter and chat stacks; Amplify builds and logs | `npm run deploy`, change sets, `aws amplify` | Pipeline |
| GitHub OIDC provider, DNS, personal sandboxes | `cdk deploy`, `aws route53`, `ampx sandbox` | Break-glass: pipeline bootstrap, rare, and personal development |

## Commands that use AWS without saying so

Remove these first, because they contradict the sign-in rule:

- `graphql_request_headers` in `src/papyrus_content/graphql_http.py` falls back to the AWS credential chain when no user session applies. It should refuse and say to log in (PPY-5f119a).
- `papyrus knowledge query` and `knowledge runs` ignore the user session.
- `papyrus automations` and `proposals publish` call Lambda or the monitoring table directly.
- `knowledge snapshot`, `archive` and `home-page snapshot --auth user` take a user session for GraphQL but still write S3, CloudFront and the key-value store with AWS credentials.
- `ops content inspect` reports only the AWS credential chain.

The final step, in PPY-ba1f31, is updating the manuals and proposing reduced operator permissions. That IAM change is Ryan's decision.
