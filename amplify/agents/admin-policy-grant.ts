import { Effect, Policy, PolicyStatement, type IRole } from "aws-cdk-lib/aws-iam";
import type { Construct } from "constructs";

/**
 * The signed-in admin's one write on the agent policy document (PPY-51ea61; docs/release-5-130-plan.md, 1.5).
 *
 * `papyrus agents set-rung --apply` saves the next version of the policy as `tenants/<tenant>/site/agents/<version>.json` in the site's media bucket,
 * through the signed-in person's own credentials (the site store only puts and gets that object). Amplify's `defineStorage` rules take a prefix that
 * ends in `/*`, and this key has a wildcard in the middle, so a storage rule cannot say it; the grant is an inline policy on the `admin` group's role.
 *
 * It sits in its own stack, not on the role in the auth stack: the storage stack already depends on the group roles (its own rules attach to them), so a
 * statement on the role that names the bucket would make the two depend on each other. Put and get on that prefix only, no delete (every version stays),
 * no list, and the `editor` and `curator` groups and the plain authenticated role get nothing (the CLI refuses an editor, but the role is the control).
 */
export const ADMIN_AGENT_POLICY_GRANT_STACK_NAME = "admin-agent-policy-grant";
export const ADMIN_AGENT_POLICY_GRANT_SID = "AdminWriteAgentPolicyBody";
export const ADMIN_AGENT_POLICY_GROUP = "admin";
export const ADMIN_AGENT_POLICY_KEY_PATTERN = "tenants/*/site/agents/*";

export function adminAgentPolicyStatement(mediaBucketArn: string): PolicyStatement {
  return new PolicyStatement({
    sid: ADMIN_AGENT_POLICY_GRANT_SID,
    effect: Effect.ALLOW,
    actions: ["s3:GetObject", "s3:PutObject"],
    resources: [`${mediaBucketArn}/${ADMIN_AGENT_POLICY_KEY_PATTERN}`],
  });
}

/** Adds the grant to `adminRole` as a policy in `scope`'s stack. `scope` must be a stack of its own, apart from the auth and storage stacks. */
export function addAdminAgentPolicyGrant(scope: Construct, adminRole: IRole, mediaBucketArn: string): Policy {
  return new Policy(scope, "AdminAgentPolicyWrite", {
    roles: [adminRole],
    statements: [adminAgentPolicyStatement(mediaBucketArn)],
  });
}
