import { defineBackend, secret } from "@aws-amplify/backend";
import { Stack } from "aws-cdk-lib";
import type * as backup from "aws-cdk-lib/aws-backup";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { CfnEventSourceMapping, Function as LambdaFunction, FunctionUrlAuthType } from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import { CfnIndex, CfnVectorBucket, CfnVectorBucketPolicy } from "aws-cdk-lib/aws-s3vectors";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { rebuildTriggerSettings } from "./rebuild-trigger-settings";
import { applyCognitoDomainPrefix, authConfigFromEnv, defineSiteAuth } from "./auth/resource";
import { data } from "./data/resource";
import { assignmentAction } from "./functions/assignment-action/resource";
import { categoryAction } from "./functions/category-action/resource";
import { ConsoleChatResponderStack } from "./functions/console-chat-responder/resource";
import { contentActions } from "./functions/content-actions/resource";
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
import { addInboundEmailSesIntake } from "./inbound-email/ses-intake";
import { InboundEmailStack } from "./inbound-email/stack";
import {
  deriveKnowledgeVectorIndexName,
  deriveReceiptRuleName,
  deriveReceiptRuleSetName,
  deriveStorageBackupVaultName,
  isLegacyProductionPipeline,
  planInboundEmailSes,
  resolveSiteBackendFeatureFlags,
  type SiteBackendIdentity,
} from "./site-backend-names";
import { addStorageBackups } from "./storage-backups/construct";
import { storage } from "./storage/resource";
import type { PapyrusSite } from "../lib/define-site";

