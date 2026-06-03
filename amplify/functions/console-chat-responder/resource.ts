import { Duration, NestedStack, Stack, type NestedStackProps } from "aws-cdk-lib";
import { Platform } from "aws-cdk-lib/aws-ecr-assets";
import { Repository } from "aws-cdk-lib/aws-ecr";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Architecture, CfnEventSourceMapping, DockerImageCode, DockerImageFunction } from "aws-cdk-lib/aws-lambda";
import type { ITable } from "aws-cdk-lib/aws-dynamodb";
import { Construct } from "constructs";

export type ConsoleChatResponderStackProps = NestedStackProps & {
  messageTable: ITable;
  messageStreamArn: string;
  threadTable: ITable;
  projectRoot: string;
  graphqlEndpoint: string;
  amplifySsmEnvConfig?: string;
  responseTarget?: string;
  model?: string;
  prebuiltImageUri?: string;
};

export class ConsoleChatResponderStack extends NestedStack {
  public readonly responderFunction: DockerImageFunction;

  constructor(scope: Construct, id: string, props: ConsoleChatResponderStackProps) {
    super(scope, id, props);

    const responseTarget = props.responseTarget?.trim() || "cloud";
    const environment: Record<string, string> = {
      PAPYRUS_MESSAGE_TABLE_NAME: props.messageTable.tableName,
      PAPYRUS_MESSAGE_THREAD_TABLE_NAME: props.threadTable.tableName,
      PAPYRUS_MESSAGE_THREAD_SEQUENCE_INDEX_NAME: "messagesByThreadSequence",
      PAPYRUS_GRAPHQL_ENDPOINT: props.graphqlEndpoint,
      PAPYRUS_CONSOLE_RESPONSE_TARGET: responseTarget,
      PAPYRUS_CONSOLE_MODEL: props.model?.trim() || process.env.PAPYRUS_CONSOLE_MODEL || "gpt-5-nano",
      PAPYRUS_CONSOLE_CONTEXT_CACHE_ROOT: "/tmp/papyrus-console/thread-context",
      PAPYRUS_CONSOLE_STATIC_CONTEXT_TTL_SECONDS: process.env.PAPYRUS_CONSOLE_STATIC_CONTEXT_TTL_SECONDS || "900",
      PAPYRUS_EXECUTE_TACTUS_RUNNER: process.env.PAPYRUS_EXECUTE_TACTUS_RUNNER || "/opt/papyrus/execute_tactus_runner.py",
      PAPYRUS_EXECUTE_TACTUS_TIMEOUT_SECONDS: process.env.PAPYRUS_EXECUTE_TACTUS_TIMEOUT_SECONDS || "30",
      PAPYRUS_JWT_ISSUER: process.env.PAPYRUS_JWT_ISSUER || "papyrus-cli",
      PAPYRUS_JWT_SUBJECT: process.env.PAPYRUS_JWT_SUBJECT || "papyrus-cli",
      PAPYRUS_JWT_AUDIENCE: process.env.PAPYRUS_JWT_AUDIENCE || "papyrus-authoring",
      PAPYRUS_JWT_GROUPS: process.env.PAPYRUS_JWT_GROUPS || "editor",
      ...(props.amplifySsmEnvConfig ? { AMPLIFY_SSM_ENV_CONFIG: props.amplifySsmEnvConfig } : {}),
    };

    const imageUri = props.prebuiltImageUri?.trim() || process.env.PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI?.trim() || "";
    const allowLocalImageBuild = parseBooleanEnv(process.env.PAPYRUS_CONSOLE_RESPONDER_ALLOW_LOCAL_BUILD);
    let code: DockerImageCode;
    if (imageUri) {
      const { repositoryName, tagOrDigest } = parseEcrImageUri(imageUri);
      assertArm64ImageUri(imageUri, tagOrDigest);
      const repository = Repository.fromRepositoryName(this, "ConsoleChatResponderRepository", repositoryName);
      code = DockerImageCode.fromEcr(repository, { tagOrDigest });
    } else {
      if (!allowLocalImageBuild) {
        throw new Error(
          "ConsoleChatResponder requires PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI (prebuilt ECR image). "
          + "Set PAPYRUS_CONSOLE_RESPONDER_ALLOW_LOCAL_BUILD=true only when intentionally using local Docker image builds.",
        );
      }
      code = DockerImageCode.fromImageAsset(props.projectRoot, {
        file: "amplify/functions/console-chat-responder/Dockerfile",
        platform: Platform.LINUX_ARM64,
        exclude: [
          ".git",
          ".env",
          ".env.*",
          ".next",
          ".amplify",
          "node_modules",
          "coverage",
          "dist",
          "out",
          "corpora",
          ".papyrus-runs",
          "amplify_outputs.json",
          "amplify_outputs.json.*",
          "amplify/functions/console-chat-responder/target",
        ],
      });
    }

    this.responderFunction = new DockerImageFunction(this, "ConsoleChatResponderFunction", {
      code,
      architecture: Architecture.ARM_64,
      timeout: Duration.minutes(2),
      memorySize: 1024,
      environment,
      description: "Rust responder for Papyrus editor console chat Message stream",
    });

    new CfnEventSourceMapping(this, "ConsoleResponderMessageStreamMapping", {
      batchSize: 1,
      eventSourceArn: props.messageStreamArn,
      functionName: this.responderFunction.functionArn,
      functionResponseTypes: ["ReportBatchItemFailures"],
      maximumRetryAttempts: 2,
      startingPosition: "LATEST",
    });

    props.messageTable.grantReadWriteData(this.responderFunction);
    props.threadTable.grantReadWriteData(this.responderFunction);
    this.responderFunction.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["dynamodb:Query"],
      resources: [
        `${props.messageTable.tableArn}/index/*`,
        `${props.threadTable.tableArn}/index/*`,
      ],
    }));
    const stack = Stack.of(this);
    // execute_tactus_runner mints PAPYRUS_GRAPHQL_JWT via boto3 get_parameters; branch policies
    // often grant GetParameters on path prefixes, not GetParameter per secret name.
    this.responderFunction.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["ssm:GetParameter", "ssm:GetParameters"],
      resources: [
        `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/papyrus/*`,
        `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/papyrus/*`,
        `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/*`,
        `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/dbsyytcm9drqa/*`,
        `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/dbsyytcm9drqa/*`,
      ],
    }));
    this.responderFunction.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["appsync:GraphQL"],
      resources: ["*"],
    }));
    this.responderFunction.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: [
        "dynamodb:DescribeStream",
        "dynamodb:GetRecords",
        "dynamodb:GetShardIterator",
        "dynamodb:ListStreams",
      ],
      resources: [props.messageStreamArn],
    }));
  }
}

