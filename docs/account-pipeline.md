# The account pipeline: a deployment's AWS account is defined in Git

Epic PPY-9bd776. Rule (Ryan, 2026-11-11): nobody creates a cloud resource by hand. Every resource is defined in Git and applied by a pipeline on merge. Agents read with the AWS CLI and never create or change.

This page is for a **deployment repository** (a publication group's own repo and AWS account, in our organisation, another organisation, or a client's account). Papyrus's own release pipeline for the Anthus accounts is [infra/pipeline/README.md](../infra/pipeline/README.md); it is unchanged and keeps working. Nothing here edits the `papyrus-pipeline-approver` or `papyrus-stack-pipeline` stacks.

## The pieces

| Piece | Where | What it is |
| --- | --- | --- |
| Account baseline | `infra/account/baseline.yaml` | One CloudFormation stack, `<prefix>-github-deploy`: the GitHub OIDC provider and five roles. Seeded once by a person, afterwards changed only by the pipeline, with no person's approval. |
| Account stacks | `infra/account/stacks/` (`dns`, `budget`, `certificate`, `ses`, `placeholder`) | Templates a deployment repo references as `papyrus:infra/account/stacks/dns.yaml`. |
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

- **`<prefix>-github-deploy`**: only a run of the repository started by a push to `main`. Starts and reads Amplify jobs on the production branch. Creates, reads and executes CloudFormation change sets on stacks named `<prefix>-*`, always through the service role (a change set made any other way is refused). Looks up a hosted zone and one budget by name, read-only. It is explicitly denied every write to the baseline stack. Cannot create or change IAM.
- **`<prefix>-github-plan`**: any pull request in the repository (not forks). Read-only: describes `<prefix>-*` stacks, reads their templates, looks up the zone and budget. Creates nothing.
- **`<prefix>-github-roles-apply`**: only a job in the GitHub environment `pipeline-roles`, whose deployment branch policy allows `main` only. It needs no person's approval. Can run a change set on the baseline stack only, through the roles service role.
- **`<prefix>-cloudformation`**: what CloudFormation itself uses for the account stacks. Route 53 zones and records, one budget, ACM certificates, SES identities, CloudFront distributions and functions for the placeholder site. No IAM.
- **`<prefix>-cloudformation-roles`**: what CloudFormation uses for the baseline stack. IAM on the five pipeline roles and the GitHub provider, and nothing else.

Residual risk: whoever can merge to `main` can change, through the roles job, what the pipeline may do. The safety is the main-only trust on every role, branch protection on `main` (a pull request and the `ci` check), the roles service role's narrow IAM rights, and the deployer refusing any Replace or Remove that `allowed-changes.json` does not list. The change set is in the job summary after the fact.

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

- The CDK bootstrap stack (`CDKToolkit`) is CDK's own template, usually made by `cdk bootstrap`. It is a hand-made resource in most accounts. Adopting it means importing it with the template version the CDK CLI ships; see the epic.
- The Anthus accounts' hand-made roles, zones and providers (story PPY-b5ddec): design and dry-run only, each import read by Ryan first.
- Seeding accounts from the organisation level with StackSets (story PPY-a41df9) and the client-owned-account access stack (story PPY-1f6e73): designs in the Humorus epic HUM-be87f4.
