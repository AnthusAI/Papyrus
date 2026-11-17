/**
 * Locks the signed-in admin's grant on the agent policy document (amplify/agents/admin-policy-grant.ts; docs/release-5-130-plan.md, 1.5):
 * put and get on `tenants/*\/site/agents/*` in the media bucket, on the admin group's role only, in a stack of its own.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { AccountRootPrincipal, Role } from "aws-cdk-lib/aws-iam";
import { addAdminAgentPolicyGrant, ADMIN_AGENT_POLICY_GRANT_SID } from "../amplify/agents/admin-policy-grant";

const BUCKET_ARN = "arn:aws:s3:::example-media-bucket";
const app = new App();
const authStack = new Stack(app, "auth");
const adminRole = new Role(authStack, "AdminRole", { assumedBy: new AccountRootPrincipal() });
new Role(authStack, "EditorRole", { assumedBy: new AccountRootPrincipal() });
const grantStack = new Stack(app, "grant");
addAdminAgentPolicyGrant(grantStack, adminRole, BUCKET_ARN);

const grant = Template.fromStack(grantStack);
grant.resourceCountIs("AWS::IAM::Policy", 1);
const [policy] = Object.values(grant.findResources("AWS::IAM::Policy"));
assert.deepEqual(
  policy.Properties.PolicyDocument.Statement,
  [
    {
      Sid: ADMIN_AGENT_POLICY_GRANT_SID,
      Effect: "Allow",
      Action: ["s3:GetObject", "s3:PutObject"],
      Resource: `${BUCKET_ARN}/tenants/*/site/agents/*`,
    },
  ],
  "exactly one statement: get and put on the agent policy prefix, no delete, no list, nothing else",
);
assert.equal(policy.Properties.Roles.length, 1, "attached to one role");
const attached = JSON.stringify(policy.Properties.Roles);
assert.ok(attached.includes("AdminRole"), "attached to the admin role");
assert.ok(!attached.includes("EditorRole"), "the editor role does not carry it");

// Wired for the admin group only, in its own stack, and not for a shared stack.
const wiring = readFileSync(path.resolve(__dirname, "../amplify/site-backend.ts"), "utf8");
assert.match(wiring, /ADMIN_AGENT_POLICY_GROUP\]\.role/, "the grant takes the admin group's role");
assert.match(wiring, /backend\.createStack\(ADMIN_AGENT_POLICY_GRANT_STACK_NAME\)/, "in a stack of its own, so the storage and auth stacks do not depend on each other");
assert.match(wiring, /if \(tenancyMode !== "shared"\) \{\n\s+addAdminAgentPolicyGrant/, "a dedicated site only");
const storage = readFileSync(path.resolve(__dirname, "../amplify/storage/resource.ts"), "utf8");
assert.ok(!/agents/.test(storage), "the storage rules do not carry the agent policy prefix");
console.log("admin agent policy grant: ok");
