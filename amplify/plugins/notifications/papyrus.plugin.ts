import { Duration, RemovalPolicy, Stack } from "aws-cdk-lib";
import { Alarm, ComparisonOperator, MathExpression, Metric, TreatMissingData } from "aws-cdk-lib/aws-cloudwatch";
import { AttributeType, BillingMode, ProjectionType, Table, TableEncryption } from "aws-cdk-lib/aws-dynamodb";
import { Rule, Schedule } from "aws-cdk-lib/aws-events";
import { LambdaFunction as LambdaTarget } from "aws-cdk-lib/aws-events-targets";
import { ArnPrincipal, Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Key } from "aws-cdk-lib/aws-kms";
import { Architecture, type Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { SqsEventSource } from "aws-cdk-lib/aws-lambda-event-sources";
import type { ITable } from "aws-cdk-lib/aws-dynamodb";
import { Queue, QueueEncryption } from "aws-cdk-lib/aws-sqs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pythonLambdaCode } from "../../functions/shared/python-bundle";
import { SecureStringParameter } from "../newsletter/secure-string-parameter";
import { ALARM_MINIMUM_SENDS, BOUNCE_RATE_THRESHOLD, COMPLAINT_RATE_THRESHOLD } from "../newsletter/papyrus.plugin";
import { postalAddressParameterArns } from "../newsletter/sending";
import type { PapyrusPlugin, PluginManifest, PluginWiringContext } from "../types";
import { resolveNotificationsConfig, type NotificationsConfig } from "./config";
import { siteApiEnvironment } from "../../site-api-access";
import { X_ENDPOINTS, announcementsParameterPrefix } from "../../functions/announcements/wire";
import { ANNOUNCEMENTS_TIMEOUT_SECONDS } from "../../functions/announcements/resource";

export { resolveNotificationsConfig };
export type { NotificationsConfig };

export const NOTIFICATIONS_OUTPUT_KEY = "notifications";
export const HANDLERS = {
  router: "papyrus_content.notifications.handler.router",
  email: "papyrus_content.notifications.handler.email",
  x: "papyrus_content.notifications.handler.x",
  flush: "papyrus_content.notifications.handler.flush",
  sesEvents: "papyrus_content.notifications.handler.ses_events",
  pause: "papyrus_content.notifications.handler.pause",
} as const;
/** Caducus is pinned exactly, beside `papyrus_content`: a package change is a Caducus release, then a Papyrus release. */
export const CADUCUS_REQUIREMENT = "caducus[notify]==0.4.0";
export const NOTIFICATIONS_REQUIREMENTS = [CADUCUS_REQUIREMENT, "PyYAML>=6.0.2,<7", "citeproc-py>=0.8.2,<1", "anthus-markus==0.7.0", "Pillow>=11.3,<12"];
/** Relative to `amplify/functions/`, which is where the shared bundler looks for a function's `handler.py`. */
const FUNCTION_DIRECTORY = "../plugins/notifications/function";
export const EMAIL_TIMEOUT_SECONDS = 120;
export const EMAIL_MAX_RECEIVE_COUNT = 3;
/** One post can wait out X's rate limit inside the consumer (Caducus sleeps until `x-rate-limit-reset`), and X's windows are fifteen minutes: the Lambda maximum. */
export const X_TIMEOUT_SECONDS = 900;
export const X_MAX_RECEIVE_COUNT = 3;

export const notificationsManifest: PluginManifest = {
  name: "notifications",
  contract: 1,
  models: [],
  queries: [],
  mutations: [],
  guest: { mutations: [] },
  newsroomPanels: [],
  staticAssets: [],
};

let codeForTests: Code | undefined;

/** Synthesis tests swap the bundled Python asset (a pip install) for inline code. Pass nothing to restore it. */
export function overrideNotificationsCodeForTests(code?: Code): void {
  codeForTests = code;
}

export const notificationsFunctionName = (siteId: string) => `papyrus-notifications-${siteId}`;
export const notificationsEmailName = (siteId: string) => `papyrus-notifications-email-${siteId}`;
export const notificationsXName = (siteId: string) => `papyrus-notifications-x-${siteId}`;
export const notificationsFlushName = (siteId: string) => `papyrus-notifications-flush-${siteId}`;
export const notificationsSesEventsName = (siteId: string) => `papyrus-notifications-ses-${siteId}`;
export const notificationsPauseName = (siteId: string) => `papyrus-notifications-pause-${siteId}`;
export const notificationsTableName = (siteId: string) => `papyrus-notifications-${siteId}`;
/** The recipients of operator-class notices: a StringList an operator puts by hand, never in Git. */
export const notificationsOperatorsParameterName = (siteId: string) => `/papyrus/${siteId}/notifications/operators`;
/** Generated once by the stack; the addresses' recipient keys are derived from it. */
export const notificationsKeyParameterName = (siteId: string) => `/papyrus/${siteId}/notifications/recipient-key`;
/** Where the newsletter plugin generated its key (it is retained when that plugin is removed): read only while old newsletter links are honoured. */
export const legacyNewsletterKeyParameterName = (siteId: string) => `/papyrus/${siteId}/newsletter-key`;
export const notificationsAlarmNames = (siteId: string) => ({
  emailDeadLetters: `papyrus-notifications-${siteId}-email-dlq`,
  xDeadLetters: `papyrus-notifications-${siteId}-x-dlq`,
  routerDeadLetters: `papyrus-notifications-${siteId}-router-dlq`,
});

/** The pause alarms, created only where the newsletter plugin is absent (python: `pause.alarm_names`). */
export const notificationsPauseAlarmNames = (siteId: string) => ({
  bounce: `papyrus-notifications-${siteId}-bounce-rate`,
  complaint: `papyrus-notifications-${siteId}-complaint-rate`,
});

/** The configuration set's ARN, and the sending identity's: the email function may send through nothing else. */
export function notificationsSesResources(stack: Stack, config: Pick<NotificationsConfig, "sendingDomain" | "configurationSet">): string[] {
  return [
    `arn:${stack.partition}:ses:${stack.region}:${stack.account}:identity/${config.sendingDomain}`,
    `arn:${stack.partition}:ses:${stack.region}:${stack.account}:configuration-set/${config.configurationSet}`,
  ];
}

/** What the functions read from their environment. Lists carry only what they need to decide whether a story is covered. */
export function notificationsEnvironment(config: NotificationsConfig, names: { table: string; operators: string; key: string }): Record<string, string> {
  return {
    TABLE_NAME: names.table,
    OPERATORS_PARAMETER: names.operators,
    RECIPIENT_KEY_PARAMETER: names.key,
    SITE_ID: config.siteId,
    SITE_ORIGIN: config.siteOrigin,
    SITE_BASE_PATH: config.basePath,
    FROM_ADDRESS: config.fromAddress,
    FROM_NAME: config.fromName,
    CONFIGURATION_SET: config.configurationSet,
    ITEM_URL_STYLE: config.itemUrlStyle,
    LISTS_JSON: JSON.stringify(config.lists.map((list) => ({ id: list.id, name: list.name, description: list.description, rule: list.rule, approval: list.approval, kind: list.kind, family: list.family, cadence: list.cadence, sendAt: list.sendAt, timeZone: list.timeZone }))),
    THEME_JSON: JSON.stringify(config.theme),
    CONSENT: config.consent,
    CONFIRM_WINDOW_SECONDS: String(config.confirmWindowHours * 3600),
    METRIC_NAMESPACE: `Caducus/papyrus-${config.siteId}`,
    ...(config.legacyNewsletterLinks ? { LEGACY_NEWSLETTER_KEY_PARAMETER: legacyNewsletterKeyParameterName(config.siteId) } : {}),
  };
}

export const notificationsPlugin: PapyrusPlugin<NotificationsConfig, Record<string, never>> = {
  manifest: notificationsManifest,
  resolveConfig: resolveNotificationsConfig,
  functions: () => ({}),
  schemaDefinitions: () => ({}),
  publicSettings: (config) => ({
    contract: notificationsManifest.contract,
    fromName: config.fromName,
    // The CMS routes answer with redirects to pages under the site's base path.
    basePath: config.basePath,
    lists: config.lists.map((list) => ({ id: list.id, name: list.name, description: list.description })),
    // The subscribe form shows exactly this sentence (state kind=offered); the function refuses any other wording.
    consent: config.consent,
    theme: config.theme,
  }),
  wire(backend, config, context: PluginWiringContext) {
    const stack = Stack.of(context.createStack("notifications"));
    const operatorsParameter = notificationsOperatorsParameterName(config.siteId);

    const key = new Key(stack, "NotificationsKey", {
      description: `Encrypts the ${config.siteId} notifications table`,
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const table = new Table(stack, "NotificationsTable", {
      tableName: notificationsTableName(config.siteId),
      partitionKey: { name: "pk", type: AttributeType.STRING },
      sortKey: { name: "sk", type: AttributeType.STRING },
      billingMode: BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "expiresAt",
      encryption: TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: key,
      // Point-in-time recovery stays off so that erasing a person is real erasure.
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: false },
      removalPolicy: RemovalPolicy.RETAIN,
    });
    table.addGlobalSecondaryIndex({
      indexName: "byRecipient",
      partitionKey: { name: "recipientKey", type: AttributeType.STRING },
      sortKey: { name: "queuedAt", type: AttributeType.STRING },
      projectionType: ProjectionType.ALL,
    });
    // A list's confirmed, unsuppressed subscribers, for the page-by-page fan-out of a public kind (Caducus public audiences).
    table.addGlobalSecondaryIndex({
      indexName: "byList",
      partitionKey: { name: "gsiList", type: AttributeType.STRING },
      projectionType: ProjectionType.KEYS_ONLY,
    });
    const keyParameter = new SecureStringParameter(stack, "RecipientKeyParameter", {
      parameterName: notificationsKeyParameterName(config.siteId),
      description: `Root key for ${config.siteId} notification recipient keys and links`,
    });

    const functionDirectory = path.dirname(fileURLToPath(import.meta.url));
    // One bundle serves the four functions; they differ in handler, timeout and IAM.
    const code =
      codeForTests ??
      pythonLambdaCode(
        {
          functionDir: FUNCTION_DIRECTORY,
          modules: ["papyrus_content"],
          requirements: NOTIFICATIONS_REQUIREMENTS,
          noDeps: true,
          checkoutExtras: (outputDir) => installRequirements(path.join(functionDirectory, "function", "requirements.txt"), outputDir),
        },
        [
          "bash",
          "-c",
          [
            "set -euo pipefail",
            "mkdir -p /asset-output/papyrus_content",
            "cp amplify/plugins/notifications/function/handler.py /asset-output/handler.py",
            "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
            "python3 -m pip install -r amplify/plugins/notifications/function/requirements.txt -t /asset-output --no-cache-dir",
          ].join(" && "),
        ],
      );

    // Email: the queue, its dead letter queue, and the router's dead letter queue for failed asynchronous invocations.
    const emailDeadLetters = new Queue(stack, "EmailDeadLetterQueue", {
      queueName: `papyrus-notifications-${config.siteId}-email-dlq`,
      retentionPeriod: Duration.days(14),
      encryption: QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
    });
    const emailQueue = new Queue(stack, "EmailQueue", {
      queueName: `papyrus-notifications-${config.siteId}-email`,
      visibilityTimeout: Duration.seconds(EMAIL_TIMEOUT_SECONDS * 6),
      encryption: QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
      deadLetterQueue: { queue: emailDeadLetters, maxReceiveCount: EMAIL_MAX_RECEIVE_COUNT },
    });
    // X: its own queue, so one consumer at a time posts for the site's one account (the budget is charged one post after another), and its dead letter queue.
    const xDeadLetters = new Queue(stack, "XDeadLetterQueue", {
      queueName: `papyrus-notifications-${config.siteId}-x-dlq`,
      retentionPeriod: Duration.days(14),
      encryption: QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
    });
    const xQueue = new Queue(stack, "XQueue", {
      queueName: `papyrus-notifications-${config.siteId}-x`,
      visibilityTimeout: Duration.seconds(X_TIMEOUT_SECONDS * 6),
      encryption: QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
      deadLetterQueue: { queue: xDeadLetters, maxReceiveCount: X_MAX_RECEIVE_COUNT },
    });
    // The announcements function's model tables: the settings (pause, budget, prices), the account connection and the spend counter. The consumer has no signed-in person, so it reads and writes them with its own role.
    const announcementTables = backend.data.resources.tables as Record<string, ITable>;
    const routerDeadLetters = new Queue(stack, "RouterDeadLetterQueue", {
      queueName: `papyrus-notifications-${config.siteId}-router-dlq`,
      retentionPeriod: Duration.days(14),
      encryption: QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
    });

    const environment = {
      ...notificationsEnvironment(config, { table: table.tableName, operators: operatorsParameter, key: keyParameter.parameterName }),
      EMAIL_QUEUE_URL: emailQueue.queueUrl,
      X_QUEUE_URL: xQueue.queueUrl,
      ...X_ENDPOINTS,
      ANNOUNCEMENT_SETTINGS_TABLE: announcementTables.AnnouncementSettings.tableName,
      X_CONNECTION_TABLE: announcementTables.XConnection.tableName,
      ANNOUNCEMENT_SPEND_TABLE: announcementTables.AnnouncementSpend.tableName,
      X_REFRESH_LEASE_SECONDS: String(ANNOUNCEMENTS_TIMEOUT_SECONDS),
      ...siteApiEnvironment(context.graphqlEndpoint),
    };
    const common = { runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, code, environment };
    const router = new LambdaFunction(stack, "RouterFunction", {
      ...common,
      functionName: notificationsFunctionName(config.siteId),
      handler: HANDLERS.router,
      timeout: Duration.seconds(60),
      memorySize: 512,
      deadLetterQueue: routerDeadLetters,
      retryAttempts: 2,
      description: `Notifications for ${config.siteId}: a published story becomes one Caducus event`,
    });
    const email = new LambdaFunction(stack, "EmailFunction", {
      ...common,
      functionName: notificationsEmailName(config.siteId),
      handler: HANDLERS.email,
      timeout: Duration.seconds(EMAIL_TIMEOUT_SECONDS),
      memorySize: 512,
      // One batch at a time, so the send rate is the account's SES rate, never a multiple of it.
      reservedConcurrentExecutions: 1,
      description: `Mails queued notifications for ${config.siteId}, paced under the SES send rate`,
    });
    email.addEventSource(new SqsEventSource(emailQueue, { batchSize: 10, reportBatchItemFailures: true }));
    const x = new LambdaFunction(stack, "XFunction", {
      ...common,
      functionName: notificationsXName(config.siteId),
      handler: HANDLERS.x,
      timeout: Duration.seconds(X_TIMEOUT_SECONDS),
      memorySize: 512,
      // One post at a time: the budget is charged one post after another, and a post whose outcome is unknown is checked before it is repeated.
      reservedConcurrentExecutions: 1,
      description: `Posts queued announcements for ${config.siteId} to its connected X account`,
    });
    x.addEventSource(new SqsEventSource(xQueue, { batchSize: 1, reportBatchItemFailures: true }));
    const flush = new LambdaFunction(stack, "FlushFunction", {
      ...common,
      functionName: notificationsFlushName(config.siteId),
      handler: HANDLERS.flush,
      timeout: Duration.seconds(60),
      memorySize: 256,
      reservedConcurrentExecutions: 1,
      description: `Sends the ${config.siteId} notifications whose grouping window ended`,
    });
    new Rule(stack, "FlushSchedule", {
      description: `Every minute: send ${config.siteId} notification groups that are due`,
      schedule: Schedule.rate(Duration.minutes(1)),
      targets: [new LambdaTarget(flush)],
    });
    const sesEvents = new LambdaFunction(stack, "SesEventsFunction", {
      ...common,
      functionName: notificationsSesEventsName(config.siteId),
      handler: HANDLERS.sesEvents,
      timeout: Duration.seconds(30),
      memorySize: 256,
      description: `Records SES events of the ${config.siteId} configuration set for mail this site sent`,
    });
    // Default bus. Only mail this site tagged with a delivery id: the newsletter shares the configuration set and is not ours.
    new Rule(stack, "SesEventsRule", {
      description: `SES events for ${config.siteId} notification mail`,
      eventPattern: {
        source: ["aws.ses"],
        detail: { mail: { tags: { "ses:configuration-set": [config.configurationSet], delivery: [{ exists: true }] as unknown as string[], site: [config.siteId] } } },
      },
      targets: [new LambdaTarget(sesEvents)],
    });

    const parameterArns = [
      `arn:${stack.partition}:ssm:${stack.region}:${stack.account}:parameter${operatorsParameter}`,
      keyParameter.parameterArn,
    ];
    // Old newsletter links (dated; legacy_links.py): every function builds the same runtime, so each may read the old key.
    if (config.legacyNewsletterLinks) {
      parameterArns.push(`arn:${stack.partition}:ssm:${stack.region}:${stack.account}:parameter${legacyNewsletterKeyParameterName(config.siteId)}`);
    }
    // Every function builds the same runtime (the audience needs the recipient key), and the SES events suppress readers.
    for (const fn of [router, email, x, flush, sesEvents]) {
      table.grantReadWriteData(fn); // includes the table key's encrypt and decrypt
      fn.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["ssm:GetParameter"], resources: parameterArns }));
    }
    // A reader who lifts a bounce or complaint by opting in again is cleared from the SES account suppression list too.
    // The action has no resource-level form (as for the newsletter function).
    router.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["ses:DeleteSuppressedDestination"], resources: ["*"] }));
    // The X consumer reads the account's connection, its token parameters (a refresh saves the next one), the settings and the spend counter, and nothing else of the site's.
    announcementTables.AnnouncementSettings.grantReadData(x);
    announcementTables.XConnection.grantReadWriteData(x); // a refresh takes the connection's lease and records its result
    announcementTables.AnnouncementSettings.grantReadWriteData(x); // a refresh X refuses pauses announcements
    announcementTables.AnnouncementSpend.grantReadWriteData(x);
    x.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["ssm:GetParameter", "ssm:PutParameter"],
        resources: [`arn:${stack.partition}:ssm:${stack.region}:${stack.account}:parameter${announcementsParameterPrefix(config.siteId)}/*`],
      }),
    );
    xQueue.grantSendMessages(router);
    emailQueue.grantSendMessages(router);
    emailQueue.grantSendMessages(flush);
    emailQueue.grantSendMessages(email); // a fan-out page queues its deliveries and the next page
    router.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["appsync:GraphQL"],
        resources: [`arn:${stack.partition}:appsync:${stack.region}:${stack.account}:apis/${context.graphqlApiId}/types/Query/fields/getPublishedItem`],
      }),
    );
    email.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["ses:SendEmail", "ses:SendRawEmail"],
        resources: notificationsSesResources(stack, config),
        conditions: { StringEquals: { "ses:FromAddress": config.fromAddress } },
      }),
    );
    // GetAccount (the send rate) does not support resource-level permissions.
    email.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["ses:GetAccount"], resources: ["*"] }));
    // The postal address for the footer of public-class mail: the same two parameters as the newsletter's.
    email.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["ssm:GetParameter"], resources: postalAddressParameterArns(stack, config.siteId) }));

    // Without the newsletter plugin nobody else watches the set's reputation: the same two rate alarms, and a function that
    // turns sending off for the set when either enters ALARM. With it, the newsletter owns both and a send on a paused set
    // is simply refused (and logged `failed`). No alarm action: the account's operator listener tells admins.
    if (!context.enabledPlugins.includes("newsletter")) {
      const pauseNames = notificationsPauseAlarmNames(config.siteId);
      const rate = (metricName: string) =>
        new Metric({
          namespace: "AWS/SES",
          metricName,
          dimensionsMap: { "ses:configuration-set": config.configurationSet },
          statistic: "Sum",
          period: Duration.hours(24),
        });
      for (const [id, alarmName, metricName, threshold] of [
        ["BounceRateAlarm", pauseNames.bounce, "Bounce", BOUNCE_RATE_THRESHOLD],
        ["ComplaintRateAlarm", pauseNames.complaint, "Complaint", COMPLAINT_RATE_THRESHOLD],
      ] as const) {
        new Alarm(stack, id, {
          alarmName,
          alarmDescription: `${metricName} rate above ${threshold * 100}% of sends in 24 hours (at least ${ALARM_MINIMUM_SENDS} sends): pauses ${config.siteId} notification sending`,
          metric: new MathExpression({
            expression: `IF(sent >= ${ALARM_MINIMUM_SENDS}, FILL(events, 0) / sent, 0)`,
            usingMetrics: { sent: rate("Send"), events: rate(metricName) },
            period: Duration.hours(24),
            label: `${metricName} rate`,
          }),
          threshold,
          evaluationPeriods: 1,
          comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
          treatMissingData: TreatMissingData.NOT_BREACHING,
        });
      }
      const pause = new LambdaFunction(stack, "PauseFunction", {
        ...common,
        functionName: notificationsPauseName(config.siteId),
        handler: HANDLERS.pause,
        timeout: Duration.seconds(30),
        memorySize: 256,
        description: `Turns off sending for the ${config.siteId} configuration set when a rate alarm fires`,
      });
      new Rule(stack, "PauseRule", {
        description: `The ${config.siteId} bounce or complaint rate alarm entered ALARM`,
        eventPattern: {
          source: ["aws.cloudwatch"],
          detailType: ["CloudWatch Alarm State Change"],
          detail: { alarmName: [pauseNames.bounce, pauseNames.complaint], state: { value: ["ALARM"] } },
        },
        targets: [new LambdaTarget(pause)],
      });
      // The set's own sending switch; nothing else of SES is writable.
      pause.addToRolePolicy(
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: ["ses:PutConfigurationSetSendingOptions"],
          resources: [notificationsSesResources(stack, config)[1]],
        }),
      );
    }

    // One alarm on each dead letter queue. No alarm action: the account's operator listener reads every alarm on the default bus.
    const alarmNames = notificationsAlarmNames(config.siteId);
    for (const [id, alarmName, queue] of [
      ["EmailDeadLetterAlarm", alarmNames.emailDeadLetters, emailDeadLetters],
      ["XDeadLetterAlarm", alarmNames.xDeadLetters, xDeadLetters],
      ["RouterDeadLetterAlarm", alarmNames.routerDeadLetters, routerDeadLetters],
    ] as const) {
      new Alarm(stack, id, {
        alarmName,
        alarmDescription: `${config.siteId} notifications: a message is waiting in ${queue.queueName}`,
        metric: new Metric({
          namespace: "AWS/SQS",
          metricName: "ApproximateNumberOfMessagesVisible",
          dimensionsMap: { QueueName: queue.queueName },
          statistic: "Maximum",
          period: Duration.minutes(5),
        }),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: TreatMissingData.NOT_BREACHING,
      });
    }

    // The CMS routes are the only caller: a publish tells this function nothing (the announce agent is woken by the Item change feed).
    router.addPermission("InvokeFromCmsCompute", { principal: new ArnPrincipal(config.computeRoleArn), action: "lambda:InvokeFunction" });

    backend.addOutput({ custom: { [NOTIFICATIONS_OUTPUT_KEY]: { actionsFunction: router.functionName, xQueueUrl: xQueue.queueUrl } } });
  },
};

function installRequirements(requirementsPath: string, outputDir: string): void {
  // Same wheels and platform as the other Python functions: a Lambda on arm64 with CPython 3.12.
  execFileSync(
    "python3",
    [
      "-m", "pip", "install", "-r", requirementsPath, "-t", outputDir, "--no-cache-dir",
      "--platform", "manylinux2014_aarch64", "--implementation", "cp", "--python-version", "3.12",
      "--only-binary=:all:", "--ignore-requires-python",
    ],
    { stdio: "inherit" },
  );
}
