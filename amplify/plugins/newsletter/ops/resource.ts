import { defineFunction } from "@aws-amplify/backend";
import { Duration } from "aws-cdk-lib";
import { Architecture, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";
import { pythonLambdaCode } from "../../../functions/shared/python-bundle";

/** AppSync gives a resolver 30 seconds; this function only forwards to `newsletter`, which answers in a few. */
export const NEWSLETTER_OPS_TIMEOUT_SECONDS = 25;

/**
 * The newsroom's newsletter operations enter here because an Amplify custom operation needs an Amplify-defined function and
 * the `newsletter` function itself lives in the plugin stack. It holds no data access: it may invoke that one function.
 */
export const newsletterOps = defineFunction(
  (scope: Construct) =>
    new Function(scope, "papyrus-newsletter-ops", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(NEWSLETTER_OPS_TIMEOUT_SECONDS),
      memorySize: 256,
      code: pythonLambdaCode(
        { functionDir: "../plugins/newsletter/ops", modules: ["papyrus_content"], noDeps: true },
        [
          "bash",
          "-c",
          [
            "set -euo pipefail",
            "mkdir -p /asset-output/papyrus_content",
            "cp amplify/plugins/newsletter/ops/handler.py /asset-output/handler.py",
            "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
          ].join(" && "),
        ],
      ),
    }),
  { resourceGroupName: "data" },
);
