import { defineBackend, secret } from "@aws-amplify/backend";
import { Duration, RemovalPolicy, Stack } from "aws-cdk-lib";
import * as backup from "aws-cdk-lib/aws-backup";
import { AwsCustomResource, AwsCustomResourcePolicy, PhysicalResourceId } from "aws-cdk-lib/custom-resources";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as events from "aws-cdk-lib/aws-events";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as ses from "aws-cdk-lib/aws-ses";
import * as sesActions from "aws-cdk-lib/aws-ses-actions";
import { PolicyStatement } from "aws-cdk-lib/aws-iam";
import { CfnFunction, Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import { CfnIndex, CfnVectorBucket, CfnVectorBucketPolicy } from "aws-cdk-lib/aws-s3vectors";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { auth } from "./auth/resource";
import { data } from "./data/resource";
import { assignmentAction } from "./functions/assignment-action/resource";
import { categoryAction } from "./functions/category-action/resource";
import { ConsoleChatResponderStack } from "./functions/console-chat-responder/resource";
import { graphqlJwtAuthorizer } from "./functions/graphql-jwt-authorizer/resource";
import { knowledgeQuery } from "./functions/knowledge-query/resource";
import { manageUserRole } from "./functions/manage-user-role/resource";
import { modelAttachmentUpload } from "./functions/model-attachment-upload/resource";
import { newsroomSummary } from "./functions/newsroom-summary/resource";
import { procedureAction } from "./functions/procedure-action/resource";
import { readerSettings } from "./functions/reader-settings/resource";
import { emailSubmissionProcessor } from "./functions/email-submission-processor/resource";
import { sesInboundReceive } from "./functions/ses-inbound-receive/resource";
import { slackDelivery } from "./functions/slack-delivery/resource";
import { slackEvents } from "./functions/slack-events/resource";
import { InboundEmailStack } from "./inbound-email/stack";
import { SlackAgentStack } from "./slack/stack";
import { storage } from "./storage/resource";

const knowledgeVectorIndexName = "papyrus-knowledge";
const knowledgeVectorDimension = 1536;
const knowledgeEmbeddingModel = "text-embedding-3-small";

const amplifyBranch = (process.env.AWS_BRANCH ?? "").trim();
const amplifyAppId = (process.env.AWS_APP_ID ?? "").trim();
const isAmplifyProductionPipeline =
  amplifyBranch === "main" && amplifyAppId === "dbsyytcm9drqa";

function readEnvFlag(name: string, defaultValue: boolean): boolean {
  const raw = (process.env[name] ?? "").trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(raw)) return true;
  if (["0", "false", "no", "off"].includes(raw)) return false;
  return defaultValue;
}

function sanitizeAwsName(value: string, maxLength = 50): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, maxLength);
}

// SES active receipt rule sets and shared backup vault names are account-global.
// Keep them on the production pipeline only unless explicitly opted in.
const enableInboundEmail = readEnvFlag("PAPYRUS_ENABLE_INBOUND_EMAIL", isAmplifyProductionPipeline);
const enableSlackAgent = readEnvFlag("PAPYRUS_ENABLE_SLACK", false);
const enableStorageBackups = readEnvFlag("PAPYRUS_ENABLE_STORAGE_BACKUPS", isAmplifyProductionPipeline);

const backend = defineBackend({
  assignmentAction,
  auth,
  categoryAction,
  data,
  graphqlJwtAuthorizer,
  knowledgeQuery,
  manageUserRole,
  modelAttachmentUpload,
  newsroomSummary,
  procedureAction,
  readerSettings,
  emailSubmissionProcessor,
  sesInboundReceive,
  slackEvents,
  slackDelivery,
  storage,
});

const amplifyBackendDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(amplifyBackendDir, "..");
const enableConsoleResponder = readEnvFlag("PAPYRUS_ENABLE_CONSOLE_RESPONDER", true);

if (
  enableConsoleResponder
  && !process.env.PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI?.trim()
  && !process.env.PAPYRUS_CONSOLE_RESPONDER_ALLOW_LOCAL_BUILD?.trim()
  && !isAmplifyProductionPipeline
) {
  process.env.PAPYRUS_CONSOLE_RESPONDER_ALLOW_LOCAL_BUILD = "true";
}
const inboundEmailDomain = (process.env.PAPYRUS_INBOUND_EMAIL_DOMAIN ?? "p.apyr.us").trim().toLowerCase();
const inboundEmailLocalParts = (process.env.PAPYRUS_INBOUND_EMAIL_LOCAL_PARTS ?? "submissions,suggestions")
  .split(",")
  .map((entry) => entry.trim().toLowerCase())
  .filter(Boolean);
