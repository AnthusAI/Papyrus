# Shared stacks deploy from the release (PPY-b8cc79)

`papyrus-monitoring` and `papyrus-newsletter-sending-operators` are deployed by `.github/workflows/stack-deploy.yml`. Nobody creates or executes a change set for them by hand.

| File | What it is |
| --- | --- |
| `stacks.json` | The stacks, in deploy order: template, the paths that are their inputs, parameters, zone lookups, which `build.py` zips feed which code-key parameter, capabilities. |
| `allowed-changes.json` | The Removes and Replaces a release may make on purpose, each with its reason. Empty it again once they have deployed. |
| `stack_deploy.py` | The whole deploy, with its safety checks. Tested by `procedures/newsroom/tests/test_stack_deploy.py`. |
| `papyrus-stack-pipeline.yaml` | The three IAM roles (and, only when asked, the account's GitHub OIDC provider). The only hand-applied stack. |
| `bootstrap.sh` | The one command that applies it: [Required: the role bootstrap](#required-the-role-bootstrap-a-person-runs-it). |

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

## What does not fit

- `papyrus-procedure-runner` takes `ImageUri`, a container image built and pushed elsewhere. The shape (zip builds that feed content-hash keys) does not apply, so it is not in `stacks.json`. It would fit once the image build is a pipeline step.
- Edge stacks and per-site newsletter stacks are not in scope. The same file could carry them.
- `papyrus-monitoring`'s `CodeBucket` is read from the live stack, and the template bucket for every stack comes from there. On a new account, before that stack exists, the CDK bootstrap bucket name is used (see "A new account, in order").

## Required: the role bootstrap (a person runs it)

The release deploys through three IAM roles. They are created by one CloudFormation stack, `papyrus-stack-pipeline` (`papyrus-stack-pipeline.yaml`), which a **person** applies, on purpose. A pipeline must not be able to raise its own permissions, so the release never touches this stack. Without it, `stack-deploy` cannot find a role to assume and nothing deploys.

**Run it when:** (1) you set up a new AWS account, and (2) after **any** change to `infra/pipeline/papyrus-stack-pipeline.yaml`, including a merged pull request that adds a permission. A release that needs a permission the account's roles lack fails with a "not authorized" error; the job summary then names this command.

**Who:** a person with credentials that can create IAM roles in the account (an administrator login). Agents do not run it unless the person tells them to; an agent that needs it asks, with the command below.

```bash
export AWS_PROFILE=<profile for the account>      # log in first, for example aws sso login
infra/pipeline/bootstrap.sh --account <12-digit account id>
```

On an account with no GitHub OIDC provider yet, add `--create-oidc-provider`. Other flags: `--plan-only` (show the change set, apply nothing), `--yes` (do not ask before applying), `--repo OWNER/REPO` (default `AnthusAI/Papyrus`).

What it does, and says as it goes: checks the credentials belong to the account you named (the id is never stored in Git); checks the OIDC provider; creates a change set for `papyrus-stack-pipeline` and shows it; asks you to type `yes`; applies it; sets the `AWS_ACCOUNT_ID` repository variable (the roles' account, kept out of Git); then verifies the three roles exist and the deployed template equals the file in the repository. Run it again whenever you like: with nothing to change it says "no changes" and touches nothing.

**How the release tells you it is out of date.** The pull-request dry run and the release's deploy both compare the template in the repository with the deployed `papyrus-stack-pipeline` stack. If they differ, the job summary has a heading "The pipeline roles are out of date" and a warning annotation, with the command above. This is a notice, never a failure of the release. If the deployed plan or deploy role cannot yet read that stack (roles from before this check), the notice says so; that also means the roles need this one run. A change to the template puts both stacks in scope on purpose, so the release runs this check.

### A new account, in order

1. **CDK bootstrap** (`cdk bootstrap`) creates the assets bucket `cdk-hnb659fds-assets-<account>-<region>`. The pipeline uploads templates and zips there. The first `papyrus-monitoring` is created with that bucket by name when the stack does not exist yet; afterwards the live stack's `CodeBucket` is used.
2. **This role bootstrap**, above. It also creates the GitHub OIDC provider with `--create-oidc-provider` if the account has none (`aws iam list-open-id-connect-providers` shows it). Provider facts, checked against the AWS CloudFormation reference and GitHub's guide to OIDC with AWS: URL `https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com`, and no thumbprint (optional for this property; IAM verifies GitHub's certificate against its own trusted CAs).
3. **A public hosted zone** for each `hostedZone` lookup in `stacks.json` (today `anth.us` for the operators stack's sending domain). Without it the operators stack stops with "expected exactly one public hosted zone". A different account needs its own domain in `stacks.json` (a pull request).
4. **SES.** The operators stack creates the sending identity; an account new to SES starts in the sandbox, and moving out is a request to AWS that a person makes.
5. **Merge and release.** The release creates `papyrus-newsletter-sending-operators`, then `papyrus-monitoring`. Every parameter without a default is supplied by `stacks.json` or the build. This first-create path (bucket by name, `CREATE` change set) is covered by unit tests against a fake CloudFormation; it has not been rehearsed on a real empty account.

Not solved: nothing in `stacks.json` creates the CDK bootstrap or the hosted zone; both are account facts a person provides. Also, `papyrus-procedure-runner`, edge and per-site newsletter stacks are still outside the pipeline (see above).

## The roles, in plain words

- `papyrus-stack-plan-github`: trusted only for `repo:AnthusAI/Papyrus:pull_request`; can describe the two stacks and the pipeline stack, read their templates and look up a hosted zone.
- `papyrus-stack-deploy-github`: trusted only for `repo:AnthusAI/Papyrus:ref:refs/heads/main`; can drive change sets on the two stacks (creating one only with the service role attached), pass that one role to CloudFormation, and read and write objects under `papyrus-monitoring/` in the CDK assets bucket. It has no permission to create a Lambda, role or table itself.
- `papyrus-stack-deploy-cloudformation`: the service role CloudFormation assumes; permissions by service, scoped to `papyrus-*` names. Residual risk: it can create roles named `papyrus-monitoring-*` or `papyrus-newsletter-sending-*` with any inline policy, so what a template grants is controlled by review of the pull request and its dry run, not by this role.
