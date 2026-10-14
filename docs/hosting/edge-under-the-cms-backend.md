# Edge stacks under the CMS backend (PPY-ddbaeb)

Status: design only. Nothing in this document has been executed. Every CloudFormation change set below needs Ryan's approval before it is created against production.

## Goal

Each site's CloudFront edge (`papyrus-edge-<site>`) was a hand-run CloudFormation stack at cutover. The goal is that one CMS Amplify app owns everything a site needs, so that merging to `main` deploys the edge together with the backend, with no personal AWS credentials, no downtime, no replaced distribution, no alias change and no certificate change (and no Amplify domain re-association, which is throttled).

## What exists for Anth.us (read-only inspection, papyrus-production, 2026-10-14)

| Stack | Resources | Notes |
| --- | --- | --- |
| `papyrus-edge-anth-us` | distribution `E3UMOOJRMY7FK7` (aliases `anth.us`, `www.anth.us`, ACM certificate parameter), OAC `EIPFJM917AYHO`, CloudFront functions `papyrus-edge-anth-us-viewer-request` and `-viewer-response` | Template identical to `infra/edge/anth-us-s3.yaml` in this repo. CloudFormation drift detection: IN_SYNC for all four resources. Cache policy `658327ea-f89d-4fab-a63d-7e88639e58f6` (CachingOptimized), HTTP/2 and 3, IPv6, price class all. |
| `papyrus-edge-anth-us-cms` | newsroom main and staging distributions, forward-host function | Fronts the CMS Amplify app. |
| `papyrus-edge-anth-us-preview` | a second reader-shaped distribution on the same bucket, no aliases | It has no aliases, so it serves no public host. Its purpose is not documented; decide separately whether to delete it. |