const inboundEmailCorpusKey = (process.env.PAPYRUS_INBOUND_EMAIL_CORPUS_KEY ?? "AI-ML-research").trim();
const inboundDnsZoneId = (process.env.PAPYRUS_ROUTE53_HOSTED_ZONE_ID ?? "Z10285921B1G7MVRV06W9").trim();
const inboundDnsZoneName = (process.env.PAPYRUS_ROUTE53_HOSTED_ZONE_NAME ?? "apyr.us").trim().replace(/\.$/, "");
const inboundDnsRecordName = inboundEmailDomain.endsWith(`.${inboundDnsZoneName}`)
  ? inboundEmailDomain.slice(0, -(inboundDnsZoneName.length + 1))
  : inboundEmailDomain;

if (enableConsoleResponder || enableSlackAgent) {
  const messageTable = backend.data.resources.tables.Message;
  const cfnTables = backend.data.resources.cfnResources.cfnTables;
  const messageCfnTable =
    cfnTables.Message
    ?? cfnTables.MessageTable
    ?? Object.entries(cfnTables).find(([key]) => {
      const normalized = key.toLowerCase();
      return normalized.includes("message") && !normalized.includes("thread");
    })?.[1];

  if (messageCfnTable) {
    messageCfnTable.streamSpecification = {
      streamViewType: dynamodb.StreamViewType.NEW_IMAGE,
    };
  }

  const messageStreamArn = messageTable.tableStreamArn ?? messageCfnTable?.attrStreamArn;
  if (!messageStreamArn) {
    throw new Error(`Message agents require Message table stream ARN. cfnTables=${Object.keys(cfnTables).join(",")}`);
  }

  const messageThreadTable = backend.data.resources.tables.MessageThread;
  const dataStack = Stack.of(messageTable);
  const graphqlEndpoint = backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl;
  const jwtAuthorizerCfn = backend.graphqlJwtAuthorizer.resources.lambda.node.defaultChild as CfnFunction | undefined;
  const jwtAuthorizerEnvironment = jwtAuthorizerCfn?.environment;
  const jwtAuthorizerVariables =
    jwtAuthorizerEnvironment
    && typeof jwtAuthorizerEnvironment === "object"
    && "variables" in jwtAuthorizerEnvironment
      ? (jwtAuthorizerEnvironment as { variables?: Record<string, string> }).variables
      : undefined;
  const jwtSsmEnvConfig =
    process.env.AMPLIFY_SSM_ENV_CONFIG?.trim()
    || jwtAuthorizerVariables?.AMPLIFY_SSM_ENV_CONFIG?.trim()
    || "";

  if (enableConsoleResponder) {
    new ConsoleChatResponderStack(dataStack, "ConsoleChatResponder", {
      messageTable,
      messageStreamArn,
      threadTable: messageThreadTable,
      projectRoot,
      graphqlEndpoint,
      amplifySsmEnvConfig: jwtSsmEnvConfig || undefined,
      responseTarget: process.env.PAPYRUS_CONSOLE_RESPONSE_TARGET,
      model: process.env.PAPYRUS_CONSOLE_MODEL,
      prebuiltImageUri: process.env.PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI,
    });
  }

  if (enableSlackAgent) {
    const slackEventsLambda = backend.slackEvents.resources.lambda as LambdaFunction;
    const slackDeliveryLambda = backend.slackDelivery.resources.lambda as LambdaFunction;
    slackEventsLambda.addToRolePolicy(
      new PolicyStatement({
        actions: ["appsync:GraphQL"],
        resources: ["*"],
      }),
    );
    backend.slackEvents.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", graphqlEndpoint);
    backend.slackEvents.addEnvironment(
      "PAPYRUS_CONSOLE_RESPONSE_TARGET",
      (process.env.PAPYRUS_CONSOLE_RESPONSE_TARGET ?? "cloud").trim() || "cloud",
    );
    backend.slackEvents.addEnvironment(
      "PAPYRUS_SLACK_ALLOWED_USER_IDS",
      (process.env.PAPYRUS_SLACK_ALLOWED_USER_IDS ?? "").trim(),
    );
    backend.slackDelivery.addEnvironment(
      "PAPYRUS_CONSOLE_RESPONSE_TARGET",
      (process.env.PAPYRUS_CONSOLE_RESPONSE_TARGET ?? "cloud").trim() || "cloud",
    );
    const slackSigningSecretName = (process.env.PAPYRUS_SLACK_SIGNING_SECRET_NAME ?? "PAPYRUS_SLACK_SIGNING_SECRET").trim();
    const slackBotTokenName = (process.env.PAPYRUS_SLACK_BOT_TOKEN_NAME ?? "PAPYRUS_SLACK_BOT_TOKEN").trim();
    backend.slackEvents.addEnvironment("PAPYRUS_SLACK_SIGNING_SECRET", secret(slackSigningSecretName));
    backend.slackDelivery.addEnvironment("PAPYRUS_SLACK_BOT_TOKEN", secret(slackBotTokenName));

    const slackStack = new SlackAgentStack(dataStack, "SlackAgent", {
      slackEventsFunction: slackEventsLambda,
      slackDeliveryFunction: slackDeliveryLambda,
      messageTable,
      messageStreamArn,
      graphqlEndpoint,
    });
    backend.addOutput({
      slackEventsUrl: slackStack.eventsFunctionUrl,
    });
  }
}