export function defineSiteBackend(papyrusSite: PapyrusSite) {
  // `papyrus.config.ts`'s default export. Backend options live under `backend`;
  // the default brand id namespaces account-global resources.
  const site = { brandId: papyrusSite.defaultBrand, ...papyrusSite.backend };
  const knowledgeVectorDimension = 1536;
  const knowledgeEmbeddingModel = "text-embedding-3-small";

  const amplifyBranch = (process.env.AWS_BRANCH ?? "").trim();
  const amplifyAppId = (process.env.AWS_APP_ID ?? "").trim();
  // Amplify app id whose `main` branch is the original p.apyr.us backend; only
  // that app keeps the historical account-global names (see site-backend-names.ts).
  const productionAppId = (site.productionAppId ?? "").trim();
  const siteBackendIdentity: SiteBackendIdentity = {
    brandId: (
      site.brandId
      ?? process.env.PAPYRUS_SITE_BRAND
      ?? process.env.NEXT_PUBLIC_PAPYRUS_SITE_BRAND
      ?? "papyrus"
    ).trim().toLowerCase(),
    amplifyAppId,
    amplifyBranch,
    productionAppId,
  };
  const isAmplifyProductionPipeline = isLegacyProductionPipeline(siteBackendIdentity);
  const knowledgeVectorIndexName = deriveKnowledgeVectorIndexName(siteBackendIdentity);
  const featureFlags = resolveSiteBackendFeatureFlags(site.features, process.env, siteBackendIdentity);
  const enableInboundEmail = featureFlags.inboundEmail;
  const enableSlackAgent = featureFlags.slack;
  const enableStorageBackups = featureFlags.storageBackups;

  const authConfig = site.auth ?? authConfigFromEnv();
  const backend = defineBackend({
    assignmentAction,
    auth: defineSiteAuth(authConfig),
    categoryAction,
    contentActions,
    data,
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

  const requestedCognitoDomainPrefix = (authConfig.cognitoDomainPrefix ?? "").trim();
  if (
    authConfig.applyCognitoDomainPrefix === true
    && requestedCognitoDomainPrefix !== ""
    && authConfig.disableGoogleOAuth !== true
  ) {
    applyCognitoDomainPrefix(backend.auth.stack, requestedCognitoDomainPrefix);
  }

  const amplifyBackendDir = dirname(fileURLToPath(import.meta.url));
  // Repo root in a Papyrus checkout; package root when installed from npm.
  const projectRoot = resolve(amplifyBackendDir, "..");
  const enableConsoleResponder = featureFlags.consoleResponder;

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

  let slackEventsUrl: string | undefined;

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
    const amplifySsmEnvConfig = process.env.AMPLIFY_SSM_ENV_CONFIG?.trim() || "";

    if (enableConsoleResponder) {
      new ConsoleChatResponderStack(dataStack, "ConsoleChatResponder", {
        messageTable,
        messageStreamArn,
        threadTable: messageThreadTable,
        projectRoot,
        graphqlEndpoint,
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
      if (amplifySsmEnvConfig) {
        backend.slackEvents.addEnvironment("AMPLIFY_SSM_ENV_CONFIG", amplifySsmEnvConfig);
        backend.slackDelivery.addEnvironment("AMPLIFY_SSM_ENV_CONFIG", amplifySsmEnvConfig);
      }
      backend.slackDelivery.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", graphqlEndpoint);
      backend.slackDelivery.addEnvironment(
        "PAPYRUS_CONSOLE_RESPONSE_TARGET",
        (process.env.PAPYRUS_CONSOLE_RESPONSE_TARGET ?? "cloud").trim() || "cloud",
      );
      const slackBotTokenName = (process.env.PAPYRUS_SLACK_BOT_TOKEN_NAME ?? "PAPYRUS_SLACK_BOT_TOKEN").trim();
      backend.slackDelivery.addEnvironment("PAPYRUS_SLACK_BOT_TOKEN", secret(slackBotTokenName));

      const slackStack = Stack.of(slackEventsLambda);
      const slackSsmResources = amplifyAppId
        ? [
            `arn:aws:ssm:${slackStack.region}:${slackStack.account}:parameter/amplify/${amplifyAppId}/*`,
            `arn:aws:ssm:${slackStack.region}:${slackStack.account}:parameter/amplify/shared/${amplifyAppId}/*`,
          ]
        : [`arn:aws:ssm:${slackStack.region}:${slackStack.account}:parameter/amplify/*`];
      const slackSsmPolicy = new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["ssm:GetParameter", "ssm:GetParameters"],
        resources: slackSsmResources,
      });
      slackEventsLambda.addToRolePolicy(slackSsmPolicy);
      slackDeliveryLambda.addToRolePolicy(slackSsmPolicy);

      // Wire Slack on the data stack (not a nested SlackAgent stack) to avoid CloudFormation
      // circular dependencies between Message and slack-delivery in the data resource group.
      const slackEventsFunctionUrl = slackEventsLambda.addFunctionUrl({
        authType: FunctionUrlAuthType.NONE,
      });
      slackEventsUrl = slackEventsFunctionUrl.url;

      const slackConsumerStack = backend.createStack("slack-consumer");
      new CfnEventSourceMapping(slackConsumerStack, "SlackDeliveryMessageStreamMapping", {
        batchSize: 1,
        eventSourceArn: messageStreamArn,
        functionName: slackDeliveryLambda.functionArn,
        functionResponseTypes: ["ReportBatchItemFailures"],
        maximumRetryAttempts: 2,
        startingPosition: "LATEST",
      });

      slackDeliveryLambda.addToRolePolicy(
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: [
            "dynamodb:DescribeStream",
            "dynamodb:GetRecords",
            "dynamodb:GetShardIterator",
            "dynamodb:ListStreams",
          ],
          resources: [messageStreamArn],
        }),
      );
      slackDeliveryLambda.addToRolePolicy(
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem"],
          resources: [messageTable.tableArn, `${messageTable.tableArn}/index/*`],
        }),
      );
      slackDeliveryLambda.addToRolePolicy(
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: ["appsync:GraphQL"],
          resources: ["*"],
        }),
      );
    }
  }

  const storageBucket = backend.storage.resources.bucket;
  const storageStack = Stack.of(storageBucket);

  let storageBackupPlan: backup.BackupPlan | undefined;
  let storageBackupVault: backup.BackupVault | undefined;

  const storageBucketCfn = storageBucket.node.defaultChild as s3.CfnBucket | undefined;
  if ((enableStorageBackups || enableInboundEmail) && storageBucketCfn) {
    // Backups and inbound-email intake both rely on S3 → EventBridge notifications.
    storageBucketCfn.addPropertyOverride(
      "NotificationConfiguration.EventBridgeConfiguration.EventBridgeEnabled",
      true,
    );
  }

  if (enableStorageBackups) {
    const storageBackupsStack = backend.createStack("storage-backups");
    const storageBackupVaultName = deriveStorageBackupVaultName(
      siteBackendIdentity,
      storageBackupsStack.stackName,
      process.env.PAPYRUS_STORAGE_BACKUP_VAULT_NAME,
    );

    const storageBackups = addStorageBackups(storageBackupsStack, {
      storageBucket,
      backupVaultName: storageBackupVaultName,
    });
    storageBackupVault = storageBackups.vault;
    storageBackupPlan = storageBackups.plan;
  }

  // Grant S3 access on Lambda roles only (not storage bucket policies) to avoid
  // storage ↔ data nested-stack circular dependencies from allow.resource().
  const corporaObjectArn = `${storageBucket.bucketArn}/corpora/*`;
  const mediaObjectArn = `${storageBucket.bucketArn}/media/*`;
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
  const grantMediaReadWriteDelete = (lambda: LambdaFunction) => {
    lambda.addToRolePolicy(
      new PolicyStatement({
        actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
        resources: [mediaObjectArn],
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
    backend.contentActions,
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
  const contentActionsLambda = backend.contentActions.resources.lambda as LambdaFunction;
  grantNewsroomReadWriteDelete(contentActionsLambda);
  contentActionsLambda.addEnvironment(
    "PAPYRUS_GRAPHQL_ENDPOINT",
    backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl,
  );
  contentActionsLambda.addToRolePolicy(
    new PolicyStatement({
      actions: ["appsync:GraphQL"],
      resources: ["*"],
    }),
  );
  const rebuildSettings = rebuildTriggerSettings({
    reader: site.reader,
    stagingBuildEnabled: site.stagingBuild?.enabled === true,
    cmsAppId: amplifyAppId,
    region: Stack.of(contentActionsLambda).region,
    account: Stack.of(contentActionsLambda).account,
  });
  for (const [name, value] of Object.entries(rebuildSettings.environment)) {
    contentActionsLambda.addEnvironment(name, value);
  }
  if (rebuildSettings.resources.length > 0) {
    contentActionsLambda.addToRolePolicy(
      new PolicyStatement({ actions: rebuildSettings.actions, resources: rebuildSettings.resources }),
    );
  }
  if ((site.revalidateBaseUrl ?? "").trim() !== "") {
    backend.contentActions.addEnvironment("PAPYRUS_REVALIDATE_BASE_URL", (site.revalidateBaseUrl ?? "").trim());
    const revalidateSecretParameter = (process.env.PAPYRUS_REVALIDATE_SECRET_PARAMETER ?? "").trim();
    if (!revalidateSecretParameter.startsWith("/")) {
      throw new Error(
        "revalidateBaseUrl is set but PAPYRUS_REVALIDATE_SECRET_PARAMETER is not (an SSM parameter name starting with /). The app-shell template sets it on the production branch for Pretext sites; see docs/site-hosting.md.",
      );
    }
    backend.contentActions.addEnvironment("PAPYRUS_REVALIDATE_SECRET_PARAMETER", revalidateSecretParameter);
    const revalidateStack = Stack.of(contentActionsLambda);
    contentActionsLambda.addToRolePolicy(
      new PolicyStatement({
        actions: ["ssm:GetParameter"],
        resources: [`arn:${revalidateStack.partition}:ssm:${revalidateStack.region}:${revalidateStack.account}:parameter${revalidateSecretParameter}`],
      }),
    );
  }
  grantNewsroomReadWriteDelete(backend.modelAttachmentUpload.resources.lambda as LambdaFunction);
  grantMediaReadWriteDelete(backend.modelAttachmentUpload.resources.lambda as LambdaFunction);
  if (backend.sesInboundReceive) {
    grantNewsroomReadWrite(backend.sesInboundReceive.resources.lambda as LambdaFunction);
  }

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

    // SES allows one active receipt rule set per region, so a non-legacy site
    // creates its own brand-named rule set and never activates it here.
    const inboundSesPlan = planInboundEmailSes(siteBackendIdentity, enableInboundEmail, site.inboundEmailSes);
    if (inboundSesPlan.createReceiptRules) {
      addInboundEmailSesIntake(storageStack, {
        storageBucket,
        recipients: inboundRecipients,
        ruleSetName: deriveReceiptRuleSetName(siteBackendIdentity, inboundEmailDomain),
        existingRuleSetName: site.inboundEmailSes?.existingReceiptRuleSetName,
        ruleName: deriveReceiptRuleName(siteBackendIdentity),
        activateRuleSet: inboundSesPlan.activateReceiptRuleSet,
        domainIdentity: inboundSesPlan.manageDomainIdentity
          ? {
              domain: inboundEmailDomain,
              hostedZoneId: inboundDnsZoneId,
              hostedZoneName: inboundDnsZoneName,
              recordName: inboundDnsRecordName,
            }
          : undefined,
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
        // Pipeline-deployed apps store secrets under amplify/<appId>/... rather
        // than the sandbox's amplify/papyrus/... path. Grant the app's own
        // secret path so a second CMS app (e.g. pilobol-us) can read its key.
        ...(amplifyAppId
          ? [
              `arn:aws:ssm:${knowledgeVectorsStack.region}:${knowledgeVectorsStack.account}:parameter/amplify/${amplifyAppId}/*/OPENAI_API_KEY`,
              `arn:aws:ssm:${knowledgeVectorsStack.region}:${knowledgeVectorsStack.account}:parameter/amplify/shared/${amplifyAppId}/OPENAI_API_KEY`,
            ]
          : []),
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
      slack: enableSlackAgent && slackEventsUrl
        ? {
            eventsUrl: slackEventsUrl,
          }
        : null,
    },
  });
  return backend;
}
