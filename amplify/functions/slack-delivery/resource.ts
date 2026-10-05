import { defineFunction } from "@aws-amplify/backend";
import { Duration } from "aws-cdk-lib";
import { Architecture, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pythonLambdaCode } from "../shared/python-bundle";

const dirname = path.dirname(fileURLToPath(import.meta.url));
// Repo root in a checkout, package root when installed from npm.
const projectRoot = path.resolve(dirname, "../../..");

export const slackDelivery = defineFunction(
  (scope: Construct) => {
    return new Function(scope, "papyrus-slack-delivery", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(60),
      memorySize: 512,
      code: pythonLambdaCode(
        {
          functionDir: "slack-delivery",
          modules: ["papyrus_newsroom", "papyrus_content"],
          requirements: ["PyYAML>=6.0.2,<7.0.0", "boto3>=1.34.0,<2.0.0"],
          checkoutExtras(outputDir) {
            execSync(
              `python3 -m pip install -r "${path.join(dirname, "requirements.txt")}" -t "${outputDir}" --no-cache-dir`,
              { cwd: projectRoot, stdio: "inherit" },
            );
          },
        },
        [
          "bash",
          "-c",
          [
            "set -euo pipefail",
            "mkdir -p /asset-output/papyrus_newsroom /asset-output/papyrus_content",
            "cp amplify/functions/slack-delivery/handler.py /asset-output/handler.py",
            "cp -R src/papyrus_newsroom/. /asset-output/papyrus_newsroom/",
            "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
            "python3 -m pip install -r amplify/functions/slack-delivery/requirements.txt -t /asset-output --no-cache-dir",
          ].join(" && "),
        ],
      ),
    });
  },
  { resourceGroupName: "data" },
);