function parseBooleanEnv(value: string | undefined): boolean {
  if (!value) return false;
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

function parseEcrImageUri(imageUri: string): { repositoryName: string; tagOrDigest: string } {
  const trimmed = imageUri.trim();
  const hostAndPath = trimmed.split("/");
  if (hostAndPath.length < 2) {
    throw new Error(`Invalid PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI: ${trimmed}`);
  }
  const imagePath = hostAndPath.slice(1).join("/");
  if (imagePath.includes("@sha256:")) {
    const [repositoryName, digest] = imagePath.split("@", 2);
    if (!repositoryName || !digest) {
      throw new Error(`Invalid PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI digest form: ${trimmed}`);
    }
    return { repositoryName, tagOrDigest: digest };
  }
  const colonIndex = imagePath.lastIndexOf(":");
  if (colonIndex <= 0 || colonIndex === imagePath.length - 1) {
    throw new Error(`PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI must include a tag (repo:tag) or digest: ${trimmed}`);
  }
  return {
    repositoryName: imagePath.slice(0, colonIndex),
    tagOrDigest: imagePath.slice(colonIndex + 1),
  };
}

function assertArm64ImageUri(imageUri: string, tagOrDigest: string): void {
  const normalized = `${imageUri} ${tagOrDigest}`.toLowerCase();
  if (normalized.includes("amd64") || normalized.includes("x86_64")) {
    throw new Error(
      `PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI must reference an ARM64 image, but received: ${imageUri}`,
    );
  }
}
