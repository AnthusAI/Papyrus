# Shared stacks deploy from the release (PPY-b8cc79)

`papyrus-monitoring` and `papyrus-newsletter-sending-operators` are deployed by `.github/workflows/stack-deploy.yml`. Nobody creates or executes a change set for them by hand.

| File | What it is |
| --- | --- |
| `stacks.json` | The stacks, in deploy order: template, the paths that are their inputs, parameters, zone lookups, which `build.py` zips feed which code-key parameter, capabilities. |
| `allowed-changes.json` | The Removes and Replaces a release may make on purpose, each with its reason. Empty it again once they have deployed. |
| `stack_deploy.py` | The whole deploy, with its safety checks. Tested by `procedures/newsroom/tests/test_stack_deploy.py`. |
| `papyrus-stack-pipeline.yaml` | The three IAM roles. The only hand-deployed stack. |

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
- `papyrus-monitoring` itself must already exist: its `CodeBucket` is read from the live stack, and the template bucket for every stack comes from there.

## The one hand-run step, once

Needs credentials that can create IAM roles in the production account (Ryan's SSO admin).

```bash
export AWS_PROFILE=papyrus-production AWS_REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)   # must be the production account in AGENTS.md
aws cloudformation deploy \
  --template-file infra/pipeline/papyrus-stack-pipeline.yaml \
  --stack-name papyrus-stack-pipeline \
  --capabilities CAPABILITY_NAMED_IAM
gh variable set AWS_ACCOUNT_ID --repo AnthusAI/Papyrus --body "$ACCOUNT"
```

The second command is configuration, not infrastructure: a repository variable, so the account id stays out of Git. After this, every shared-stack change goes by pull request and release. Changing the roles themselves (the template in this directory) is deliberately not done by the pipeline: a deploy role that rewrites its own permissions is an escalation path, so that is the same single command again.

## The roles, in plain words

- `papyrus-stack-plan-github`: trusted only for `repo:AnthusAI/Papyrus:pull_request`; can describe the two stacks, read their templates and look up a hosted zone.
- `papyrus-stack-deploy-github`: trusted only for `repo:AnthusAI/Papyrus:ref:refs/heads/main`; can drive change sets on the two stacks (creating one only with the service role attached), pass that one role to CloudFormation, and read and write objects under `papyrus-monitoring/` in the CDK assets bucket. It has no permission to create a Lambda, role or table itself.
- `papyrus-stack-deploy-cloudformation`: the service role CloudFormation assumes; permissions by service, scoped to `papyrus-*` names. Residual risk: it can create roles named `papyrus-monitoring-*` or `papyrus-newsletter-sending-*` with any inline policy, so what a template grants is controlled by review of the pull request and its dry run, not by this role.
