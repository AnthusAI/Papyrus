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
const projectRoot = path.resolve(dirname, "../../..");

function copyCheckoutCorpora(outputDir: string): void {
  const corporaDir = path.join(outputDir, "corpora");
  fs.mkdirSync(corporaDir, { recursive: true });
  for (const entry of fs.readdirSync(path.join(projectRoot, "corpora"))) {
    if (!entry.endsWith(".yml")) continue;
    fs.copyFileSync(path.join(projectRoot, "corpora", entry), path.join(corporaDir, entry));
  }
  installPythonRequirements(outputDir);
}

function installPythonRequirements(outputDir: string): void {
  const requirementsPath = path.join(
    projectRoot,
    "amplify/functions/email-submission-processor/requirements.txt",
  );
  execSync(`python3 -m pip install -r "${requirementsPath}" -t "${outputDir}" --no-cache-dir`, {
    cwd: projectRoot,
    stdio: "inherit",
  });
}

export const emailSubmissionProcessor = defineFunction(
  (scope: Construct) => {
    return new Function(scope, "papyrus-email-submission-processor", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.minutes(5),
      memorySize: 1024,
      code: pythonLambdaCode(
        {
          functionDir: "email-submission-processor",
          modules: ["papyrus_newsroom", "papyrus_content", "papyrus_knowledge_query"],
          requirements: ["PyYAML>=6.0.2,<7", "requests>=2.32.3,<3", "boto3>=1.34.0,<2.0.0"],
          corpora: true,
          checkoutExtras: copyCheckoutCorpora,
        },
        [
          "bash",
          "-c",
          [
            "set -euo pipefail",
            "mkdir -p /asset-output/papyrus_newsroom /asset-output/papyrus_content /asset-output/papyrus_knowledge_query /asset-output/corpora",
            "cp amplify/functions/email-submission-processor/handler.py /asset-output/handler.py",
            "cp -R src/papyrus_newsroom/. /asset-output/papyrus_newsroom/",
            "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
            "cp -R src/papyrus_knowledge_query/. /asset-output/papyrus_knowledge_query/",
            "cp corpora/*.yml /asset-output/corpora/",
            "python3 -m pip install -r amplify/functions/email-submission-processor/requirements.txt -t /asset-output --no-cache-dir",
          ].join(" && "),
        ],
      ),
    });
  },
  { resourceGroupName: "data" },
);
