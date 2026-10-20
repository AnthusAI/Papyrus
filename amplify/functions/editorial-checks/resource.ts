import { defineFunction } from "@aws-amplify/backend";
import { Duration } from "aws-cdk-lib";
import { Architecture, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pythonLambdaCode } from "../shared/python-bundle";

const functionDirectory = path.dirname(fileURLToPath(import.meta.url));

/** AppSync gives a resolver 30 seconds; Limatus's classifier deadline (settings, default 20 s) keeps a check inside this. */
export const EDITORIAL_CHECKS_TIMEOUT_SECONDS = 28;

/** Limatus with the Jev classifier lane; papyrus_content.editorial_checks does the work. */
export const editorialChecksRequirements = ["limatus[jev]>=0.32,<0.33"];

function installRequirements(outputDir: string): void {
  execFileSync(
    "python3",
    [
      "-m", "pip", "install", "-r", path.join(functionDirectory, "requirements.txt"), "-t", outputDir, "--no-cache-dir",
      "--platform", "manylinux2014_aarch64", "--implementation", "cp", "--python-version", "3.12",
      "--only-binary=:all:", "--ignore-requires-python",
    ],
    { stdio: "inherit" },
  );
}

export const editorialChecks = defineFunction(
  (scope: Construct) =>
    new Function(scope, "papyrus-editorial-checks", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(EDITORIAL_CHECKS_TIMEOUT_SECONDS),
      memorySize: 1024,
      code: pythonLambdaCode(
        {
          functionDir: "editorial-checks",
          modules: ["papyrus_content"],
          requirements: editorialChecksRequirements,
          noDeps: true,
          checkoutExtras: installRequirements,
        },
        [
          "bash",
          "-c",
          [
            "set -euo pipefail",
            "mkdir -p /asset-output/papyrus_content",
            "cp amplify/functions/editorial-checks/handler.py /asset-output/handler.py",
            "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
            "python3 -m pip install -r amplify/functions/editorial-checks/requirements.txt -t /asset-output --no-cache-dir",
          ].join(" && "),
        ],
      ),
    }),
  { resourceGroupName: "data" },
);
