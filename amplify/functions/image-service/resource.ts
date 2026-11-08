import { defineFunction } from "@aws-amplify/backend";
import { Duration } from "aws-cdk-lib";
import { Architecture, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";
import { pythonLambdaCode } from "../shared/python-bundle";

/** AppSync gives a resolver 30 seconds; a profile read or save is a handful of small index reads and one write. */
export const IMAGE_SERVICE_TIMEOUT_SECONDS = 25;

/** stdlib plus the runtime's boto3 and PyYAML-free code: the bundle is `papyrus_content` and nothing else. */
export const imageService = defineFunction(
  (scope: Construct) =>
    new Function(scope, "papyrus-image-service", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(IMAGE_SERVICE_TIMEOUT_SECONDS),
      memorySize: 256,
      code: pythonLambdaCode(
        { functionDir: "image-service", modules: ["papyrus_content"], noDeps: true },
        [
          "bash",
          "-c",
          [
            "set -euo pipefail",
            "mkdir -p /asset-output/papyrus_content",
            "cp amplify/functions/image-service/handler.py /asset-output/handler.py",
            "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
          ].join(" && "),
        ],
      ),
    }),
  { resourceGroupName: "data" },
);
