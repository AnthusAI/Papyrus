import { Duration, Size } from "aws-cdk-lib";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Architecture, type Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import type { Construct } from "constructs";
import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pythonLambdaCode, type SiteBundleFile } from "../functions/shared/python-bundle";
import {
  RENDITIONS_EPHEMERAL_STORAGE_MB,
  RENDITIONS_MEDIA_PREFIX,
  RENDITIONS_MEMORY_MB,
  RENDITIONS_TIMEOUT_SECONDS,
  renditionsEnvironment,
  renditionsEventPattern,
} from "./renditions-settings";

const dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(dirname, "../..");

export const renditionsRequirements = ["PyYAML>=6.0.2,<7", "citeproc-py>=0.8.2,<1", "anthus-markus==0.7.0", "Pillow>=11.3,<12"];

export type RenditionsFunctionProps = {
  siteBucket: s3.IBucket;
  mediaBucket: s3.IBucket;
  siteFiles: SiteBundleFile[];
  code?: Code;
};

export type RenditionsFunction = {
  function: LambdaFunction;
  rule: events.Rule;
  deadLetterQueue: sqs.Queue;
};

function installCheckoutRequirements(outputDir: string): void {
  const requirementsPath = path.join(projectRoot, "amplify/functions/renditions/requirements.txt");
  execSync(
    `python3 -m pip install -r "${requirementsPath}" -t "${outputDir}" --no-cache-dir --platform manylinux2014_aarch64 --implementation cp --python-version 3.12 --only-binary=:all: --ignore-requires-python`,
    { cwd: projectRoot, stdio: "inherit" },
  );
}

export function addRenditionsFunction(scope: Construct, props: RenditionsFunctionProps): RenditionsFunction {
  const deadLetterQueue = new sqs.Queue(scope, "RenditionsDeadLetterQueue", {
    encryption: sqs.QueueEncryption.SQS_MANAGED,
    retentionPeriod: Duration.days(14),
    enforceSSL: true,
  });
  const renditions = new LambdaFunction(scope, "RenditionsFunction", {
    runtime: Runtime.PYTHON_3_12,
    architecture: Architecture.ARM_64,
    handler: "handler.handler",
    timeout: Duration.seconds(RENDITIONS_TIMEOUT_SECONDS),
    memorySize: RENDITIONS_MEMORY_MB,
    ephemeralStorageSize: Size.mebibytes(RENDITIONS_EPHEMERAL_STORAGE_MB),
    retryAttempts: 2,
    deadLetterQueue,
    environment: renditionsEnvironment(props.siteBucket.bucketName),
    code: props.code ?? pythonLambdaCode(
      {
        functionDir: "renditions",
        modules: ["papyrus_content"],
        requirements: renditionsRequirements,
        noDeps: true,
        checkoutExtras: installCheckoutRequirements,
        siteFiles: props.siteFiles,
      },
      [
        "bash",
        "-c",
        [
          "set -euo pipefail",
          "mkdir -p /asset-output/papyrus_content",
          "cp amplify/functions/renditions/handler.py /asset-output/handler.py",
          "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
          "python3 -m pip install -r amplify/functions/renditions/requirements.txt -t /asset-output --no-cache-dir",
        ].join(" && "),
      ],
    ),
  });
  renditions.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["s3:GetObject"],
      resources: [props.mediaBucket.arnForObjects(`${RENDITIONS_MEDIA_PREFIX}*`)],
    }),
  );
  renditions.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["s3:PutObject", "s3:GetObject"],
      resources: [props.siteBucket.arnForObjects("*")],
    }),
  );
  renditions.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["s3:ListBucket"],
      resources: [props.siteBucket.bucketArn],
    }),
  );
  const rule = new events.Rule(scope, "MediaObjectCreatedRule", {
    eventPattern: renditionsEventPattern(props.mediaBucket.bucketName),
  });
  rule.addTarget(new targets.LambdaFunction(renditions, { retryAttempts: 2 }));
  return { function: renditions, rule, deadLetterQueue };
}