const storageBucket = backend.storage.resources.bucket;
const storageStack = Stack.of(storageBucket);

let storageBackupPlan: backup.BackupPlan | undefined;
let storageBackupVault: backup.BackupVault | undefined;

if (enableStorageBackups) {
  const storageBackupsStack = backend.createStack("storage-backups");
  const storageBackupVaultName = sanitizeAwsName(
    process.env.PAPYRUS_STORAGE_BACKUP_VAULT_NAME?.trim()
    || (isAmplifyProductionPipeline
      ? "papyrus-dbsyytcm9drqa-main-media-backup-vault"
      : `papyrus-${sanitizeAwsName(storageBackupsStack.stackName, 32)}-media-vault`),
  );

  const storageBucketCfn = storageBucket.node.defaultChild as s3.CfnBucket | undefined;
  if (storageBucketCfn) {
    // S3 PITR in AWS Backup requires S3 event delivery through EventBridge.
    storageBucketCfn.addPropertyOverride(
      "NotificationConfiguration.EventBridgeConfiguration.EventBridgeEnabled",
      true,
    );
  }

  storageBackupVault = new backup.BackupVault(storageBackupsStack, "PapyrusStorageBackupVault", {
    backupVaultName: storageBackupVaultName,
    removalPolicy: RemovalPolicy.RETAIN,
  });
  storageBackupPlan = new backup.BackupPlan(storageBackupsStack, "PapyrusStorageBackupPlan", {
    backupVault: storageBackupVault,
  });

  storageBackupPlan.addRule(
    new backup.BackupPlanRule({
      ruleName: "papyrus-storage-pitr-35d",
      enableContinuousBackup: true,
      deleteAfter: Duration.days(35),
    }),
  );

  storageBackupPlan.addRule(
    new backup.BackupPlanRule({
      ruleName: "papyrus-storage-daily-365d",
      scheduleExpression: events.Schedule.cron({ minute: "0", hour: "5" }),
      deleteAfter: Duration.days(365),
    }),
  );

  storageBackupPlan.addSelection("PapyrusStorageBackupSelection", {
    allowRestores: true,
    resources: [backup.BackupResource.fromArn(storageBucket.bucketArn)],
  });
}

