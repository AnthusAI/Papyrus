import { defineFunction } from "@aws-amplify/backend";
import { Duration } from "aws-cdk-lib";
import { Architecture, Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const functionDirectory = path.dirname(fileURLToPath(import.meta.url));

/** stdlib plus the runtime's boto3: the asset is this directory's two Python files and nothing else. */
export const proposalActions = defineFunction(
  (scope: Construct) =>
    new Function(scope, "papyrus-proposal-actions", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(25),
      memorySize: 256,
      code: Code.fromAsset(functionDirectory, { exclude: ["*.ts", "__pycache__", "*.pyc"] }),
    }),
  { resourceGroupName: "data" },
);
