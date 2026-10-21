import { RemovalPolicy, Stack } from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { type Function as LambdaFunction, FunctionUrlAuthType } from "aws-cdk-lib/aws-lambda";

export const PUBLIC_FORMS_OUTPUT_KEY = "publicForms";

export type PublicFormsWiring = {
  allowedOrigins: string[];
  honeypotFields?: string[];
};

/**
 * Wires the endpoint: the rate-limit counter table (TTL), the Function URL and the function's settings, and returns
 * the URL for the `custom.publicForms.endpoint` output. Everything lives in the function's own stack.
 */
export function wirePublicForms(backend: { publicForms: { resources: { lambda: unknown }; addEnvironment: (name: string, value: string) => void } }, wiring: PublicFormsWiring): string {
  const lambda = backend.publicForms.resources.lambda as LambdaFunction;
  const stack = Stack.of(lambda);
  const table = new dynamodb.Table(stack, "PublicFormsLimits", {
    partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
    billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
    timeToLiveAttribute: "expiresAt",
    removalPolicy: RemovalPolicy.DESTROY,
  });
  lambda.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["dynamodb:UpdateItem"], resources: [table.tableArn] }));
  backend.publicForms.addEnvironment("PAPYRUS_PUBLIC_FORMS_TABLE", table.tableName);
  backend.publicForms.addEnvironment("PAPYRUS_PUBLIC_FORMS_ORIGINS", wiring.allowedOrigins.join(","));
  backend.publicForms.addEnvironment("PAPYRUS_PUBLIC_FORMS_HONEYPOTS", (wiring.honeypotFields ?? []).join(","));
  // CORS is answered by the handler (it must echo exactly one allowed origin), so the URL carries no CORS block.
  return lambda.addFunctionUrl({ authType: FunctionUrlAuthType.NONE }).url;
}
