import { Stack } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { IFunction } from "aws-cdk-lib/aws-lambda";

/** The shared lock table's name (created by the cloud knowledge run stack). The Lambda finds it through this SSM parameter. */
export const PROJECTION_LOCK_TABLE_PARAMETER = "/papyrus/projection-lock/table-name";
export const PROJECTION_LOCK_TABLE_NAME = "papyrus-projection-locks";
export const PROJECTION_LOCK_TABLE_ACTIONS = ["dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:UpdateItem", "dynamodb:GetItem"];

export function projectionLeaseParameterArn(region: string, account: string): string {
  return `arn:aws:ssm:${region}:${account}:parameter${PROJECTION_LOCK_TABLE_PARAMETER}`;
}

export function projectionLeaseTableArn(region: string, account: string): string {
  return `arn:aws:dynamodb:${region}:${account}:table/${PROJECTION_LOCK_TABLE_NAME}*`;
}

/**
 * Let a projecting Lambda take and release the per-publication projection lease: read the table-name
 * parameter and write items in the lock table, nothing broader. The table itself is not created here;
 * a deployment without it keeps projecting without a lease.
 */
export function addProjectionLeaseAccess(lambda: IFunction): void {
  const stack = Stack.of(lambda);
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["ssm:GetParameter"],
      resources: [projectionLeaseParameterArn(stack.region, stack.account)],
    }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: PROJECTION_LOCK_TABLE_ACTIONS,
      resources: [projectionLeaseTableArn(stack.region, stack.account)],
    }),
  );
}