// Grant S3 access on Lambda roles only (not storage bucket policies) to avoid
// storage ↔ data nested-stack circular dependencies from allow.resource().
const corporaObjectArn = `${storageBucket.bucketArn}/corpora/*`;
const newsroomObjectArn = `${storageBucket.bucketArn}/newsroom/*`;
const grantCorporaRead = (lambda: LambdaFunction) => {
  lambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["s3:GetObject"],
      resources: [corporaObjectArn],
    }),
  );
};
const grantNewsroomReadWrite = (lambda: LambdaFunction) => {
  lambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["s3:GetObject", "s3:PutObject"],
      resources: [newsroomObjectArn],
    }),
  );
};
const grantNewsroomReadWriteDelete = (lambda: LambdaFunction) => {
  lambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      resources: [newsroomObjectArn],
    }),
  );
};
const mediaBucketName = storageBucket.bucketName;
const withMediaBucketEnv = (resource: { addEnvironment: (key: string, value: string) => void }) => {
  resource.addEnvironment("PAPYRUS_MEDIA_BUCKET_NAME", mediaBucketName);
  resource.addEnvironment("papyrusMedia_BUCKET_NAME", mediaBucketName);
};
for (const resource of [
  backend.assignmentAction,
  backend.categoryAction,
  backend.emailSubmissionProcessor,
  backend.knowledgeQuery,
  backend.modelAttachmentUpload,
  backend.newsroomSummary,
  backend.procedureAction,
  backend.sesInboundReceive,
]) {
  withMediaBucketEnv(resource);
}
grantCorporaRead(backend.knowledgeQuery.resources.lambda as LambdaFunction);
grantNewsroomReadWrite(backend.assignmentAction.resources.lambda as LambdaFunction);
grantNewsroomReadWrite(backend.categoryAction.resources.lambda as LambdaFunction);
grantNewsroomReadWrite(backend.newsroomSummary.resources.lambda as LambdaFunction);
grantNewsroomReadWriteDelete(backend.modelAttachmentUpload.resources.lambda as LambdaFunction);

