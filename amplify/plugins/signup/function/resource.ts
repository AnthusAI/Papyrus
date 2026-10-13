import { defineFunction } from "@aws-amplify/backend";
import { Duration, RemovalPolicy } from "aws-cdk-lib";
import { AttributeType, BillingMode, Table } from "aws-cdk-lib/aws-dynamodb";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Architecture, Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const functionDirectory = path.dirname(fileURLToPath(import.meta.url));

export const signupSubmit = defineFunction(
  (scope: Construct) => {
    const rateTable = new Table(scope, "PapyrusSignupRateCounters", {
      partitionKey: { name: "pk", type: AttributeType.STRING },
      billingMode: BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "expiresAt",
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const lambda = new Function(scope, "papyrus-signup-submit", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(10),
      memorySize: 256,
      code: Code.fromAsset(functionDirectory, { exclude: ["*.ts", "__pycache__", "*.pyc"] }),
      environment: { PAPYRUS_SIGNUP_RATE_TABLE: rateTable.tableName },
    });
    lambda.addToRolePolicy(
      new PolicyStatement({ effect: Effect.ALLOW, actions: ["dynamodb:UpdateItem"], resources: [rateTable.tableArn] }),
    );
    return lambda;
  },
  { resourceGroupName: "data" },
);
