import { Effect, Policy, PolicyStatement, type IRole } from "aws-cdk-lib/aws-iam";
import type { Construct } from "constructs";

/**
 * The signed-in admin's read of the agent policy document (PPY-51ea61; docs/release-5-130-plan.md, 1.5).
 *
 * The policy is `tenants/<tenant>/site/agents/<version>.json` in the site's media bucket. The signed-in admin only reads it; every change goes through the agent-policy
 * function (amplify/functions/agent-policy), which refuses a credential that is not a person's. The admin once held the put as well, through the same credentials
 * an agent working in the person's session holds, so the server could not tell the two apart. Amplify's `defineStorage` rules take a prefix that
 * ends in `/*`, and this key has a wildcard in the middle, so a storage rule cannot say it; the grant is an inline policy on the `admin` group's role.
 *
 * It sits in its own stack, not on the role in the auth stack: the storage stack already depends on the group roles (its own rules attach to them), so a
 * statement on the role that names the bucket would make the two depend on each other. Get on that prefix only,
 * no list, and the `editor` and `curator` groups and the plain authenticated role get nothing (the CLI refuses an editor, but the role is the control).
 */
export const ADMIN_AGENT_POLICY_GRANT_STACK_NAME = "admin-agent-policy-grant";
export const ADMIN_AGENT_POLICY_GRANT_SID = "AdminReadAgentPolicyBody";
export const ADMIN_AGENT_POLICY_GROUP = "admin";
export const ADMIN_AGENT_POLICY_KEY_PATTERN = "tenants/*/site/agents/*";

export function adminAgentPolicyStatement(mediaBucketArn: string): PolicyStatement {
  return new PolicyStatement({
    sid: ADMIN_AGENT_POLICY_GRANT_SID,
    effect: Effect.ALLOW,
    actions: ["s3:GetObject"],
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
