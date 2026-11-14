import { CfnResource, Lazy, Stack, Token } from "aws-cdk-lib";
import { CfnRole } from "aws-cdk-lib/aws-iam";
import type { IConstruct } from "constructs";

/** Every L1 resource of a type under `scope`, in construct-tree order. */
export function findAllOfType<T extends IConstruct>(scope: IConstruct, type: abstract new (...args: never[]) => T): T[] {
  return scope.node.findAll().filter((node): node is T => node instanceof type);
}

/**
 * Adds one inline policy to a role without adding a resource: `Policies` gains an entry, so the template holds exactly the
 * resources it held before. Refuses a role whose `Policies` is not a plain list (a token cannot be extended safely).
 */
export function appendInlinePolicy(role: CfnRole, policyName: string, policyDocument: object): void {
  const existing = role.policies;
  if (existing !== undefined && (Token.isUnresolved(existing) || !Array.isArray(existing))) {
    throw new Error(`Cannot add the ${policyName} policy to role ${role.node.path}: its Policies is not a plain list.`);
  }
  if (existing?.some((entry) => !Token.isUnresolved(entry) && (entry as { policyName?: string }).policyName === policyName)) {
    throw new Error(`Role ${role.node.path} already has a ${policyName} policy.`);
  }
  role.policies = [...(existing ?? []), { policyName, policyDocument }];
}

/** Every resource of a CloudFormation type under `scope`, including the raw `CfnResource`s CDK writes for its own providers. */
export function findResourcesOfCfnType(scope: IConstruct, cfnType: string): CfnResource[] {
  return scope.node.findAll().filter((node): node is CfnResource => CfnResource.isCfnResource(node) && node.cfnResourceType === cfnType);
}

/** Like `appendInlinePolicy`, for a raw `CfnResource` of type AWS::IAM::Role (a custom resource provider's role). */
export function appendInlinePolicyToRawRole(role: CfnResource, policyName: string, policyDocument: object): void {
  const previous = (role as unknown as { cfnProperties: Record<string, unknown> }).cfnProperties.Policies;
  // A provider's own statements arrive lazily, so the list is read when the template is written.
  role.addPropertyOverride(
    "Policies",
    Lazy.any({
      produce: () => {
        const resolved = Stack.of(role).resolve(previous) ?? [];
        if (!Array.isArray(resolved)) throw new Error(`Cannot add the ${policyName} policy to role ${role.node.path}: its Policies is not a list.`);
        return [...resolved, { PolicyName: policyName, PolicyDocument: policyDocument }];
      },
    }),
  );
}

/**
 * The functions CDK and Amplify write for their own plumbing (custom resource providers, the branch linker, the secret fetcher, the
 * table manager, log retention, bucket deployment). They run at deploy time only; every other function is a shared function that
 * gets reserved concurrency.
 */
export const INFRASTRUCTURE_FUNCTION_ID = /^(AWS[0-9a-f]{32}|framework-.*|LogRetention.*|Custom.*|BucketNotificationsHandler.*|Provider.*|Amplify(BranchLinker|SecretFetcher).*|TableManager.*)$/;

/** The construct id that names a function's owner: the L2 `Function`'s id, a provider's id for the raw function it writes, else the resource's own id. */
export function functionOwnerId(fn: CfnResource): string {
  return fn.node.id === "Resource" || fn.node.id === "Handler" ? (fn.node.scope?.node.id ?? fn.node.id) : fn.node.id;
}

export function isInfrastructureFunction(fn: CfnResource): boolean {
  return INFRASTRUCTURE_FUNCTION_ID.test(functionOwnerId(fn));
}

/** True for the construct id of a function CDK or Amplify writes for its own plumbing (see INFRASTRUCTURE_FUNCTION_ID). */
export function isInfrastructureConstructId(id: string): boolean {
  return INFRASTRUCTURE_FUNCTION_ID.test(id);
}
