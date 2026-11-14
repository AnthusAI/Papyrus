import { defineFunction } from "@aws-amplify/backend";
import { Duration } from "aws-cdk-lib";
import { Architecture, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";
import { pythonLambdaCode } from "../shared/python-bundle";

/** AppSync gives a resolver 30 seconds. A refresh waits for another refresh's lease for at most that long. */
export const ANNOUNCEMENTS_TIMEOUT_SECONDS = 28;

/** stdlib plus the runtime's boto3: the bundle is `papyrus_content` and nothing else. */
export const announcements = defineFunction(
  (scope: Construct) =>
    new Function(scope, "papyrus-announcements", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(ANNOUNCEMENTS_TIMEOUT_SECONDS),
      memorySize: 256,
      code: pythonLambdaCode(
        { functionDir: "announcements", modules: ["papyrus_content"], noDeps: true },
        [
          "bash",
          "-c",
          [
            "set -euo pipefail",
            "mkdir -p /asset-output/papyrus_content",
            "cp amplify/functions/announcements/handler.py /asset-output/handler.py",
            "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
          ].join(" && "),
        ],
      ),
    }),
  { resourceGroupName: "data" },
);
