async function main() {
const { createRequire } = require("node:module");
const path = require("node:path");
const fs = require("node:fs");
const papyrusRoot = path.resolve(__dirname, "../../..");
const dependencyRoot = process.env.PAPYRUS_CHAT_CANDIDATE_DEPS || papyrusRoot;
const requireDependencies = createRequire(path.resolve(dependencyRoot, "package.json"));
const mode = process.env.PAPYRUS_CHAT_CANDIDATE_MODE || "runtime";
const candidateConfiguration = JSON.parse(fs.readFileSync(path.join(papyrusRoot, "config/papyrus-chat-candidate.json"), "utf8"));
const modelKeyParameter = candidateConfiguration.modelKeyParameter;
if (!/^\/papyrus\/[a-z0-9-]+\/openai-api-key$/.test(modelKeyParameter)) {
  throw new Error("The private chat model key must use the site-scoped /papyrus/<site>/openai-api-key parameter path");
}
if (!["runtime", "synthetic"].includes(mode)) throw new Error("PAPYRUS_CHAT_CANDIDATE_MODE must be runtime or synthetic");
const esbuild = requireDependencies("esbuild");
const cdk = requireDependencies("aws-cdk-lib");
const dynamodb = requireDependencies("aws-cdk-lib/aws-dynamodb");
const iam = requireDependencies("aws-cdk-lib/aws-iam");
const lambda = requireDependencies("aws-cdk-lib/aws-lambda");
const eventSources = requireDependencies("aws-cdk-lib/aws-lambda-event-sources");
const logs = requireDependencies("aws-cdk-lib/aws-logs");
const s3 = requireDependencies("aws-cdk-lib/aws-s3");
const sqs = requireDependencies("aws-cdk-lib/aws-sqs");

const lambdaAssetDirectory = path.join("/tmp", mode === "runtime" ? "papyrus-chat-runtime-lambda" : "papyrus-chat-synthetic-lambda");
fs.rmSync(lambdaAssetDirectory, { recursive: true, force: true });
await esbuild.build({
  absWorkingDir: papyrusRoot,
  entryPoints: mode === "runtime"
    ? ["infra/shared-chat-runtime/lambda/run-worker.ts", "infra/shared-chat-runtime/lambda/probe-worker.ts"]
    : ["infra/shared-chat-runtime/lambda/synthetic-adapter-test.ts"],
  outdir: lambdaAssetDirectory,
  bundle: true,
  packages: "bundle",
  platform: "node",
  format: "cjs",
  target: "node22",
  alias: {
    "chatticus/chat-runtime": requireDependencies.resolve("chatticus/chat-runtime"),
  },
});
const expectedBundles = mode === "runtime" ? ["probe-worker.js", "run-worker.js"] : ["synthetic-adapter-test.js"];
const emittedBundles = fs.readdirSync(lambdaAssetDirectory).sort();
if (JSON.stringify(emittedBundles) !== JSON.stringify(expectedBundles)) {
  throw new Error(`Unexpected ${mode} Lambda asset files: ${emittedBundles.join(", ")}`);
}

class PapyrusChatDataCandidate extends cdk.Stack {
  constructor(scope, id, props) {
    const { syntheticMode, ...stackProps } = props;
    super(scope, id, stackProps);
    let gatewayRoleArn;
    let runWorkerFunction;
    let probeWorkerFunction;
    if (!syntheticMode) {
      gatewayRoleArn = new cdk.CfnParameter(this, "GatewayRoleArn", {
        type: "String",
        description: "Production candidate gateway role ARN. Do not use for synthetic adapter validation; synthetic mode creates its own isolated test role.",
        allowedPattern: "^arn:aws:iam::[0-9]{12}:role/.+$",
      });
    }
    const privateBotId = new cdk.CfnParameter(this, "PrivateAssistantBotId", {
      type: "String",
      description: "Stable Papyrus-owned assistant ID; stored per derived account tenant on first private-channel open.",
      allowedPattern: "^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$",
    });
    const privateBotName = new cdk.CfnParameter(this, "PrivateAssistantBotName", {
      type: "String",
      description: "Visible name for the private Papyrus assistant.",
      allowedPattern: "^[A-Za-z0-9][A-Za-z0-9 ._-]{1,63}$",
    });

    const messaging = new dynamodb.Table(this, "PrivateMessaging", {
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "expires_at",
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      deletionProtection: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const conversations = new dynamodb.Table(this, "PrivateConversationIndex", {
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      deletionProtection: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    for (const name of ["l1", "l2", "l3"]) {
      conversations.addLocalSecondaryIndex({
        indexName: `${name}-index`,
        sortKey: { name, type: dynamodb.AttributeType.STRING },
        projectionType: dynamodb.ProjectionType.ALL,
      });
    }

    const objects = new s3.Bucket(this, "PrivateSessionObjects", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
    });

    const runDlq = new sqs.Queue(this, "TurnRunDlq", {
      retentionPeriod: cdk.Duration.days(14),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
    });
    const probeDlq = new sqs.Queue(this, "TurnProbeDlq", {
      retentionPeriod: cdk.Duration.days(14),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
    });
    const runs = new sqs.Queue(this, "TurnRuns", {
      visibilityTimeout: cdk.Duration.seconds(1800),
      retentionPeriod: cdk.Duration.days(syntheticMode ? 14 : 4),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
      deadLetterQueue: { queue: runDlq, maxReceiveCount: 5 },
    });
    const probes = new sqs.Queue(this, "TurnProbes", {
      visibilityTimeout: cdk.Duration.minutes(2),
      retentionPeriod: cdk.Duration.days(syntheticMode ? 14 : 4),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
      deadLetterQueue: { queue: probeDlq, maxReceiveCount: 5 },
    });

    const gateway = syntheticMode
      ? new iam.Role(this, "SyntheticAdapterGatewayRole", {
        assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
        description: "Synthetic adapter test only; not trusted by Papyrus CMS and has no model-secret access.",
      })
      : iam.Role.fromRoleArn(this, "PapyrusChatGatewayRole", gatewayRoleArn.valueAsString, { mutable: true });
    gateway.addToPolicy(new iam.PolicyStatement({
      actions: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:TransactWriteItems", "dynamodb:Query", "dynamodb:BatchGetItem"],
      resources: [messaging.tableArn],
    }));
    gateway.addToPolicy(new iam.PolicyStatement({
      actions: ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem"],
      resources: [conversations.tableArn, `${conversations.tableArn}/index/*`],
    }));
    gateway.addToPolicy(new iam.PolicyStatement({
      actions: syntheticMode ? ["s3:GetObject", "s3:PutObject"] : ["s3:GetObject"],
      resources: [objects.arnForObjects(syntheticMode ? "conversations/synthetic-adapter-tests/*" : "conversations/*")],
    }));
    gateway.addToPolicy(new iam.PolicyStatement({ actions: ["sqs:SendMessage"], resources: [runs.queueArn, probes.queueArn] }));
    if (syntheticMode) {
      gateway.addToPolicy(new iam.PolicyStatement({
        actions: ["sqs:ReceiveMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"],
        resources: [runs.queueArn],
      }));
    }

    const hostedEnvironment = {
      PAPYRUS_CHAT_MESSAGING_TABLE: messaging.tableName,
      PAPYRUS_CHAT_CONVERSATIONS_TABLE: conversations.tableName,
      PAPYRUS_CHAT_SESSION_BUCKET: objects.bucketName,
      PAPYRUS_CHAT_TURN_RUNS_QUEUE_URL: runs.queueUrl,
      PAPYRUS_CHAT_TURN_PROBES_QUEUE_URL: probes.queueUrl,
      PAPYRUS_CHAT_PRIVATE_BOT_ID: privateBotId.valueAsString,
      PAPYRUS_CHAT_PRIVATE_BOT_NAME: privateBotName.valueAsString,
    };

    let syntheticHarnessFunction;
    if (!syntheticMode) {
    const runLogGroup = new logs.LogGroup(this, "RunWorkerLogs", {
      logGroupName: "/aws/lambda/papyrus-private-chat-run-worker",
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    const probeLogGroup = new logs.LogGroup(this, "ProbeWorkerLogs", {
      logGroupName: "/aws/lambda/papyrus-private-chat-probe-worker",
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const runWorker = new iam.Role(this, "RunWorkerRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      description: "Private Papyrus computerless chat run worker.",
    });
    runWorker.addToPolicy(new iam.PolicyStatement({
      actions: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:BatchGetItem", "dynamodb:TransactWriteItems"],
      resources: [messaging.tableArn, conversations.tableArn, `${conversations.tableArn}/index/*`],
    }));
    runWorker.addToPolicy(new iam.PolicyStatement({
      actions: ["ssm:GetParameter"],
      resources: [this.formatArn({ service: "ssm", resource: "parameter", resourceName: modelKeyParameter.slice(1), arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME })],
    }));
    runWorker.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
      resources: [`${runLogGroup.logGroupArn}:*`],
    }));
    runWorker.addToPolicy(new iam.PolicyStatement({
      actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      resources: [objects.arnForObjects("conversations/*")],
    }));
    runWorker.addToPolicy(new iam.PolicyStatement({
      actions: ["sqs:ChangeMessageVisibility", "sqs:SendMessage"],
      resources: [runs.queueArn, probes.queueArn],
    }));

    const probeWorker = new iam.Role(this, "ProbeWorkerRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      description: "Private Papyrus chat deadline/recovery worker.",
    });
    probeWorker.addToPolicy(new iam.PolicyStatement({
      actions: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:TransactWriteItems", "dynamodb:BatchGetItem"],
      resources: [messaging.tableArn],
    }));
    probeWorker.addToPolicy(new iam.PolicyStatement({
      actions: ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem"],
      resources: [conversations.tableArn, `${conversations.tableArn}/index/*`],
    }));
    probeWorker.addToPolicy(new iam.PolicyStatement({
      actions: ["s3:GetObject"],
      resources: [objects.arnForObjects("conversations/*")],
    }));
    probeWorker.addToPolicy(new iam.PolicyStatement({
      actions: ["sqs:SendMessage"],
      resources: [runs.queueArn, probes.queueArn],
    }));
    probeWorker.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
      resources: [`${probeLogGroup.logGroupArn}:*`],
    }));

    runWorkerFunction = new lambda.Function(this, "RunWorker", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "run-worker.handler",
      code: lambda.Code.fromAsset(lambdaAssetDirectory),
      role: runWorker,
      memorySize: 1024,
      timeout: cdk.Duration.seconds(900),
      logGroup: runLogGroup,
      environment: {
        ...hostedEnvironment,
        OPENAI_API_KEY_PARAMETER: modelKeyParameter,
      },
      description: "Runs Papyrus private chat turns with the computerless Chatticus execution profile.",
    });
    probeWorkerFunction = new lambda.Function(this, "ProbeWorker", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "probe-worker.handler",
      code: lambda.Code.fromAsset(lambdaAssetDirectory),
      role: probeWorker,
      memorySize: 512,
      timeout: cdk.Duration.seconds(60),
      logGroup: probeLogGroup,
      environment: hostedEnvironment,
      description: "Recovers and finalizes Papyrus private chat turns.",
    });
    runWorkerFunction.addEventSource(new eventSources.SqsEventSource(runs, { enabled: false, batchSize: 1 }));
    probeWorkerFunction.addEventSource(new eventSources.SqsEventSource(probes, { enabled: false, batchSize: 1 }));
    } else {
      const syntheticLogGroup = new logs.LogGroup(this, "SyntheticAdapterTestLogs", {
        logGroupName: "/aws/lambda/papyrus-chat-synthetic-adapter-test",
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.RETAIN,
      });
      gateway.addToPolicy(new iam.PolicyStatement({
        actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
        resources: [`${syntheticLogGroup.logGroupArn}:*`],
      }));
      syntheticHarnessFunction = new lambda.Function(this, "SyntheticAdapterTest", {
        runtime: lambda.Runtime.NODEJS_22_X,
        handler: "synthetic-adapter-test.handler",
        code: lambda.Code.fromAsset(lambdaAssetDirectory),
        role: gateway,
        memorySize: 512,
        timeout: cdk.Duration.seconds(60),
        logGroup: syntheticLogGroup,
        environment: hostedEnvironment,
        description: "Manually invoked synthetic-only adapter assertions; no model calls or production site access.",
      });
    }

    new cdk.CfnOutput(this, "MessagingTableName", { value: messaging.tableName });
    new cdk.CfnOutput(this, "ConversationIndexTableName", { value: conversations.tableName });
    new cdk.CfnOutput(this, "SessionBucketName", { value: objects.bucketName });
    new cdk.CfnOutput(this, "TurnRunsQueueUrl", { value: runs.queueUrl });
    new cdk.CfnOutput(this, "TurnProbesQueueUrl", { value: probes.queueUrl });
    new cdk.CfnOutput(this, "FeatureDefault", { value: "disabled; set PAPYRUS_PRIVATE_CHAT_ENABLED=true only after review" });
    new cdk.CfnOutput(this, "SyntheticAdapterTestOnly", { value: String(syntheticMode) });
    new cdk.CfnOutput(this, "GatewayMessagingTableEnvironmentName", { value: "PAPYRUS_CHAT_MESSAGING_TABLE" });
    new cdk.CfnOutput(this, "GatewayMessagingTableName", { value: messaging.tableName });
    new cdk.CfnOutput(this, "GatewayConversationTableEnvironmentName", { value: "PAPYRUS_CHAT_CONVERSATIONS_TABLE" });
    new cdk.CfnOutput(this, "GatewayConversationTableName", { value: conversations.tableName });
    new cdk.CfnOutput(this, "GatewaySessionBucketEnvironmentName", { value: "PAPYRUS_CHAT_SESSION_BUCKET" });
    new cdk.CfnOutput(this, "GatewaySessionBucketName", { value: objects.bucketName });
    new cdk.CfnOutput(this, "GatewayRunQueueEnvironmentName", { value: "PAPYRUS_CHAT_TURN_RUNS_QUEUE_URL" });
    new cdk.CfnOutput(this, "GatewayProbeQueueEnvironmentName", { value: "PAPYRUS_CHAT_TURN_PROBES_QUEUE_URL" });
    new cdk.CfnOutput(this, "GatewayPrivateBotIdEnvironmentName", { value: "PAPYRUS_CHAT_PRIVATE_BOT_ID" });
    new cdk.CfnOutput(this, "PrivateAssistantBotIdValue", { value: privateBotId.valueAsString });
    new cdk.CfnOutput(this, "GatewayPrivateBotNameEnvironmentName", { value: "PAPYRUS_CHAT_PRIVATE_BOT_NAME" });
    new cdk.CfnOutput(this, "PrivateAssistantBotNameValue", { value: privateBotName.valueAsString });
    if (syntheticMode) {
      new cdk.CfnOutput(this, "SyntheticAdapterRoleArn", { value: gateway.roleArn });
      new cdk.CfnOutput(this, "SyntheticAdapterTestFunctionName", { value: syntheticHarnessFunction.functionName });
      new cdk.CfnOutput(this, "SyntheticAdapterInvocation", { value: "Explicit Lambda Invoke only; no event source or schedule" });
    } else {
      new cdk.CfnOutput(this, "WorkerModelKeyParameterName", { value: modelKeyParameter });
      new cdk.CfnOutput(this, "RunWorkerFunctionName", { value: runWorkerFunction.functionName });
      new cdk.CfnOutput(this, "ProbeWorkerFunctionName", { value: probeWorkerFunction.functionName });
    }
  }
}

const app = new cdk.App();
const syntheticMode = mode === "synthetic";
const stackId = syntheticMode ? "PapyrusChatSyntheticAdapterTest" : "PapyrusChatDataCandidate";
const stack = new PapyrusChatDataCandidate(app, stackId, {
  description: syntheticMode
    ? "Synthetic-only Papyrus chat adapter test resources; no CMS role, worker, production gateway, or model secret access."
    : "Private Papyrus chat data plane; site entry and queue workers remain disabled until configured.",
  syntheticMode,
});
const assembly = app.synth();
const templateName = `${stack.stackName}.template.json`;
fs.copyFileSync(path.join(assembly.directory, templateName), path.join(__dirname, templateName));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
