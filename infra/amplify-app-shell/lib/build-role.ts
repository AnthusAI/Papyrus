import { ArnFormat, Stack } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import type { AmplifyAppShellSiteConfig, BuildRoleKind } from "./site-config";
import { DEFAULT_BUILD_ROLE_KIND } from "./site-config";

/**
 * What the Amplify build of a site's CMS app runs as (features/build-role-scope.feature).
 *
 * `administrator` is the role every site has had: the AWS-managed AdministratorAccess policy. `scoped` replaces it with AWS's own
 * AmplifyBackendDeployFullAccess (what `ampx pipeline-deploy` needs), the explicit grants the build commands in build-specs.ts use, and an explicit
 * deny on the pipeline's own roles and stacks, so a bad build cannot rewrite the deploy roles or reach another tenant's shared-tier resources.
 *
 * Plainly, what scoping does not do: the backend deploy and `papyrus-infra deploy` go through the account's CDK bootstrap roles, and the
 * CloudFormation execution role there decides what a deployed template may create. Narrowing that role is separate account work.
 */
export const SCOPED_BUILD_ROLE_MANAGED_POLICY_NAME = "AmplifyBackendDeployFullAccess";
export const SCOPED_BUILD_ROLE_GRANTS_POLICY_ID = "ScopedBuildRoleGrants";
export const PIPELINE_ROLE_NAME_PREFIXES = ["papyrus-pipeline-", "papyrus-stack-", "papyrus-shared-"];
export const PIPELINE_STACK_NAMES = ["papyrus-stack-pipeline", "papyrus-pipeline-approver"];

export function resolveBuildRoleKind(cms: { buildRole?: BuildRoleKind }): BuildRoleKind {
  return cms.buildRole ?? DEFAULT_BUILD_ROLE_KIND;
}

export function buildRoleManagedPolicies(kind: BuildRoleKind): iam.IManagedPolicy[] {
  return [iam.ManagedPolicy.fromAwsManagedPolicyName(kind === "scoped" ? SCOPED_BUILD_ROLE_MANAGED_POLICY_NAME : "AdministratorAccess")];
}

export function buildRoleDescription(appName: string, kind: BuildRoleKind): string {
  return kind === "scoped"
    ? `Backend deploy and staging build service role for Amplify app ${appName} (scoped: ${SCOPED_BUILD_ROLE_MANAGED_POLICY_NAME} plus this site's grants)`
    : `Backend deploy and staging build service role for Amplify app ${appName} (AdministratorAccess: documented risk)`;
}

export function scopedBuildRoleStatements(stack: Stack, config: AmplifyAppShellSiteConfig): iam.PolicyStatement[] {
  const { partition, region, account } = stack;
  const brandId = config.brand.toLowerCase();
  const arn = (service: string, resource: string, resourceName: string, arnFormat: ArnFormat) => stack.formatArn({ service, resource, resourceName, arnFormat });
  const roleArn = (name: string) => `arn:${partition}:iam::${account}:role/${name}`;
  return [
    new iam.PolicyStatement({
      sid: "ReadThisSitesParameters",
      actions: ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
      resources: [`arn:${partition}:ssm:${region}:${account}:parameter/papyrus/${config.siteId}/*`],
    }),
    new iam.PolicyStatement({
      sid: "WakeQueueAddress",
      actions: ["sqs:GetQueueUrl"],
      resources: [`arn:${partition}:sqs:${region}:${account}:papyrus-${brandId}-agent-wakes.fifo`],
    }),
    new iam.PolicyStatement({ sid: "ListSchedules", actions: ["scheduler:ListSchedules"], resources: ["*"] }),
    new iam.PolicyStatement({
      sid: "SiteScheduleGroupEntries",
      actions: ["scheduler:GetSchedule", "scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule"],
      resources: [arn("scheduler", "schedule", `papyrus-${brandId}-agent-schedules/*`, ArnFormat.SLASH_RESOURCE_NAME)],
    }),
    new iam.PolicyStatement({
      sid: "PassTheSchedulerRoleToTheSchedulerOnly",
      actions: ["iam:PassRole"],
      resources: [roleArn(`papyrus-${brandId}-agent-scheduler`)],
      conditions: { StringEquals: { "iam:PassedToService": "scheduler.amazonaws.com" } },
    }),
    new iam.PolicyStatement({
      sid: "DenyChangesToThePipelinesOwnRoles",
      effect: iam.Effect.DENY,
      actions: ["iam:*", "sts:AssumeRole"],
      resources: PIPELINE_ROLE_NAME_PREFIXES.map((prefix) => roleArn(`${prefix}*`)),
    }),
    new iam.PolicyStatement({
      sid: "DenyChangesToThePipelinesOwnStacks",
      effect: iam.Effect.DENY,
      actions: ["cloudformation:*"],
      resources: PIPELINE_STACK_NAMES.map((name) => `arn:${partition}:cloudformation:${region}:${account}:stack/${name}/*`),
    }),
  ];
}
