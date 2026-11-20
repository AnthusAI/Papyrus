# Shared stacks deploy from the release (PPY-b8cc79)

> **Deployment accounts.** A deployment repository in another organisation or a client's account uses the account pipeline instead of `bootstrap.sh`: [docs/account-pipeline.md](../../docs/account-pipeline.md) (epic PPY-9bd776). Nothing on this page changes for the Anthus accounts.

`papyrus-monitoring` and `papyrus-newsletter-sending-operators` are deployed by `.github/workflows/stack-deploy.yml`. Nobody creates or executes a change set for them by hand.

| File | What it is |
| --- | --- |
| `stacks.json` | The stacks, in deploy order: template, the paths that are their inputs, parameters, zone lookups, which `build.py` zips feed which code-key parameter, capabilities. |
| `allowed-changes.json` | The Removes and Replaces a release may make on purpose, each with its reason. Empty it again once they have deployed. |
| `stack_deploy.py` | The whole deploy, with its safety checks. Tested by `procedures/newsroom/tests/test_stack_deploy.py`. |
| `papyrus-stack-pipeline.yaml` | The three IAM roles the release deploys with. Applied only by the `role-stack-deploy` workflow, after its automatic check. |
| `papyrus-pipeline-approver.yaml` | The small stack with the roles that workflow runs as (and, on request, the account's GitHub OIDC provider). Applied once per account by a person. |
| `role_stack.py`, `.github/workflows/role-stack-deploy.yml` | The plan, the automatic check and the apply for the pipeline roles (`role-change-check.yml` runs the check on a pull request). |
| `bootstrap.sh`, `create-environment.sh` | The one-time setup per account (and the emergency path), and the GitHub environment the apply role trusts. |

## How a release deploys

1. **Pull request** touching a stack's paths: the `dry-run` job (role `papyrus-stack-plan-github`, read-only) prints, as a job summary, the stack's state, resources added, removed and modified against the live template, new parameters, and whether the release would stop. It builds nothing and creates nothing. It cannot know which modifications replace a resource; the release's change set does, and stops on any Replace that is not listed.
2. **Release** (develop merged to main): `scope` compares the push with the last commit this workflow finished on (so a failed or stopped release is retried by the next one, and a docs-only release deploys nothing). The `tests` workflow runs on the merged commit. Then `deploy` (role `papyrus-stack-deploy-github`, only from `main`, one run at a time) takes each stack in scope in order:
   - checks the stack state; builds and uploads the zips with `infra/monitoring/build.py` (content-addressed, so re-uploading is harmless); validates every parameter and key;
   - uploads the template, creates a change set (named `papyrus-release-<sha>-<run>`) through the CloudFormation service role, and polls it;
   - an empty change set is a quiet success; a Remove or Replace not on `allowed-changes.json` deletes the change set and stops; otherwise it executes and polls the stack until it finishes.

## Safety checks

- Every parameter value is a single line with no control characters; every `*CodeKey` is exactly `papyrus-monitoring/<kind>-<64 hex>.zip`.
- A stack in `UPDATE_ROLLBACK_FAILED`, any `*_FAILED`, `ROLLBACK_COMPLETE` or any `*_IN_PROGRESS` state stops the run before anything is created. (`UPDATE_ROLLBACK_COMPLETE`, a previous update that rolled back cleanly, may be updated.)
- Remove, Replace (`True`, `Conditional`, `Dynamic`, or `RequiresRecreation: Always`) on a resource not listed for that stack and logical id: stop, execute nothing. To go ahead on purpose, add an entry (with a reason) in a reviewed pull request, release, then remove it.
- No `aws cloudformation wait`. Success needs a success status and proof that this execution ran (progress seen, or the change set reports `EXECUTE_COMPLETE`), so a stale `UPDATE_COMPLETE` is never read as done. An execution that never starts or runs past the timeout fails the job. No retries.
- A failed update fails the job, and the job summary and annotation carry the first failed resource event (the later ones are the rollback). Exit code 1 for a failure, 2 for a refusal.
- One run at a time (workflow concurrency group `stack-deploy`, and the script refuses a stack that is `*_IN_PROGRESS`).
- Change sets the pipeline does not own (for example `operators-first`) are left alone; only unexecuted `papyrus-release-*` change sets from earlier runs are deleted. A stack in `REVIEW_IN_PROGRESS` is created with a CREATE change set; the other change sets then show as obsolete.

## When a release fails

- **A change set that cannot be created** (for example `AWS::EarlyValidation::ResourceExistenceCheck`): the job reads the change set's events before deleting it, and the job summary names the resource, the check and the reason. The usual cause is a resource with a fixed name that already exists outside the stack. `OperatorTable` uses `DeletionPolicy: RetainExceptOnCreate`, so a first create that rolls back removes its own empty table; any other leftover is deleted by a person (the pipeline never deletes data) or imported, then the release is re-run.
- **A rollback that is refused for a permission**: the service role is changed only through `role-stack-deploy`. The release deploys the templates on `main`, so a template fix reaches AWS only with a release; a re-run of a failed run deploys the commit that run was for.
- **Order after a fix to both**: merge the fix, check that the `role-stack-deploy` run applied, remove any leftover resource the summary names, then release (or re-run the release on `main`).

## The shared-tier stacks (PPY-daf673)

`papyrus-shared-staging-foundation` and `papyrus-shared-prod-foundation` are in `stacks.json` with `"group": "shared"`, their own service role (`papyrus-shared-deploy-cloudformation`) and, in the workflow, their own plan and deploy roles (`papyrus-shared-plan-github`, `papyrus-shared-deploy-github`), which reach only stacks named `papyrus-shared-*`. A stack with a `hold` is planned on every pull request (the summary says **HELD**) and never created or changed; taking the `hold` out in a reviewed pull request is the go. What they create and what must be said go to first: [docs/shared-stack.md](../../docs/shared-stack.md).

## What does not fit

- Edge stacks and per-site newsletter stacks are not in scope. The same file could carry them.
- `papyrus-monitoring`'s `CodeBucket` is read from the live stack, and the template bucket for every stack comes from there. On a new account, before that stack exists, the CDK bootstrap bucket name is used (see "A new account, in order").

## Changing the pipeline roles: merge, and the automatic check applies

The release deploys through IAM roles defined in `papyrus-stack-pipeline.yaml` (the `papyrus-stack-pipeline` stack). A pipeline must not be able to raise its own permissions, so the release never touches that stack. A **separate workflow** does, and no person clicks anything: an automatic check stands where the approval used to be.

**The normal path. Nobody runs a command.** After any change to `infra/pipeline/papyrus-stack-pipeline.yaml`, this is the whole process:

1. Open the pull request. `.github/workflows/role-change-check.yml` runs `python infra/pipeline/role_stack.py check` with no AWS access: it compares the template with its base branch and fails when the change breaks a hard rule or touches an IAM statement that `allowed-role-changes.json` does not list. The failure prints each statement's fingerprint; add `{"fingerprint": "...", "reason": "..."}` for it to `infra/pipeline/allowed-role-changes.json` in the same pull request.
2. Merge to `develop` (or `main`). Develop is enough: roles often must change before the release that needs them, and only merged code ever runs the workflow.
3. `.github/workflows/role-stack-deploy.yml` starts. Its `plan` job makes a CloudFormation change set against the live stack, prints all of it in the job summary with an IAM view of every statement added or removed, and runs the same check again, now against what is deployed, plus `allowed-changes.json` for any Remove or Replace. A refusal deletes the change set and stops the run, so nothing is applied. If the deployed roles already match, it ends quietly.
4. Otherwise the `apply` job runs at once. It refuses if the template or the stack changed since the plan, executes that exact change set by name, polls it, and verifies the deployed template equals the repository. On a failure it prints the first failed resource and leaves the stack clean (an update rolls back; a first create that rolled back is deleted so the next run starts fresh).

**The hard rules** (no list can allow them; fix the template): no AWS-managed `AdministratorAccess`, `PowerUserAccess` or `IAMFullAccess`; no Allow of `*`, `iam:*`, `sts:*`, `organizations:*` or `account:*`; no identity-changing IAM action (create or pass a role, attach or put a policy, create a user or key, change a trust policy or boundary) on a resource that is not named by a prefix; no `*` principal in a trust policy; and a GitHub OIDC trust must match an exact audience and an exact subject, never a pattern.

**What an agent does:** write the template change and the `allowed-role-changes.json` entries in one pull request, merge it when its checks are green, then read the `plan` and `apply` jobs of the `role-stack-deploy` run ([workflow runs](https://github.com/AnthusAI/Papyrus/actions/workflows/role-stack-deploy.yml)) to confirm the roles were applied. Agents never apply the stack another way and never work around a refusal.

**Residual risk, plainly.** A pull request that changes the template can also change the check, its lists or this workflow, because they live in the same repository, so the check catches mistakes and unlisted changes, not a determined change to its own rules. The outer wall is the approver stack below: `papyrus-pipeline-roles-cloudformation` can only touch the three pipeline roles and their managed policies by name, and the approver stack itself is changed only by a person, never by the workflow. The branch ruleset (`protect-branches.sh`) requires green tests before any of it merges.

### The approval roles, and what they can do

They live in a **separate small stack**, `papyrus-pipeline-approver` (`papyrus-pipeline-approver.yaml`), so that the workflow can never change its own permissions.

| Role | Trusted for | Can do |
| --- | --- | --- |
| `papyrus-pipeline-roles-plan-github` | pushes to `develop` and `main` of this repository (OIDC `sub` and `aud` checked) | read the `papyrus-stack-pipeline` stack; create and delete change sets on it, only through the service role; pass that one role to CloudFormation. It cannot execute a change set. |
| `papyrus-pipeline-roles-apply-github` | the GitHub environment `pipeline-roles` only: `sub` is exactly `repo:AnthusAI/Papyrus:environment:pipeline-roles` | execute, read and delete change sets on the `papyrus-stack-pipeline` stack, and delete that stack when a first create has rolled back. No IAM rights of its own. |
| `papyrus-pipeline-roles-cloudformation` | CloudFormation, passable only from the plan role | IAM rights on the three pipeline roles and the stack's managed policies by name, and nothing else. It cannot create any other role, attach an AWS-managed policy, or touch the approver roles or stack. |

**Residual risk, plainly.** Whoever can approve can, through this stack, change what the pipeline roles may do, and so (one step removed) what the release may deploy. The approval click is the control: read the IAM view in the summary before approving. Branch limits (`develop`, `main`) on the environment and the reviewer requirement are GitHub settings, and an administrator of the repository can change them. The approver stack itself is changed only by a person (below), never by the workflow.

### One-time setup for a new AWS account (a person, once)

This is the single step the workflow cannot do for itself: create the small approver stack, and the GitHub environment with its reviewer.

```bash
# 1. In AWS: the three roles above (and, with --create-oidc-provider, the account's GitHub OIDC provider if it has none).
export AWS_PROFILE=<profile for the account>      # log in first, for example aws sso login
infra/pipeline/bootstrap.sh --account <12-digit account id> --approver-only

# 2. In GitHub: the environment `pipeline-roles` with the develop/main branch limit (no reviewer).
infra/pipeline/create-environment.sh
```

`bootstrap.sh` checks the account you named, shows a change set, asks you to type `yes`, applies it, sets the `AWS_ACCOUNT_ID` repository variable and verifies the roles. Re-run it only when `papyrus-pipeline-approver.yaml` changes. `create-environment.sh` needs the `gh` CLI signed in as a repository administrator; it is safe to run again. After these two commands, the first run of `role-stack-deploy` creates the `papyrus-stack-pipeline` stack the same way as any later change: plan, approve.

**Alternative in the AWS console, no local tools:** open CloudShell in the account and paste `git clone --depth 1 https://github.com/AnthusAI/Papyrus && Papyrus/infra/pipeline/bootstrap.sh --account <12-digit account id> --approver-only`. (A CloudFormation quick-create link needs the template in S3, which this repository deliberately has no bucket for; uploading `papyrus-pipeline-approver.yaml` in the console's "Create stack" page also works, with the three parameters left at their defaults.) CloudShell has no `gh`, so set the `AWS_ACCOUNT_ID` repository variable by hand when the script says so. The environment still needs `create-environment.sh` (or the same settings made by hand in the repository's Settings, Environments).

**What the setup creates:** AWS: stack `papyrus-pipeline-approver` with the three roles above and, only with `--create-oidc-provider`, the GitHub OIDC provider. GitHub: the environment `pipeline-roles` with one required reviewer and two allowed branches, and the `AWS_ACCOUNT_ID` repository variable. Nothing else.

**The emergency path.** If the workflow itself is unavailable, `infra/pipeline/bootstrap.sh --account <12-digit account id>` (without `--approver-only`) also applies the `papyrus-stack-pipeline` stack, with the same change set shown and confirmed. Like all of `bootstrap.sh`, it refuses unless the templates in your checkout equal `origin/develop` or `origin/main` (`--plan-only` warns instead, to preview a pull request), and there is no override: an urgent change goes through a merge to `develop` first.

### A new account, in order

1. **CDK bootstrap** (`cdk bootstrap`) creates the assets bucket `cdk-hnb659fds-assets-<account>-<region>`. The pipeline uploads templates and zips there. The first `papyrus-monitoring` is created with that bucket by name when the stack does not exist yet; afterwards the live stack's `CodeBucket` is used.
2. **The one-time approver setup**, above (`bootstrap.sh --approver-only`, then `create-environment.sh`). It also creates the GitHub OIDC provider with `--create-oidc-provider` if the account has none (`aws iam list-open-id-connect-providers` shows it). Provider facts, checked against the AWS CloudFormation reference and GitHub's guide to OIDC with AWS: URL `https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com`, and no thumbprint (optional for this property; IAM verifies GitHub's certificate against its own trusted CAs).
3. **A public hosted zone** for each `hostedZone` lookup in `stacks.json` (today `anth.us` for the operators stack's sending domain). Without it the operators stack stops with "expected exactly one public hosted zone". A different account needs its own domain in `stacks.json` (a pull request).
4. **SES.** The operators stack creates the sending identity; an account new to SES starts in the sandbox, and moving out is a request to AWS that a person makes.
5. **Plan and approve, then merge and release.** The first `role-stack-deploy` run (after merging, or `workflow_dispatch` from `develop`) creates the pipeline roles once a person approves. The release then creates `papyrus-newsletter-sending-operators`, then `papyrus-monitoring`. Every parameter without a default is supplied by `stacks.json` or the build. This first-create path (bucket by name, `CREATE` change set) is covered by unit tests against a fake CloudFormation; it has not been rehearsed on a real empty account.

Not solved: nothing creates the CDK bootstrap or the hosted zone; both are account facts a person provides. The approver setup is also a person's step by design: the workflow cannot create the roles it runs as. Edge and per-site newsletter stacks are still outside the pipeline (see above). The procedure runner is inside it: its image is a build step (`kind: image`) and only the release changes its stack.

## The roles, in plain words

- `papyrus-stack-plan-github`: trusted only for `repo:AnthusAI/Papyrus:pull_request`; can describe the two stacks and the pipeline stack, read their templates and look up a hosted zone.
- `papyrus-stack-deploy-github`: trusted only for `repo:AnthusAI/Papyrus:ref:refs/heads/main`; can drive change sets on the two stacks (creating one only with the service role attached), pass that one role to CloudFormation, and read and write objects under `papyrus-monitoring/` in the CDK assets bucket. It has no permission to create a Lambda, role or table itself.
- `papyrus-stack-deploy-cloudformation`: the service role CloudFormation assumes; permissions by service, scoped to `papyrus-*` names. Residual risk: it can create roles named `papyrus-monitoring-*` or `papyrus-newsletter-sending-*` with any inline policy, so what a template grants is controlled by review of the pull request and its dry run, not by this role.
