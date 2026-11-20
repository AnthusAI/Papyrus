import { Stack } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { MONITORING_TABLE_PARAMETER, monitoringViewParameterArn, monitoringViewTableArns } from "../monitoring-view/wire";

/**
 * The X spend counter is in the shared monitoring table under `SPEND#<tenant>#x:<account>#<cycle start>` (src/papyrus_content/spend_ledger.py), the one place the
 * procedure runner can also reach. A function that reads or adds to it names the table through the parameter the monitoring stack writes, and its role may touch
 * only this site's X rows: the leading key must start with `SPEND#<tenant>#x:`. A site with no tenant on its build (`PAPYRUS_TENANT_ID`) gets neither the variable nor the
 * grant, and the function answers that the counter needs one.
 */
export const SPEND_LEDGER_ACTIONS = ["dynamodb:GetItem", "dynamodb:UpdateItem"];

export const spendLeadingKeys = (tenantId: string) => [`SPEND#${tenantId}#x:*`];

export function wireSpendLedger(lambda: LambdaFunction, tenantId: string | undefined = process.env.PAPYRUS_TENANT_ID): void {
  const tenant = (tenantId ?? "").trim();
  if (!tenant) return;
  const stack = Stack.of(lambda);
  lambda.addEnvironment("PAPYRUS_TENANT_ID", tenant);
  lambda.addEnvironment("PAPYRUS_MONITORING_TABLE_PARAMETER", MONITORING_TABLE_PARAMETER);
  lambda.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["ssm:GetParameter"], resources: [monitoringViewParameterArn(stack.region, stack.account)] }));
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: SPEND_LEDGER_ACTIONS,
      resources: monitoringViewTableArns(stack.region, stack.account).slice(0, 1),
      conditions: { "ForAllValues:StringLike": { "dynamodb:LeadingKeys": spendLeadingKeys(tenant) } },
    }),
  );
}
