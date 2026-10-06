import { defineFunction } from "@aws-amplify/backend";
import { Duration } from "aws-cdk-lib";
import { Architecture, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";
import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pythonLambdaCode } from "../shared/python-bundle";

const dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(dirname, "../../..");

export const contentActionsRequirements = ["PyYAML>=6.0.2,<7", "citeproc-py>=0.8.2,<1", "anthus-markus==0.5.1", "Pillow>=10,<12"];

function installCheckoutRequirements(outputDir: string): void {
  const requirementsPath = path.join(projectRoot, "amplify/functions/content-actions/requirements.txt");
  execSync(
    `python3 -m pip install -r "${requirementsPath}" -t "${outputDir}" --no-cache-dir --platform manylinux2014_aarch64 --implementation cp --python-version 3.12 --only-binary=:all: --ignore-requires-python`,
    { cwd: projectRoot, stdio: "inherit" },
  );
}

export const contentActions = defineFunction(
  (scope: Construct) => {
    return new Function(scope, "papyrus-content-actions", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(60),
      memorySize: 1024,
      code: pythonLambdaCode(
        {
          functionDir: "content-actions",
          modules: ["papyrus_content"],
          requirements: contentActionsRequirements,
          noDeps: true,
          checkoutExtras: installCheckoutRequirements,
        },
        [
          "bash",
          "-c",
          [
            "set -euo pipefail",
            "mkdir -p /asset-output/papyrus_content",
            "cp amplify/functions/content-actions/handler.py /asset-output/handler.py",
            "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
            "python3 -m pip install -r amplify/functions/content-actions/requirements.txt -t /asset-output --no-cache-dir",
          ].join(" && "),
        ],
      ),
    });
  },
  { resourceGroupName: "data" },
);
