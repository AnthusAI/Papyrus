import { defineFunction } from "@aws-amplify/backend";
import { Duration } from "aws-cdk-lib";
import { Architecture, Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const functionDirectory = path.dirname(fileURLToPath(import.meta.url));

export const homePageTrigger = defineFunction(
  (scope: Construct) =>
    new Function(scope, "papyrus-home-page-trigger", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(30),
      memorySize: 256,
      code: Code.fromAsset(functionDirectory, { exclude: ["*.ts", "__pycache__", "*.pyc", "*_test.py"] }),
    }),
  { resourceGroupName: "data" },
);