if (enableInboundEmail) {
  if (!backend.sesInboundReceive || !backend.emailSubmissionProcessor) {
    throw new Error("Inbound email is enabled but sesInboundReceive/emailSubmissionProcessor were not registered.");
  }
  const inboundReceive = backend.sesInboundReceive;
  const inboundProcessor = backend.emailSubmissionProcessor;
  const receiveLambda = inboundReceive.resources.lambda as LambdaFunction;
  const processorLambda = inboundProcessor.resources.lambda as LambdaFunction;
  const graphqlEndpoint = backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl;
  const inboundRecipients = inboundEmailLocalParts.map((localPart) => `${localPart}@${inboundEmailDomain}`);

  inboundReceive.addEnvironment(
    "PAPYRUS_EMAIL_SUBMISSION_PROCESSOR_FUNCTION_NAME",
    processorLambda.functionName,
  );
  inboundReceive.addEnvironment("PAPYRUS_INBOUND_EMAIL_DOMAIN", inboundEmailDomain);
  inboundReceive.addEnvironment("PAPYRUS_INBOUND_EMAIL_LOCAL_PARTS", inboundEmailLocalParts.join(","));
  inboundReceive.addEnvironment("PAPYRUS_INBOUND_EMAIL_CORPUS_KEY", inboundEmailCorpusKey);
  inboundReceive.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", graphqlEndpoint);

  inboundProcessor.addEnvironment("PAPYRUS_INBOUND_EMAIL_CORPUS_KEY", inboundEmailCorpusKey);
  inboundProcessor.addEnvironment("PAPYRUS_INBOUND_EMAIL_DOMAIN", inboundEmailDomain);
  inboundProcessor.addEnvironment("PAPYRUS_INBOUND_FEEDBACK_EMAIL_ENABLED", "true");
  inboundProcessor.addEnvironment(
    "PAPYRUS_INBOUND_FEEDBACK_FROM_EMAIL",
    `Papyrus Submissions <submissions@${inboundEmailDomain}>`,
  );
  inboundProcessor.addEnvironment("PAPYRUS_PUBLIC_SITE_BASE_URL", "https://p.apyr.us");
  inboundProcessor.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", graphqlEndpoint);

  receiveLambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["lambda:InvokeFunction"],
      resources: [processorLambda.functionArn],
    }),
  );
  receiveLambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["s3:GetObject", "s3:ListBucket"],
      resources: [
        storageBucket.bucketArn,
        `${storageBucket.bucketArn}/inbound-email/*`,
      ],
    }),
  );
  processorLambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["s3:ListBucket"],
      resources: [storageBucket.bucketArn],
    }),
  );
  processorLambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      resources: [
        `${storageBucket.bucketArn}/inbound-email/*`,
        `${storageBucket.bucketArn}/inbound-email-archived/*`,
      ],
    }),
  );
  processorLambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["s3:GetObject", "s3:PutObject"],
      resources: [corporaObjectArn],
    }),
  );
  receiveLambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["appsync:GraphQL"],
      resources: ["*"],
    }),
  );
  processorLambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["appsync:GraphQL"],
      resources: ["*"],
    }),
  );
  processorLambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["ses:SendEmail", "ses:SendRawEmail"],
      resources: ["*"],
    }),
  );

  const inboundEventStack = Stack.of(receiveLambda);

  // SES receipt rule sets are account-global; only provision on the production pipeline.
  if (isAmplifyProductionPipeline) {
  const inboundDnsZone = route53.HostedZone.fromHostedZoneAttributes(storageStack, "PapyrusInboundDnsZone", {
    hostedZoneId: inboundDnsZoneId,
    zoneName: inboundDnsZoneName,
  });
  const verifyInboundEmailDomain = new AwsCustomResource(storageStack, "VerifyInboundEmailDomain", {
    onCreate: {
      service: "SES",
      action: "verifyDomainIdentity",
      parameters: {
        Domain: inboundEmailDomain,
      },
      physicalResourceId: PhysicalResourceId.of(`ses-domain-verify-${inboundEmailDomain}`),
    },
    onUpdate: {
      service: "SES",
      action: "verifyDomainIdentity",
      parameters: {
        Domain: inboundEmailDomain,
      },
      physicalResourceId: PhysicalResourceId.of(`ses-domain-verify-${inboundEmailDomain}`),
    },
    policy: AwsCustomResourcePolicy.fromSdkCalls({
      resources: AwsCustomResourcePolicy.ANY_RESOURCE,
    }),
    timeout: Duration.minutes(2),
  });
  new route53.TxtRecord(storageStack, "PapyrusInboundEmailDomainVerification", {
    zone: inboundDnsZone,
    recordName: `_amazonses.${inboundDnsRecordName}`,
    ttl: Duration.minutes(5),
    values: [verifyInboundEmailDomain.getResponseField("VerificationToken")],
  });

  const inboundRuleSet = new ses.ReceiptRuleSet(storageStack, "PapyrusInboundEmailRuleSet", {
    receiptRuleSetName: `papyrus-inbound-${inboundEmailDomain.replace(/\./g, "-")}`,
  });
  inboundRuleSet.addRule("PapyrusInboundSubmissions", {
    recipients: inboundRecipients,
    enabled: true,
    scanEnabled: true,
    tlsPolicy: ses.TlsPolicy.REQUIRE,
    actions: [
      new sesActions.S3({
        bucket: storageBucket,
        objectKeyPrefix: "inbound-email/",
      }),
    ],
  });

  new AwsCustomResource(storageStack, "ActivateInboundEmailRuleSet", {
    onCreate: {
      service: "SES",
      action: "setActiveReceiptRuleSet",
      parameters: {
        RuleSetName: inboundRuleSet.receiptRuleSetName,
      },
      physicalResourceId: PhysicalResourceId.of(`activate-${inboundRuleSet.receiptRuleSetName}`),
    },
    onUpdate: {
      service: "SES",
      action: "setActiveReceiptRuleSet",
      parameters: {
        RuleSetName: inboundRuleSet.receiptRuleSetName,
      },
      physicalResourceId: PhysicalResourceId.of(`activate-${inboundRuleSet.receiptRuleSetName}`),
    },
    onDelete: {
      service: "SES",
      action: "setActiveReceiptRuleSet",
      parameters: {
        RuleSetName: null,
      },
    },
    policy: AwsCustomResourcePolicy.fromSdkCalls({
      resources: AwsCustomResourcePolicy.ANY_RESOURCE,
    }),
    timeout: Duration.minutes(2),
  });
  }

  new InboundEmailStack(inboundEventStack, "InboundEmail", {
    storageBucket,
    receiveFunctionArn: receiveLambda.functionArn,
  });
}

