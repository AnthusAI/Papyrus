import { Construct } from "constructs";
import { Annotations, Arn, ArnFormat, Aws, CfnOutput, CfnParameter, Duration, Fn, RemovalPolicy, Stack, StackProps } from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as eventSources from "aws-cdk-lib/aws-lambda-event-sources";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import {
  AmplifyAppShellSiteConfig,
  CHAT_PRIVATE_ASSISTANT_ID,
  CHAT_PRIVATE_ASSISTANT_NAME,
  chatExportName,
  resolveChatLogGroupPrefix,
  resolveChatStackName,
} from "./site-config";

export type PapyrusChatStackProps = StackProps & {
  config: AmplifyAppShellSiteConfig;
  /** Directory holding the bundled `run-worker.js` and `probe-worker.js`. Not needed when `chat.workerCodeS3Key` pins the code. */
  lambdaAssetDirectory?: string;
};

/**
 * The private newsroom chat data plane of one publication: two DynamoDB tables, a private versioned S3 bucket, run
 * and probe queues with DLQs, and the two worker Lambdas with their event source mappings. The CMS compute role
 * receives the scoped gateway policy through the `GatewayRoleArn` parameter (the app shell's `CmsComputeRoleArn`
 * output), and the app shell reads the resource names back through this stack's exports.
 *
 * The resource definitions are the ones the p.apyr.us stack `PapyrusChatDataCandidate` was activated from
 * (infra/shared-chat-runtime/cdk/synth.cjs); logical ids and construct order are kept so that stack is adopted by an
 * in-place update (scripts/test-infra-chat.ts compares the two templates).
 */
