import { Aspects, CfnResource, Lazy, Stack, Token, type IAspect } from "aws-cdk-lib";
import { CfnRole } from "aws-cdk-lib/aws-iam";
import type { IConstruct } from "constructs";

/**
 * The deny every dedicated site's role carries on the shared tier's resources (PPY-daf673; docs/shared-stack.md; the design note's
 * "Isolation inside an existing account", layer 3). This package ships on its own, so it keeps a copy of
 * `amplify/shared-stack/names.ts`; scripts/test-shared-stack.ts fails when the two statements differ.
 *
 * An inline policy is added to each role, so the stack gains no resource.
 */
export const SHARED_DENY_POLICY_NAME = "papyrus-deny-shared-stack";
const SHARED_FAMILY_PREFIX = "papyrus-shared-";
const SHARED_DEPLOYMENT_VALUES = ["shared-prod", "shared-staging"];

export function sharedStackDenyStatements() {
  return [
    {
      Sid: "DenyTaggedSharedStackResources",
      Effect: "Deny",
      Action: ["*"],
      Resource: ["*"],
      Condition: { StringEquals: { "aws:ResourceTag/anthus:deployment": [...SHARED_DEPLOYMENT_VALUES] } },
    },
    {
      Sid: "DenyNamedSharedStackResources",
      Effect: "Deny",
      Action: ["*"],
      Resource: [
        `arn:aws:cloudformation:*:*:stack/${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:s3:::${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:s3:::${SHARED_FAMILY_PREFIX}*/*`,
        `arn:aws:lambda:*:*:function:${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:logs:*:*:log-group:/aws/lambda/${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:logs:*:*:log-group:/aws/lambda/${SHARED_FAMILY_PREFIX}*:*`,
        `arn:aws:iam::*:role/${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:iam::*:policy/${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:ssm:*:*:parameter/papyrus/shared/*`,
        `arn:aws:sns:*:*:${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:sqs:*:*:${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:cloudwatch:*:*:alarm:${SHARED_FAMILY_PREFIX}*`,
        `arn:aws:kms:*:*:alias/${SHARED_FAMILY_PREFIX}*`,
      ],
    },
    {
      Sid: "DenySharedStackKeys",
      Effect: "Deny",
      Action: ["kms:*"],
      Resource: ["*"],
      Condition: { "ForAnyValue:StringLike": { "kms:ResourceAliases": `alias/${SHARED_FAMILY_PREFIX}*` } },
    },
  ];
}

export const sharedStackDenyPolicyDocument = () => ({ Version: "2012-10-17", Statement: sharedStackDenyStatements() });

class SharedStackDeny implements IAspect {
  visit(node: IConstruct): void {
    if (!CfnResource.isCfnResource(node) || node.cfnResourceType !== "AWS::IAM::Role") return;
    if (node instanceof CfnRole) {
      const existing = node.policies;
      if (existing !== undefined && (Token.isUnresolved(existing) || !Array.isArray(existing))) {
        throw new Error(`Cannot add the ${SHARED_DENY_POLICY_NAME} policy to role ${node.node.path}: its Policies is not a plain list.`);
      }
      node.policies = [...(existing ?? []), { policyName: SHARED_DENY_POLICY_NAME, policyDocument: sharedStackDenyPolicyDocument() }];
      return;
    }
    // A raw role (a custom resource provider's): extend its list when the template is written.
    const previous = (node as unknown as { cfnProperties: Record<string, unknown> }).cfnProperties.Policies;
    node.addPropertyOverride(
      "Policies",
      Lazy.any({
        produce: () => {
          const resolved = Stack.of(node).resolve(previous) ?? [];
          if (!Array.isArray(resolved)) throw new Error(`Cannot add the ${SHARED_DENY_POLICY_NAME} policy to role ${node.node.path}: its Policies is not a list.`);
          return [...resolved, { PolicyName: SHARED_DENY_POLICY_NAME, PolicyDocument: sharedStackDenyPolicyDocument() }];
        },
      }),
    );
  }
}

/** Adds the deny to every role of `stack`, unless `enabled` is false (only the synth test that proves the deny is the whole difference passes false). */
export function addSharedStackDeny(stack: Stack, enabled = true): void {
  if (enabled) Aspects.of(stack).add(new SharedStackDeny());
}
