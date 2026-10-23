import { defineFunction } from "@aws-amplify/backend";
import { Duration } from "aws-cdk-lib";
import { Architecture, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";
import { pythonLambdaCode } from "../shared/python-bundle";

/** AppSync gives a resolver 30 seconds; a table read and ten run lookups need a few. */
export const AUTOMATION_VIEW_TIMEOUT_SECONDS = 25;

/** stdlib plus the runtime's boto3: the bundle is `papyrus_content` and nothing else. */
export const automationView = defineFunction(
  (scope: Construct) =>
    new Function(scope, "papyrus-automation-view", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(AUTOMATION_VIEW_TIMEOUT_SECONDS),
      memorySize: 256,
      code: pythonLambdaCode(
        { functionDir: "automation-view", modules: ["papyrus_content"], noDeps: true },
        [
          "bash",
          "-c",
          [
            "set -euo pipefail",
            "mkdir -p /asset-output/papyrus_content",
            "cp amplify/functions/automation-view/handler.py /asset-output/handler.py",
            "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
          ].join(" && "),
        ],
      ),
    }),
  { resourceGroupName: "data" },
);
