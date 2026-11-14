import { Stack } from "aws-cdk-lib";
import { CfnRole } from "aws-cdk-lib/aws-iam";
import type { IConstruct } from "constructs";
import { appendInlinePolicy, appendInlinePolicyToRawRole, findAllOfType, findResourcesOfCfnType } from "./inline-policy";
import { SHARED_DENY_POLICY_NAME, sharedStackDenyPolicyDocument } from "./names";

/**
 * The deny that closes the reverse direction of the isolation (docs/plans/multi-tenant-architecture.md, layer 3): a dedicated
 * site's roles may not touch anything of the shared tier. Added as an inline policy, so no template gains a resource.
 *
 * `skip` names the stacks left alone. A dedicated backend with many models would pass CloudFormation's 2,500-resource limit
 * if one change touched every per-model nested stack (Papyrus 5.99.0 rolled back that way, amplify/cost-tag-waves.ts), and a
 * per-model data stack's roles can reach only their own table. Returns the number of roles that got the deny.
 */
export function addSharedStackDeny(scope: IConstruct, skip: (stack: Stack) => boolean = () => false): number {
  const document = sharedStackDenyPolicyDocument();
  const roles = findAllOfType(scope, CfnRole).filter((role) => !skip(Stack.of(role)));
  for (const role of roles) appendInlinePolicy(role, SHARED_DENY_POLICY_NAME, document);
  // CDK writes the role of a custom resource provider as a raw resource, not a CfnRole.
  const rawRoles = findResourcesOfCfnType(scope, "AWS::IAM::Role").filter((role) => !(role instanceof CfnRole) && !skip(Stack.of(role)));
  for (const role of rawRoles) appendInlinePolicyToRawRole(role, SHARED_DENY_POLICY_NAME, document);
  return roles.length + rawRoles.length;
}

/** True for the nested stack of one data model (`data/PapyrusCmsApi/<Model>`), where the transformer puts the model's table role. */
export function isModelDataStack(stack: Stack, modelNames: ReadonlySet<string>): boolean {
  return stack.node.scope?.node.id === "PapyrusCmsApi" && modelNames.has(stack.node.id);
}