const knowledgeVectorsStack = backend.createStack("knowledge-vectors");
const knowledgeVectorBucket = new CfnVectorBucket(knowledgeVectorsStack, "PapyrusKnowledgeVectorBucket", {
  encryptionConfiguration: {
    sseType: "AES256",
  },
});
const knowledgeVectorIndex = new CfnIndex(knowledgeVectorsStack, "PapyrusKnowledgeVectorIndex", {
  dataType: "float32",
  dimension: knowledgeVectorDimension,
  distanceMetric: "cosine",
  indexName: knowledgeVectorIndexName,
  metadataConfiguration: {
    nonFilterableMetadataKeys: ["text", "summary", "sourceUri", "title"],
  },
  vectorBucketArn: knowledgeVectorBucket.attrVectorBucketArn,
});
knowledgeVectorIndex.node.addDependency(knowledgeVectorBucket);
const knowledgeVectorBucketPolicy = new CfnVectorBucketPolicy(knowledgeVectorsStack, "PapyrusKnowledgeVectorBucketPolicy", {
  vectorBucketArn: knowledgeVectorBucket.attrVectorBucketArn,
  policy: {
    Version: "2012-10-17",
    Statement: [
      {
        Sid: "AllowSameAccountPapyrusKnowledgeVectorAccess",
        Effect: "Allow",
        Principal: {
          AWS: `arn:aws:iam::${knowledgeVectorsStack.account}:root`,
        },
        Action: [
          "s3vectors:GetIndex",
          "s3vectors:GetVectors",
          "s3vectors:ListVectors",
          "s3vectors:PutVectors",
          "s3vectors:QueryVectors",
          "s3vectors:DeleteVectors",
        ],
        Resource: [
          knowledgeVectorBucket.attrVectorBucketArn,
          knowledgeVectorIndex.attrIndexArn,
        ],
      },
    ],
  },
});
knowledgeVectorBucketPolicy.node.addDependency(knowledgeVectorIndex);

const knowledgeQueryLambda = backend.knowledgeQuery.resources.lambda as LambdaFunction;
backend.knowledgeQuery.addEnvironment("OPENAI_API_KEY", secret("OPENAI_API_KEY"));
knowledgeQueryLambda.addEnvironment("PAPYRUS_STORAGE_BUCKET_NAME", storageBucket.bucketName);
knowledgeQueryLambda.addEnvironment(
  "PAPYRUS_GRAPHQL_ENDPOINT",
  backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl,
);
knowledgeQueryLambda.addEnvironment("PAPYRUS_S3_VECTOR_INDEX_ARN", knowledgeVectorIndex.attrIndexArn);
knowledgeQueryLambda.addEnvironment("PAPYRUS_S3_VECTOR_INDEX_NAME", knowledgeVectorIndexName);
knowledgeQueryLambda.addEnvironment("PAPYRUS_EMBEDDING_MODEL", knowledgeEmbeddingModel);
knowledgeQueryLambda.addEnvironment("PAPYRUS_EMBEDDING_DIMENSIONS", String(knowledgeVectorDimension));
knowledgeQueryLambda.addToRolePolicy(
  new PolicyStatement({
    actions: [
      "s3vectors:GetIndex",
      "s3vectors:GetVectors",
      "s3vectors:ListVectors",
      "s3vectors:QueryVectors",
    ],
    resources: [knowledgeVectorIndex.attrIndexArn],
  }),
);
knowledgeQueryLambda.addToRolePolicy(
  new PolicyStatement({
    actions: ["ssm:GetParameter"],
    resources: [
      `arn:aws:ssm:${knowledgeVectorsStack.region}:${knowledgeVectorsStack.account}:parameter/amplify/papyrus/*/OPENAI_API_KEY`,
      `arn:aws:ssm:${knowledgeVectorsStack.region}:${knowledgeVectorsStack.account}:parameter/amplify/shared/papyrus/OPENAI_API_KEY`,
    ],
  }),
);

backend.addOutput({
  custom: {
    inboundEmail: enableInboundEmail
      ? {
          domain: inboundEmailDomain,
          localParts: inboundEmailLocalParts,
          addresses: inboundEmailLocalParts.map((localPart) => `${localPart}@${inboundEmailDomain}`),
          corpusKey: inboundEmailCorpusKey,
        }
      : null,
    knowledgeQuery: {
      s3VectorBucketArn: knowledgeVectorBucket.attrVectorBucketArn,
      s3VectorIndexArn: knowledgeVectorIndex.attrIndexArn,
      s3VectorIndexName: knowledgeVectorIndexName,
      embeddingModel: knowledgeEmbeddingModel,
      embeddingDimensions: knowledgeVectorDimension,
    },
    storageBackups: storageBackupPlan && storageBackupVault
      ? {
          backupPlanId: storageBackupPlan.backupPlanId,
          backupVaultArn: storageBackupVault.backupVaultArn,
          backupVaultName: storageBackupVault.backupVaultName,
          protectedBucketArn: storageBucket.bucketArn,
          protectedBucketName: storageBucket.bucketName,
        }
      : null,
  },
});
