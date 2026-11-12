# The account pipeline: a deployment's AWS account is defined in Git

Epic PPY-9bd776. Rule (Ryan, 2026-11-11): nobody creates a cloud resource by hand. Every resource is defined in Git and applied by a pipeline on merge. Agents read with the AWS CLI and never create or change.

This page is for a **deployment repository** (a publication group's own repo and AWS account, in our organisation, another organisation, or a client's account). Papyrus's own release pipeline for the Anthus accounts is [infra/pipeline/README.md](../infra/pipeline/README.md); it is unchanged and keeps working. Nothing here edits the `papyrus-pipeline-approver` or `papyrus-stack-pipeline` stacks.

## The pieces

| Piece | Where | What it is |
| --- | --- | --- |
| Account baseline | `infra/account/baseline.yaml` | One CloudFormation stack, `<prefix>-github-deploy`: the GitHub OIDC provider and five roles. Seeded once by a person, afterwards changed only by the pipeline, with no person's approval. |
| Account stacks | `infra/account/stacks/` (`dns`, `budget`, `certificate`, `ses`, `cloudtrail`, `placeholder`) | Templates a deployment repo references as `papyrus:infra/account/stacks/dns.yaml`. |
| Deployer | `infra/pipeline/stack_deploy.py --config <path>` | The same deployer Papyrus releases use, with optional config for deployment repos: `root`, `papyrus:` templates, inline templates, `enabled`, `fromEnv` / `fromStackOutput` parameters, CloudFormation **import**, a name-server check, `group`, and a `changed` check. |
| Workflow | `.github/workflows/account-stacks.yml` | Reusable (`workflow_call`): lint, read-only plan on pull requests, deploy on merge to `main`, apply of the baseline when it differs. |

## What a deployment repo contains

`infra/stacks.json` (stack settings only, no account ids), optional `infra/stacks/*.yaml` of its own, `infra/expected-nameservers.json`, `infra/allowed-changes.json`, and a workflow that calls `account-stacks.yml`:

```yaml
name: Infrastructure
on:
  pull_request: {branches: [develop, main]}
  push: {branches: [main], paths-ignore: ["project/**"]}
jobs:
  account:
    permissions: {contents: read, id-token: write}
    uses: AnthusAI/Papyrus/.github/workflows/account-stacks.yml@<papyrus tag>
    with:
      prefix: <prefix>
      papyrus-ref: <the same tag>
      aws-account-id: ${{ vars.AWS_ACCOUNT_ID }}
```

The repository variable is `AWS_ACCOUNT_ID` (a variable, not Git). The budget alert address is never a GitHub variable or secret either: workflow logs on a public repository are public. The budget stack reads it from an SSM String parameter, `/<prefix>/budget-alert-email`, at deploy time (`AWS::SSM::Parameter::Value<String>`), and a person creates that parameter once.

A stack that must wait is `"enabled": false` with a `reason`. A stack that can only succeed after the registrar delegates the domain (a DNS-validated certificate, and the placeholder site that needs it) is enabled with `"when": {"delegated": {"zone": "<domain>", "expectedFile": "expected-nameservers.json"}}`: until the public name-server answers for the domain equal the expected set, the deployer skips it with a notice (not an error), and the next run after delegation creates it. This avoids a CloudFormation stack that sits in progress for hours waiting for ACM validation and may roll back. `stack_deploy.py delegation --config <path>` reports the state with no AWS credentials and writes `delegated=true|false` to `$GITHUB_OUTPUT`, which a scheduled watcher can use.

Mail: the `ses` stack creates the identity with Easy DKIM, a custom MAIL FROM domain (MX and SPF records) and a DMARC record in the zone. SES verifies by itself once the domain is delegated. It sets no DMARC report address (an address does not go in Git). SES production access is a request to AWS that a person makes.

Mail events: the `ses` stack also creates, before any mail is sent, a configuration set (reputation metrics on, sending on, the suppression list for bounces and complaints), an SNS topic, and an event destination that publishes only BOUNCE, COMPLAINT, DELIVERY_DELAY and REJECT to the topic. SEND, OPEN and CLICK are not recorded: no tracking pixels. The topic policy lets only SES, from this account and this configuration set, publish. `ConfigurationSetName` and `EventTopicName` are required parameters with no default, so a config cannot forget them; start both with the deployment prefix (the service role is scoped to `<prefix>-*`).

