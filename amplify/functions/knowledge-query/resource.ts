import { defineFunction } from "@aws-amplify/backend";
import { Duration } from "aws-cdk-lib";
import { Architecture, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isPackageMode, pythonLambdaCode } from "../shared/python-bundle";

const dirname = path.dirname(fileURLToPath(import.meta.url));
// Repo root in a checkout, package root when installed from npm.
const projectRoot = path.resolve(dirname, "../../..");

function storageBucketName(): string {
  if (process.env.PAPYRUS_STORAGE_BUCKET_NAME) return process.env.PAPYRUS_STORAGE_BUCKET_NAME;

  // Publication repo root (cwd) in package mode; repo root in a checkout.
  const outputsPath = path.join(isPackageMode() ? process.cwd() : projectRoot, "amplify_outputs.json");
  if (!fs.existsSync(outputsPath)) return "";

  try {
    const outputs = JSON.parse(fs.readFileSync(outputsPath, "utf8")) as {
      storage?: { bucket_name?: string };
    };
    return outputs.storage?.bucket_name ?? "";
  } catch {
    return "";
  }
}

export const knowledgeQuery = defineFunction(
  (scope: Construct) => {
    return new Function(scope, "papyrus-knowledge-query", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(300),
      memorySize: 512,
      environment: {
        PAPYRUS_STORAGE_BUCKET_NAME: storageBucketName(),
      },
      code: pythonLambdaCode(
        {
          functionDir: "knowledge-query",
          modules: ["papyrus_knowledge_query"],
        },
        [
          "bash",
          "-c",
          [
            "set -euo pipefail",
            "mkdir -p /asset-output/papyrus_knowledge_query",
            "cp amplify/functions/knowledge-query/handler.py /asset-output/handler.py",
            "cp -R src/papyrus_knowledge_query/. /asset-output/papyrus_knowledge_query/",
          ].join(" && "),
        ],
      ),
    });
  },
  { resourceGroupName: "data" },
);