export class PapyrusChatStack extends Stack {
  constructor(scope: Construct, props: PapyrusChatStackProps) {
    const { config, lambdaAssetDirectory, ...stackProps } = props;
    const chat = config.chat;
    const stackName = resolveChatStackName(config);
    if (!chat || !stackName) throw new Error(`site ${config.siteId} does not enable chat`);
    // The construct id is the stack name: the SQS event source mapping logical ids derive from it.
    super(scope, stackName, { ...stackProps, stackName });

    const modelKeyParameter = chat.modelKeyParameter;
    const logGroupPrefix = resolveChatLogGroupPrefix(config);

    const gatewayRoleArn = new CfnParameter(this, "GatewayRoleArn", {
      type: "String",
      description: "The site's CMS compute role ARN (CmsComputeRoleArn output of the app-shell stack); receives the scoped gateway policy.",
      allowedPattern: "^arn:aws:iam::[0-9]{12}:role/.+$",
    });
    const privateBotId = new CfnParameter(this, "PrivateAssistantBotId", {
      type: "String",
      default: CHAT_PRIVATE_ASSISTANT_ID,
      description: "Stable Papyrus-owned assistant ID; stored per derived account tenant on first private-channel open.",
      allowedPattern: "^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$",
    });
    const privateBotName = new CfnParameter(this, "PrivateAssistantBotName", {
      type: "String",
      default: CHAT_PRIVATE_ASSISTANT_NAME,
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
      removalPolicy: RemovalPolicy.RETAIN,
    });

    const conversations = new dynamodb.Table(this, "PrivateConversationIndex", {
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      deletionProtection: true,
      removalPolicy: RemovalPolicy.RETAIN,
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
      removalPolicy: RemovalPolicy.RETAIN,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
    });

    const queue = (id: string, extra: Partial<sqs.QueueProps> = {}) =>
      new sqs.Queue(this, id, { encryption: sqs.QueueEncryption.SQS_MANAGED, enforceSSL: true, ...extra });
    const runDlq = queue("TurnRunDlq", { retentionPeriod: Duration.days(14) });
    const probeDlq = queue("TurnProbeDlq", { retentionPeriod: Duration.days(14) });
    const runs = queue("TurnRuns", {
      visibilityTimeout: Duration.seconds(1800),
      retentionPeriod: Duration.days(4),
      deadLetterQueue: { queue: runDlq, maxReceiveCount: 5 },
    });
    const probes = queue("TurnProbes", {
      visibilityTimeout: Duration.minutes(2),
      retentionPeriod: Duration.days(4),
      deadLetterQueue: { queue: probeDlq, maxReceiveCount: 5 },
    });

    const gateway = iam.Role.fromRoleArn(this, "PapyrusChatGatewayRole", gatewayRoleArn.valueAsString, { mutable: true });
    gateway.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:TransactWriteItems", "dynamodb:Query", "dynamodb:BatchGetItem"],
      resources: [messaging.tableArn],
    }));
    gateway.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem"],
      resources: [conversations.tableArn, `${conversations.tableArn}/index/*`],
    }));
    gateway.addToPrincipalPolicy(new iam.PolicyStatement({ actions: ["s3:GetObject"], resources: [objects.arnForObjects("conversations/*")] }));
    gateway.addToPrincipalPolicy(new iam.PolicyStatement({ actions: ["sqs:SendMessage"], resources: [runs.queueArn, probes.queueArn] }));
    // Appended last, as in the activated stack's policy (the transaction-check correction was added to it afterwards).
    gateway.addToPrincipalPolicy(new iam.PolicyStatement({ actions: ["dynamodb:ConditionCheckItem"], resources: [messaging.tableArn] }));

    const hostedEnvironment = {
      PAPYRUS_CHAT_MESSAGING_TABLE: messaging.tableName,
      PAPYRUS_CHAT_CONVERSATIONS_TABLE: conversations.tableName,
      PAPYRUS_CHAT_SESSION_BUCKET: objects.bucketName,
      PAPYRUS_CHAT_TURN_RUNS_QUEUE_URL: runs.queueUrl,
      PAPYRUS_CHAT_TURN_PROBES_QUEUE_URL: probes.queueUrl,
      PAPYRUS_CHAT_PRIVATE_BOT_ID: privateBotId.valueAsString,
      PAPYRUS_CHAT_PRIVATE_BOT_NAME: privateBotName.valueAsString,
    };

    const runLogGroup = new logs.LogGroup(this, "RunWorkerLogs", {
      logGroupName: `${logGroupPrefix}-run-worker`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const probeLogGroup = new logs.LogGroup(this, "ProbeWorkerLogs", {
      logGroupName: `${logGroupPrefix}-probe-worker`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
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
      // Pseudo parameters, not the literal account: the template stays environment-agnostic like the activated stack.
      resources: [Arn.format({ partition: Aws.PARTITION, region: Aws.REGION, account: Aws.ACCOUNT_ID, service: "ssm", resource: "parameter", resourceName: modelKeyParameter.slice(1), arnFormat: ArnFormat.SLASH_RESOURCE_NAME })],
    }));
    runWorker.addToPolicy(new iam.PolicyStatement({ actions: ["logs:CreateLogStream", "logs:PutLogEvents"], resources: [`${runLogGroup.logGroupArn}:*`] }));
    runWorker.addToPolicy(new iam.PolicyStatement({
      actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      resources: [objects.arnForObjects("conversations/*")],
    }));
    runWorker.addToPolicy(new iam.PolicyStatement({ actions: ["sqs:ChangeMessageVisibility", "sqs:SendMessage"], resources: [runs.queueArn, probes.queueArn] }));

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
    probeWorker.addToPolicy(new iam.PolicyStatement({ actions: ["s3:GetObject"], resources: [objects.arnForObjects("conversations/*")] }));
    probeWorker.addToPolicy(new iam.PolicyStatement({ actions: ["sqs:SendMessage"], resources: [runs.queueArn, probes.queueArn] }));
    probeWorker.addToPolicy(new iam.PolicyStatement({ actions: ["logs:CreateLogStream", "logs:PutLogEvents"], resources: [`${probeLogGroup.logGroupArn}:*`] }));

    let code: lambda.Code;
    if (chat.workerCodeS3Key) {
      // Already uploaded and verified bytes: the template names the object, nothing is bundled or uploaded.
      const assets = s3.Bucket.fromBucketName(this, "WorkerCodeAssets", Fn.sub("cdk-hnb659fds-assets-${AWS::AccountId}-${AWS::Region}"));
      code = lambda.Code.fromBucket(assets, chat.workerCodeS3Key);
      Annotations.of(assets).acknowledgeWarning("@aws-cdk/aws-lambda:codeFromBucketObjectVersionNotSpecified", "the key is a content hash; it is never overwritten");
    } else {
      if (!lambdaAssetDirectory) throw new Error(`site ${config.siteId}: bundle the chat workers first (scripts/bundle-chat-lambdas.mjs) and pass -c chatLambdas=<dir>, or pin chat.workerCodeS3Key`);
      code = lambda.Code.fromAsset(lambdaAssetDirectory);
    }

    const runWorkerFunction = new lambda.Function(this, "RunWorker", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "run-worker.handler",
      code,
      role: runWorker,
      memorySize: 1024,
      timeout: Duration.seconds(900),
      logGroup: runLogGroup,
      environment: { ...hostedEnvironment, OPENAI_API_KEY_PARAMETER: modelKeyParameter },
      description: "Runs Papyrus private chat turns with the computerless Chatticus execution profile.",
    });
    const probeWorkerFunction = new lambda.Function(this, "ProbeWorker", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "probe-worker.handler",
      code,
      role: probeWorker,
      memorySize: 512,
      timeout: Duration.seconds(60),
      logGroup: probeLogGroup,
      environment: hostedEnvironment,
      description: "Recovers and finalizes Papyrus private chat turns.",
    });
    // The model key parameter exists for every configured site, so the workers run from the first deploy.
    runWorkerFunction.addEventSource(new eventSources.SqsEventSource(runs, { enabled: true, batchSize: 1 }));
    probeWorkerFunction.addEventSource(new eventSources.SqsEventSource(probes, { enabled: true, batchSize: 1 }));
    // Last, as in the activated stack (the storage-owner fence was added after the event source grants).
    runWorker.addToPolicy(new iam.PolicyStatement({ actions: ["dynamodb:ConditionCheckItem"], resources: [conversations.tableArn] }));

    const exported = (id: string, value: string, exportKey?: Parameters<typeof chatExportName>[1]) =>
      new CfnOutput(this, id, { value, ...(exportKey ? { exportName: chatExportName(stackName, exportKey) } : {}) });
    exported("MessagingTableName", messaging.tableName, "MessagingTableName");
    exported("ConversationIndexTableName", conversations.tableName, "ConversationIndexTableName");
    exported("SessionBucketName", objects.bucketName, "SessionBucketName");
    exported("TurnRunsQueueUrl", runs.queueUrl, "TurnRunsQueueUrl");
    exported("TurnProbesQueueUrl", probes.queueUrl, "TurnProbesQueueUrl");
    exported("FeatureDefault", "enabled per site by the chat block of its site.json (PAPYRUS_PRIVATE_CHAT_ENABLED on the CMS production branch)");
    exported("SyntheticAdapterTestOnly", "false");
    exported("GatewayMessagingTableEnvironmentName", "PAPYRUS_CHAT_MESSAGING_TABLE");
    exported("GatewayMessagingTableName", messaging.tableName);
    exported("GatewayConversationTableEnvironmentName", "PAPYRUS_CHAT_CONVERSATIONS_TABLE");
    exported("GatewayConversationTableName", conversations.tableName);
    exported("GatewaySessionBucketEnvironmentName", "PAPYRUS_CHAT_SESSION_BUCKET");
    exported("GatewaySessionBucketName", objects.bucketName);
    exported("GatewayRunQueueEnvironmentName", "PAPYRUS_CHAT_TURN_RUNS_QUEUE_URL");
    exported("GatewayProbeQueueEnvironmentName", "PAPYRUS_CHAT_TURN_PROBES_QUEUE_URL");
    exported("GatewayPrivateBotIdEnvironmentName", "PAPYRUS_CHAT_PRIVATE_BOT_ID");
    exported("PrivateAssistantBotIdValue", privateBotId.valueAsString);
    exported("GatewayPrivateBotNameEnvironmentName", "PAPYRUS_CHAT_PRIVATE_BOT_NAME");
    exported("PrivateAssistantBotNameValue", privateBotName.valueAsString);
    exported("WorkerModelKeyParameterName", modelKeyParameter);
    exported("RunWorkerFunctionName", runWorkerFunction.functionName);
    exported("ProbeWorkerFunctionName", probeWorkerFunction.functionName);
  }
}