Audit trail: the `cloudtrail` stack creates one multi-region trail (management events only: no data events, no Insights; global service events included; log file validation on) and a private S3 bucket for its logs: all public access blocked, owner-enforced ownership, SSE-S3 encryption, TLS required, retained if the stack is deleted, no versioning (CloudTrail never overwrites a log object and validation proves integrity). Logs expire after `RetentionDays` (default 400, minimum 30) and incomplete multipart uploads after 7 days. Cost: the first copy of management events in an account is free; only the S3 storage of the logs is billed. Name the trail and stack with the prefix (`<prefix>-trail` in a stack named `<prefix>-cloudtrail`): the bucket gets a generated name that starts with the stack name.

Placeholder: the `placeholder` stack serves one labelled HTML page on the apex and www from a CloudFront Function (no bucket, no upload), until the real site takes the domain over.

## Check the repository's OIDC subject before the apply

The roles trust the repository's OIDC subject. Newer GitHub repositories can use **immutable subject claims**, where the subject is `repo:<owner>@<owner id>/<repo>@<repo id>:...` instead of `repo:<owner>/<repo>:...`; a role that trusts the classic form refuses every run (found on Humorus, 2026-11-11). Read the repository's prefix and pass it as `GithubSubjectPrefix` (leave it empty for the classic form):

```bash
gh api repos/<owner>/<repo>/actions/oidc/customization/sub    # sub_claim_prefix
```

## The one apply by a person

The first apply of the baseline cannot come from a pipeline that does not exist yet. It is a single documented command (replacing `bootstrap.sh` for a deployment account). It writes no repository variable of any repository.

```bash
aws cloudformation deploy --stack-name <prefix>-github-deploy \
  --template-file infra/account/baseline.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides Prefix=<prefix> GithubRepository=<owner>/<repo> BudgetName=<budget name>
```

Review first with `--no-execute-changeset`. Add `CreateOidcProvider=false` if `aws iam list-open-id-connect-providers` already lists `token.actions.githubusercontent.com`. Then set the `AWS_ACCOUNT_ID` variable on the deployment repo and create the GitHub environment `pipeline-roles` **before** merging any change to the baseline, with its deployment branch policy set to the release branch only and **no required reviewers** (nobody has to click anything; add reviewers there only if a deployment wants a human gate, in which case the roles job waits for it). Without the branch policy a job on any branch could name the environment and assume the roles-apply role. After this, every change goes through the pipeline.

## What the roles can do, in plain English

- **`<prefix>-github-deploy`**: only a run of the repository started by a push to `main`. Starts and reads Amplify jobs on the production branch, and for the first build reads the app, reads and updates that one branch's variables, and lists SSM parameter names. Creates, reads and executes CloudFormation change sets on stacks named `<prefix>-*`, always through the service role (a change set made any other way is refused). Looks up a hosted zone and one budget by name, read-only. It is explicitly denied every write to the baseline stack. Cannot create or change IAM.
- **`<prefix>-github-plan`**: any pull request in the repository (not forks). Read-only: describes `<prefix>-*` stacks, reads their templates, looks up the zone and budget. Creates nothing.
- **`<prefix>-github-watch`**: only a run of the repository on its default branch (parameter `DefaultBranch`, default `develop`; GitHub runs scheduled workflows only from there). Read-only: describes `<prefix>-*` stacks, reads the Amplify app, and lists SSM parameter **names** (`ssm:DescribeParameters`). It cannot read a parameter value.
- **`<prefix>-github-roles-apply`**: only a job in the GitHub environment `pipeline-roles`, whose deployment branch policy allows `main` only. It needs no person's approval. Can run a change set on the baseline stack only, through the roles service role.
- **`<prefix>-cloudformation`**: what CloudFormation itself uses for the account stacks. Route 53 zones and records, one budget, ACM certificates, SES identities, configuration sets and event destinations (named `<prefix>-*`), SNS topics named `<prefix>-*`, one CloudTrail trail named `<prefix>-*` and S3 buckets named `<prefix>-*` (create, policy, encryption, lifecycle; for the trail logs), CloudFront distributions and functions for the placeholder site. No IAM.
- **`<prefix>-cloudformation-roles`**: what CloudFormation uses for the baseline stack. IAM on the six pipeline roles and the GitHub provider, and nothing else.

