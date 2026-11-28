# Proposal: how the release creates the shared Amplify Gen 2 backend (PPY-daf673)

Status: proposal, for Ryan's decision. Nothing here is built.

## The problem

The shared foundation stacks are single CloudFormation templates, which `infra/pipeline/stack_deploy.py` deploys through a checked change set. The shared **backend** is an Amplify Gen 2 app: a CDK app of nested stacks, with Lambda and asset bundles and generated resource names. `stack_deploy.py` deploys one template at a time, uploads no assets, and the shared service role (`papyrus-shared-deploy-cloudformation`) is scoped by name prefixes that generated names do not match. So the release cannot create the backend today.

## Options

**A. An Amplify Hosting app for the shared backend, deployed by `ampx pipeline-deploy` inside Amplify, like every site.** Same path the dedicated sites use; nothing new to build in the pipeline. But the deploy runs under Amplify's service role, outside the change-set check and `allowed-changes.json`, and it needs a branch that builds, which a backend with no front end does not naturally have.

**B. Teach the pipeline to deploy a synthesized CDK app.** The release runs `ampx` synthesis (`scripts/synth-backend-with-options.mts` already does it for tests), publishes the assets with a CDK-style publisher under the `papyrus-shared-*` template prefix, then creates one change set per nested stack on the root (`papyrus-shared-<tier>-backend`) with nested change sets on, and runs the existing check over every nested change set. The service role is widened by tag (`aws:RequestTag/anthus:deployment` = shared-*) and by a `papyrus-shared-<tier>-` name prefix forced through the CDK stack name, not by a wildcard. Keeps one deploy path, one checker, one approval model. Costs a real build: asset publishing, nested-stack change sets, and the service-role rights for AppSync, DynamoDB, Cognito, Lambda and S3.

**C. `cdk deploy` (or `ampx deploy`) from a GitHub job with a CDK bootstrap role.** Fastest to build. But the bootstrap execution role is broad (AdministratorAccess by default), and it bypasses the change-set check, which the hard rules and AGENTS.md rely on.

## Recommendation

**B.** It is the only option that keeps the shared tier under the same checked change-set path, scoped roles and `allowed-changes.json` as every other pipeline stack, which is the point of the shared tier being in the release at all. A is a fallback if B's service-role rights cannot be scoped tightly enough. Reject C.

Slices for B: (1) synthesize in CI and print the nested-stack resource list on pull requests (read-only); (2) asset publishing to the shared prefix; (3) nested change sets plus the check over each; (4) the service-role rights, listed by fingerprint like any role change; (5) first create, held in `stacks.json` like the foundation stacks.
