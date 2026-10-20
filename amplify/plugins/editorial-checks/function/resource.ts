import { defineFunction } from "@aws-amplify/backend";
import { Duration } from "aws-cdk-lib";
import { Architecture, Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const functionDirectory = path.dirname(fileURLToPath(import.meta.url));
const requirementsPath = path.join(functionDirectory, "requirements.txt");

/** AppSync gives a resolver 30 seconds; Limatus's classifier deadline (settings, default 20 s) keeps a check inside this. */
export const EDITORIAL_CHECKS_TIMEOUT_SECONDS = 28;

export const editorialChecks = defineFunction(
  (scope: Construct) =>
    new Function(scope, "papyrus-editorial-checks", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: "handler.handler",
      timeout: Duration.seconds(EDITORIAL_CHECKS_TIMEOUT_SECONDS),
      memorySize: 1024,
      code: Code.fromAsset(functionDirectory, {
        bundling: {
          image: Runtime.PYTHON_3_12.bundlingImage,
          command: [
            "bash",
            "-c",
            "pip install -r requirements.txt -t /asset-output --no-cache-dir && cp handler.py /asset-output/handler.py",
          ],
          local: {
            tryBundle(outputDir: string) {
              execFileSync(
                "python3",
                [
                  "-m", "pip", "install", "-r", requirementsPath, "-t", outputDir, "--no-cache-dir",
                  "--platform", "manylinux2014_aarch64", "--implementation", "cp", "--python-version", "3.12",
                  "--only-binary=:all:", "--ignore-requires-python",
                ],
                { stdio: "inherit" },
              );
              fs.copyFileSync(path.join(functionDirectory, "handler.py"), path.join(outputDir, "handler.py"));
              return true;
            },
          },
        },
      }),
    }),
  { resourceGroupName: "data" },
);