Residual risk: whoever can merge to `main` can change, through the roles job, what the pipeline may do. The safety is the main-only trust on every role, branch protection on `main` (a pull request and the `ci` check), the roles service role's narrow IAM rights, and the deployer refusing any Replace or Remove that `allowed-changes.json` does not list. The change set is in the job summary after the fact.

## The app shell

A site's Amplify app, Cognito pool and the rest live in one per-site CDK stack, defined in `infra/amplify-app-shell` and synthesized by the published command `papyrus-infra synth --site infra/site.json --out cdk.out`. The reusable workflow `.github/workflows/app-shell-deploy.yml` deploys it on merge to `main`, with GitHub OIDC and no person involved:

```yaml
jobs:
  app-shell:
    permissions: { contents: read, id-token: write }
    uses: AnthusAI/Papyrus/.github/workflows/app-shell-deploy.yml@<papyrus tag>
    with:
      prefix: myco
      papyrus-ref: <the same tag>
      aws-account-id: ${{ vars.AWS_ACCOUNT_ID }}
      stack-name: <the stack name infra/site.json produces>
      site-id: <siteId>
```

- **`synth`** runs on pull requests, pushes and manual runs, with no AWS credentials. It installs the repository's dependencies, synthesizes, and runs `infra/pipeline/check_cdk_manifest.py`, which fails unless the cloud assembly holds exactly one CloudFormation stack and its name is `stack-name`.
- **`deploy`** runs only for a push or manual run on `main`. It assumes `<prefix>-github-deploy`, runs `aws-cdk deploy` on the already synthesized assembly. It reads the stack output `CmsAppId` and passes it on as the job output `app-id`.
- **`build`** (only when `start-amplify-build` is true; the default is false) starts the Amplify release job through `amplify-deploy.yml`, as `<site-id>-github-deploy`. Leave it off until the app has a build source (below). It calls the `main` copy of `amplify-deploy.yml`, because `./` in a reusable workflow resolves in the caller's repository.

### The roles, and the power, in plain English

The baseline's `<prefix>-github-deploy` role gains permission to assume exactly the CDK bootstrap deploy role and file-publishing role (`cdk-<CdkQualifier>-deploy-role-...` and `cdk-<CdkQualifier>-file-publishing-role-...`, never the image-publishing or lookup roles; the qualifier parameter defaults to `hnb659fds`).

What that means: **a push to `main` can run any CloudFormation change as the CDK CloudFormation execution role.** Read-only checks of the Humorus account on 2026-11-11 found the `CDKToolkit` bootstrap at version 33 with qualifier `hnb659fds`, the `CloudFormationExecutionPolicies` parameter empty, and so the AWS-managed `AdministratorAccess` policy attached to `cdk-hnb659fds-cfn-exec-role`; the roles `cdk-hnb659fds-{cfn-exec,deploy,file-publishing,image-publishing,lookup}-role` exist. For that account the execution role **is** `AdministratorAccess`. The baseline's explicit deny on the baseline stack does not bind the CDK path, because the change set is made by the CDK deploy role, not by the pipeline role. Three things hold it in check: main-only trust on the role, branch protection on `main`, and the manifest check, which is what stops a synth from naming another stack (the baseline, say). The Replace/Remove refusal of `stack_deploy.py` does not apply to CDK deploys. A tighter bootstrap (`CloudFormationExecutionPolicies` set to a narrow policy) is a follow-up.

### How the Amplify app gets its code (the Machines on Machines mechanism)

This is how every Papyrus Amplify site works today, checked read-only on the Machines on Machines app:

- The app-shell stack creates the Amplify app with **no repository**. Amplify's own auto-build is off (`enableBranchAutoBuild: false`), there are no webhooks, and the production branch builds only when told to.
- The app is then **connected to its GitHub repository once**, in the Amplify console, by an organisation administrator authorizing the Amplify GitHub App for that repository ("Connect repository", see [site-hosting.md](site-hosting.md#one-time-github-app-connection-per-app)). Afterwards `get-app` shows the repository and `repositoryCloneMethod: TOKEN`: Amplify holds the GitHub App's installation access. **We hold no token** (no PAT, nothing in SSM or GitHub secrets), and there is no API for this handshake.
- Every deploy after that is started by the repository's own workflow: a push to `main` signs in with GitHub OIDC as `<siteId>-github-deploy` (main only) and runs `amplify start-job --job-type RELEASE --commit-id <sha>`, then waits for it ([amplify-deploy.yml](../.github/workflows/amplify-deploy.yml)). That role is created by the app-shell stack. The Amplify build runs the backend (`ampx pipeline-deploy`) and the Next build.

So the one hand step is the **connection**: an authorization, like giving the registrar the name servers or creating the Google client, not a resource. It is a person-only step, once per app. Everything else is codified: the app, its roles, the branch, the OIDC role and each deploy. The `app-shell-deploy.yml` workflow can run `start-amplify-build` after the stack deploys; leave it false until the app has been connected, because a job on an unconnected app fails.

If a deployment must have no such step at all, the route to evaluate is a token-free CodeCommit mirror (Actions pushes each commit to an AWS CodeCommit repository with short-lived OIDC credentials, and the app builds from CodeCommit with an IAM service role). A spike has to prove it first; nothing here builds it. Amplify Hosting does not support manual deploys for server-side rendered apps (AWS documentation), so the Git-less route is not available for these apps.

### The first build starts by itself

A brand-new site backend is too big for one CloudFormation operation, so its first Amplify build runs twice: pass 1 with the branch variable `PAPYRUS_BOOTSTRAP_STAGE=1`, then pass 2 without it ([site-hosting.md](site-hosting.md#start-a-new-papyrus-site-the-two-deploy-first-backend)). Nobody has to start it or tell anyone. Once the two person-only steps are done, a watcher notices and the first build runs, and then the watcher turns itself off:

1. the Amplify app has a repository connected (see above), and
2. the Google client parameters exist in SSM (`papyrus site google-secrets set`, [google-oauth-setup.md](google-oauth-setup.md)).

Two reusable workflows and one script do it, `infra/pipeline/amplify_first_build.py`:

- **`first-build-watch.yml`** is called by a thin scheduled workflow on the repository's default branch every 15 minutes. It signs in as `<prefix>-github-watch` (read-only, default branch only) and runs `amplify_first_build.py check`: the app-shell stack has `CmsAppId`, `get-app` shows a repository, and SSM has parameters named `.../GOOGLE_CLIENT_ID` and `.../GOOGLE_CLIENT_SECRET` under `/amplify/<appId>/`. It reads names, never values, and prints only a plain status line (never the app id). Not ready is not an error: the run just says what is missing. When ready it dispatches `first-build.yml` on `main` and disables its own calling workflow, so it never runs again.
- **`first-build.yml`** runs only for a push or manual dispatch on `main`, as `<prefix>-github-deploy`, and runs `amplify_first_build.py run --commit-id <sha>`. It is idempotent and resumable. It marks its Amplify jobs with the commit message `first-build pass 1` and `first-build pass 2` and decides from the branch's jobs: a pass-2 job succeeded means done; a running first-build job is waited for; a pass-1 job that succeeded means remove `PAPYRUS_BOOTSTRAP_STAGE` (update-branch replaces the whole variable map, so it reads the branch first and keeps every other variable exactly) and start pass 2; no first-build job yet means set the variable, start pass 1, wait, remove the variable, start pass 2, wait. It polls every 20 seconds with an overall timeout of 50 minutes. When pass 2 has succeeded it runs `gh workflow disable` on the watcher, with the job's own token.
- A failed or cancelled pass stops the run with exit 1 and a message, and never loops. A person reads the Amplify job log and fixes the cause. A failed first create can also leave the Amplify backend root stack `amplify-<appId>-<branch>-branch-<hash>` in `ROLLBACK_COMPLETE`; CloudFormation cannot update it, so a person or the pipeline deletes it first. Then dispatch `first-build.yml` with `retry-failed` true to start again. If the timeout runs out, the Amplify job keeps running; running again resumes waiting.

The callers (the file names are the caller's; `actions: write` is needed to dispatch and disable):

```yaml
# .github/workflows/first-build-watch.yml  (default branch)
name: first-build-watch
on: { schedule: [{ cron: "*/15 * * * *" }], workflow_dispatch: {} }
jobs:
  watch:
    permissions: { contents: read, id-token: write, actions: write }
    uses: AnthusAI/Papyrus/.github/workflows/first-build-watch.yml@<papyrus tag>
    with:
      prefix: myco
      papyrus-ref: <the same tag>
      aws-account-id: ${{ vars.AWS_ACCOUNT_ID }}
      stack-name: <the app-shell stack name>
      watcher-workflow-file: first-build-watch.yml
      dispatch-workflow: first-build.yml
---
# .github/workflows/first-build.yml  (on main)
name: first-build
on: { workflow_dispatch: { inputs: { retry-failed: { type: boolean, default: false } } } }
jobs:
  first-build:
    permissions: { contents: read, id-token: write, actions: write }
    uses: AnthusAI/Papyrus/.github/workflows/first-build.yml@<papyrus tag>
    with:
      prefix: myco
      papyrus-ref: <the same tag>
      aws-account-id: ${{ vars.AWS_ACCOUNT_ID }}
      stack-name: <the app-shell stack name>
      retry-failed: ${{ inputs.retry-failed || false }}
```

The deploy role's first-build rights are limited to that one app and branch (`GetApp`, `GetBranch`, `UpdateBranch`, `ListJobs`, `StartJob`, `GetJob`) plus `ssm:DescribeParameters`. `UpdateBranch` can change that branch's environment variables, so it stays on the main-only role.

### Google sign-in (person-only)

Signing in with Google also needs a person once: the Cognito domain prefix, the two redirect URIs in the Google console, and `papyrus site google-secrets set`. Follow [google-oauth-setup.md](google-oauth-setup.md).

## Adopting what already exists

A zone, budget or role made by hand is **imported**, never replaced:

- The template has `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`, so deleting the stack never deletes the resource.
- The deployer looks the existing resource up by name (read-only), creates a CloudFormation `IMPORT` change set, and refuses to execute it if any change is not an `Import`. A follow-up update then applies the template's properties under the usual Remove/Replace safety.
- For a zone, the deploy then compares the zone's name servers to `infra/expected-nameservers.json` and fails if they differ. Pull requests show the same check in the read-only plan.
- Imports into a live account are read by a person (the change set is in the job summary) before the first merge that triggers them.

## What a person still does

Nothing else can be automated:

1. The one baseline apply above, and creating the `pipeline-roles` environment with its branch policy (no reviewers).
2. Giving the registrar the zone's four name servers.
3. Creating the Google OAuth client for sign-in.
4. The SSM String parameter `/<prefix>/budget-alert-email` with the alert address (for an adopted budget it must equal the live subscriber: `NotificationsWithSubscribers` and `BudgetName` are create-only properties of `AWS::Budgets::Budget`, so a difference would replace the budget; the deployer refuses any Replace).
5. Secret values. `AWS::SSM::Parameter` cannot create a `SecureString`, and values never go in Git, so a person (or `papyrus site google-secrets set`) puts the value. The pipeline may manage everything around it.

## Not covered yet

- A tighter CloudFormation execution policy for the app shell (see "The app shell").
- The CDK bootstrap stack (`CDKToolkit`) is CDK's own template, usually made by `cdk bootstrap`. It is a hand-made resource in most accounts. Adopting it means importing it with the template version the CDK CLI ships; see the epic.
- The Anthus accounts' hand-made roles, zones and providers (story PPY-b5ddec): design and dry-run only, each import read by Ryan first.
- Seeding accounts from the organisation level with StackSets (story PPY-a41df9) and the client-owned-account access stack (story PPY-1f6e73): designs in the Humorus epic HUM-be87f4.