The site bucket and its bucket policy (`aws:SourceArn` equal to the distribution) are already created by the site backend (`publication.edgeDistributionArn`). The redirects key-value store is created by the site backend and passed to the edge stack as a parameter. The other sites follow the same shape (Pilobol.us adds a reader distribution that uses the backend's redirect function; p.apyr.us and Threat Intelligence front Amplify apps).

## Why this is not just "set `distribution.create: true`"

The generic `createDistribution` in `amplify/publication/s3-projection.ts` builds a different distribution from the live one: the generic redirect function instead of the Anth.us viewer-request function (pattern redirects, static-hosting rules), no viewer-response function (cache-control and content-type rewriting that keeps the previous host's headers), a CDK-chosen cache policy and OAC name, and a new logical identity. Pointing the aliases at it is a cutover (a new distribution), not an adoption. So the work has two parts: make the construct able to describe the live resources exactly, and move ownership of the live resources without replacing them.

## Plan A (recommended first): the CMS build deploys the edge stack, gated by its change set

No import, no new ownership model, no replacement. The template stays a CloudFormation file in the site repo (for Anth.us `infra/edge/anth-us-s3.template.yaml`, rendered by `bin/render_edge_template.py`), and the CMS build applies it.

1. Add an `edge` block to the app-shell site config: the stack name, the template path in the site repo and the parameter values. The app-shell template gives the CMS app's service role `cloudformation:CreateChangeSet`, `DescribeChangeSet`, `ExecuteChangeSet`, `DescribeStacks`, `GetTemplate` on `papyrus-edge-<site>*` only, and the CloudFront actions that stack's resources need (distribution, OAC, function and key-value-store reads), scoped to the resource ARNs.
2. After `ampx pipeline-deploy` the build runs `papyrus-app edge-deploy`, which creates a change set for the stack and reads it:
   * no changes: nothing to do, the build continues;
   * changes: the change set is left **unexecuted**, its name and a readable summary are printed in the build log, and the build fails. Ryan executes it (console or CLI) or approves it by setting the branch environment variable `PAPYRUS_EDGE_APPROVED_CHANGESET` to the change set name and rebuilding. Replacement of a distribution, a changed alias or a changed certificate is refused even when approved (the script exits before it will execute such a set).
3. Edge changes therefore always arrive as a PR that changes the template, deploy with the app, and still wait for a human yes. A merge that does not touch the edge is unaffected.

What it does not do: put the edge inside the CDK app. The edge stack stays a separate top-level stack, now deployed by the same pipeline.

## Plan B: the live resources become part of the backend's CDK app (resource import)

Use this only if single-CDK-app ownership is required. Hard requirement first, to settle in a spike on a throwaway distribution (stage S1 below): Amplify Gen 2 deploys the backend as nested stacks of the branch stack (`amplify-<appId>-<branch>-<hash>`). CloudFormation resource import is a change set on a stack; whether it can target an Amplify-managed nested stack directly has not been verified here and must not be assumed. If it cannot, Plan B degrades to a top-level stack that the app deploys, which is Plan A.

Stages, each a change set Ryan approves before it is created or executed:

* **S0, construct work (no AWS change).** Extend `publication.distribution` with an `adopt` form: `{ adopt: { aliases, certificateArn, viewerRequestFunctionFile, viewerResponseFunctionFile, cachePolicyId, comment } }`. The synthesized resources must have the same property values as the live ones so that the import change set shows `Import` and no property difference. A unit test compares the synthesized properties with the checked-in snapshot of the live configuration.
* **S1, spike.** Repeat the whole sequence on a throwaway site (`papyrus-mid-test*`, a one-origin distribution without aliases) to prove import into the target stack type, the `DeletionPolicy` handoff and the absence of any request error during the move.
* **Stage 1, retain.** Update `papyrus-edge-anth-us` with a template that is identical except for `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain` on the four resources. The exact diff is `infra/edge/migration/anth-us-stage1-retain.diff`. The change set contains no resource modification; it only records the policies.
* **Stage 2, release.** Delete `papyrus-edge-anth-us`. The four resources are retained and keep serving; no alias, certificate or origin changes. (The stack has no other resources; its parameters are only inputs.) Take a CloudFront configuration backup first (`aws cloudfront get-distribution-config --id E3UMOOJRMY7FK7`, `aws cloudfront get-function`) and keep it with the approval.
* **Stage 3, import.** Create a change set of type `IMPORT` on the target stack with `infra/edge/migration/anth-us-resources-to-import.json` as `--resources-to-import`. Read the change set: every row must be `Import`, none `Add`, `Modify` or `Remove`, and `Replacement` must be `False`. Execute it. Drift detection on the target stack must report IN_SYNC for the four resources.
* **Stage 4, normal deploys.** From then on the backend deploy updates the distribution as part of the app; an edge change is an ordinary change in the PR and the pipeline shows the diff. Approvals stay with the PR merge (Ryan's "merge #N") and with the change-set gate of Plan A if the team wants both.

Between stages 2 and 3 the live distribution is unowned by any stack but fully serving. If stage 3 fails, re-import it into a stack with the stage 1 template (same command, same JSON), which restores the previous ownership. Nothing in either direction touches a request path.

## Risks

* An import mismatch (a property that differs from live) is reported as drift on the first deploy after import and then reverted by CloudFormation on the next update, which for a distribution can mean a visible behavior change. The stage 3 change set must show no property difference, and the first post-import deploy must be a deliberate no-op.
* CloudFront functions are replaced when their name changes: the logical names and the `Name` expressions (`${AWS::StackName}-viewer-request`) must resolve to the existing names in the target stack, or the stack name must stay `papyrus-edge-anth-us`.
* The domain and certificate stay as they are. Never create or change an Amplify domain association, a hosted zone or a record from this work.
* Other sites differ (the `-cms` stacks and the p.apyr.us and Threat Intelligence stacks front Amplify apps through a forward-host function and have no site bucket); do Anth.us, then reuse the construct for Pilobol.us.

## Estimate

Plan A: about two days (app-shell permissions, `edge-deploy` script with change-set gate and refusal rules, tests, one rehearsal on a throwaway stack). Plan B adds S0 and S1: about four more days, with the nested-stack import question as the main unknown.
