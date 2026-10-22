import { Duration, RemovalPolicy, Stack } from "aws-cdk-lib";
import { Alarm, ComparisonOperator, MathExpression, Metric, TreatMissingData } from "aws-cdk-lib/aws-cloudwatch";
import { SnsAction } from "aws-cdk-lib/aws-cloudwatch-actions";
import { AttributeType, BillingMode, ProjectionType, Table, TableEncryption } from "aws-cdk-lib/aws-dynamodb";
import { ArnPrincipal, Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Key } from "aws-cdk-lib/aws-kms";
import { Topic } from "aws-cdk-lib/aws-sns";
import { LambdaSubscription } from "aws-cdk-lib/aws-sns-subscriptions";
import { Architecture, type Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SecureStringParameter } from "./secure-string-parameter";
import { pythonLambdaCode } from "../../functions/shared/python-bundle";
import type { PapyrusPlugin, PluginManifest, PluginWiringContext } from "../types";
import { resolveNewsletterConfig, type NewsletterConfig } from "./config";
import { newsletterOps } from "./ops/resource";
import { NEWSLETTER_MUTATIONS, NEWSLETTER_QUERIES, newsletterSchemaDefinitions } from "./schema";
import { newsletterFunctionName, wireSending } from "./sending";

export { resolveNewsletterConfig };
export type { NewsletterConfig };

export const NEWSLETTER_OUTPUT_KEY = "newsletter";
export const NEWSLETTER_HANDLER = "papyrus_content.newsletter.handler.handler";
/** `boto3` is bundled because the runtime's copy may predate SESv2 `Simple.Headers` (List-Unsubscribe). */
export const NEWSLETTER_REQUIREMENTS = ["PyYAML>=6.0.2,<7", "citeproc-py>=0.8.2,<1", "anthus-markus==0.7.0", "Pillow>=11.3,<12", "boto3>=1.35.8,<2"];
/** Relative to `amplify/functions/`, which is where the shared bundler looks for a function's `handler.py`. */
const FUNCTION_DIRECTORY = "../plugins/newsletter/function";

export const newsletterManifest: PluginManifest = {
  name: "newsletter",
  contract: 1,
  models: [],
  queries: NEWSLETTER_QUERIES,
  mutations: NEWSLETTER_MUTATIONS,
  guest: { mutations: [] },
  newsroomPanels: [],
  staticAssets: ["_plugins/papyrus-newsletter@1.js"],
};

let codeForTests: Code | undefined;

/** Synthesis tests swap the bundled Python asset (a pip install) for inline code. Pass nothing to restore it. */
export function overrideNewsletterCodeForTests(code?: Code): void {
  codeForTests = code;
}

export function newsletterKeyParameterName(siteId: string): string {
  return `/papyrus/${siteId}/newsletter-key`;
}

/** The SES identity ARN and configuration set ARN the function may send through. */
export function newsletterSesResources(stack: Stack, config: Pick<NewsletterConfig, "sendingDomain" | "configurationSet">): string[] {
  return [
    `arn:${stack.partition}:ses:${stack.region}:${stack.account}:identity/${config.sendingDomain}`,
    `arn:${stack.partition}:ses:${stack.region}:${stack.account}:configuration-set/${config.configurationSet}`,
  ];
}

export const BOUNCE_RATE_THRESHOLD = 0.04;
export const COMPLAINT_RATE_THRESHOLD = 0.0008;
export const ALARM_MINIMUM_SENDS = 50;

export function newsletterAlarmTopicName(siteId: string): string {
  return `papyrus-newsletter-alarms-${siteId}`;
}

/** The two alarm names; the function pauses sending only for these (python: `events.alarm_names`). */
export function newsletterAlarmNames(siteId: string): { bounce: string; complaint: string } {
  return { bounce: `papyrus-newsletter-${siteId}-bounce-rate`, complaint: `papyrus-newsletter-${siteId}-complaint-rate` };
}

/** What the function reads from its environment. Lists carry only what it needs to name them in the email. */
export function newsletterEnvironment(config: NewsletterConfig, tableName: string, keyParameter: string): Record<string, string> {
  return {
    TABLE_NAME: tableName,
    KEY_PARAMETER: keyParameter,
    SITE_ID: config.siteId,
    SITE_ORIGIN: config.siteOrigin,
    SENDING_DOMAIN: config.sendingDomain,
    FROM_ADDRESS: config.fromAddress,
    FROM_NAME: config.fromName,
    CONFIGURATION_SET: config.configurationSet,
    ITEM_URL_STYLE: config.itemUrlStyle,
    LISTS_JSON: JSON.stringify(
      config.lists.map((list) => ({
        id: list.id,
        name: list.name,
        description: list.description,
        kind: list.kind,
        // A roundup's issue type, archive section and time zone are what drafting needs; schedules and rules stay in the stack.
        ...(list.kind === "roundup" ? { issueType: list.issueType, archivePath: list.archivePath, timezone: list.schedule.timezone } : {}),
      })),
    ),
    THEME_JSON: JSON.stringify(config.theme),
    ALARM_NAMES: Object.values(newsletterAlarmNames(config.siteId)).join(","),
  };
}

export const newsletterPlugin: PapyrusPlugin<NewsletterConfig, { newsletterOps: typeof newsletterOps }> = {
  manifest: newsletterManifest,
  resolveConfig: resolveNewsletterConfig,
  functions: () => ({ newsletterOps }),
  schemaDefinitions: newsletterSchemaDefinitions,
  publicSettings: (config) => ({
    contract: newsletterManifest.contract,
    fromName: config.fromName,
    lists: config.lists.map((list) => ({
      id: list.id,
      name: list.name,
      description: list.description,
      kind: list.kind,
      // The panel needs the item type to open an issue in the editor and the archive path to show where it lands.
      ...(list.kind === "roundup" ? { issueType: list.issueType, archivePath: list.archivePath } : {}),
    })),
    theme: config.theme,
  }),
  wire(backend, config, context: PluginWiringContext) {
    const stack = Stack.of(context.createStack("newsletter"));

    const key = new Key(stack, "NewsletterKey", {
      description: `Encrypts the ${config.siteId} newsletter subscriber table`,
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const table = new Table(stack, "NewsletterTable", {
      partitionKey: { name: "pk", type: AttributeType.STRING },
      sortKey: { name: "sk", type: AttributeType.STRING },
      billingMode: BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "expiresAt",
      encryption: TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: key,
      // Point-in-time recovery stays off so that erasing a subscriber is real erasure.
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: false },
      removalPolicy: RemovalPolicy.RETAIN,
    });
    table.addGlobalSecondaryIndex({
      indexName: "byList",
      partitionKey: { name: "gsiList", type: AttributeType.STRING },
      sortKey: { name: "sk", type: AttributeType.STRING },
      projectionType: ProjectionType.KEYS_ONLY,
    });

    // Sparse: only send-ledger rows carry `gsiHid`, so erasing a subscriber finds their rows with one query, not a scan.
    table.addGlobalSecondaryIndex({
      indexName: "byHid",
      partitionKey: { name: "gsiHid", type: AttributeType.STRING },
      projectionType: ProjectionType.KEYS_ONLY,
    });

    const keyParameter = new SecureStringParameter(stack, "NewsletterKeyParameter", {
      parameterName: newsletterKeyParameterName(config.siteId),
      description: `Root key for ${config.siteId} newsletter subscriber hashing and link signing (HKDF-derived)`,
    });

    const functionDirectory = path.dirname(fileURLToPath(import.meta.url));
    // One bundle serves the `newsletter` function and the send worker; they differ in handler, timeout and IAM.
    const code = codeForTests ?? pythonLambdaCode(
      {
        functionDir: FUNCTION_DIRECTORY,
        modules: ["papyrus_content"],
        requirements: NEWSLETTER_REQUIREMENTS,
        noDeps: true,
        checkoutExtras: (outputDir) => installRequirements(path.join(functionDirectory, "function", "requirements.txt"), outputDir),
      },
      [
        "bash",
        "-c",
        [
          "set -euo pipefail",
          "mkdir -p /asset-output/papyrus_content",
          "cp amplify/plugins/newsletter/function/handler.py /asset-output/handler.py",
          "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
          "python3 -m pip install -r amplify/plugins/newsletter/function/requirements.txt -t /asset-output --no-cache-dir",
        ].join(" && "),
      ],
    );
    const environment = newsletterEnvironment(config, table.tableName, keyParameter.parameterName);
    const lambda = new LambdaFunction(stack, "NewsletterFunction", {
      functionName: newsletterFunctionName(config.siteId),
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: NEWSLETTER_HANDLER,
      // Starting a send pages the whole list and queues it, so this is longer than a signup needs.
      timeout: Duration.seconds(120),
      memorySize: 512,
      description: `Newsletter for ${config.siteId}: subscriptions, roundup drafts, approval and starting sends`,
      environment,
      code,
    });

    table.grantReadWriteData(lambda); // includes the table key's encrypt and decrypt
    lambda.addToRolePolicy(
      new PolicyStatement({ effect: Effect.ALLOW, actions: ["ssm:GetParameter"], resources: [keyParameter.parameterArn] }),
    );
    lambda.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["ses:SendEmail", "ses:SendRawEmail"],
        resources: newsletterSesResources(stack, config),
        conditions: { StringEquals: { "ses:FromAddress": config.fromAddress } },
      }),
    );
    wireSending({
      stack,
      config,
      context,
      backend,
      table,
      lambda,
      environment,
      keyParameterArn: keyParameter.parameterArn,
      sesResources: newsletterSesResources(stack, config),
      code,
    });

    // The SES configuration set's own sending switch, for the alarm pause. Nothing else of SES is writable.
    lambda.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["ses:PutConfigurationSetSendingOptions"],
        resources: [newsletterSesResources(stack, config)[1]],
      }),
    );
    // Lifting a suppression after a deliberate re-subscribe. IAM has no resource-level scope for the account list.
    lambda.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["ses:DeleteSuppressedDestination"], resources: ["*"] }));

    // SES delivery events: the topic belongs to the sending stack and is named literally.
    const eventTopic = Topic.fromTopicArn(
      stack,
      "SesEventTopic",
      `arn:${stack.partition}:sns:${stack.region}:${stack.account}:${config.eventTopicName}`,
    );
    eventTopic.addSubscription(new LambdaSubscription(lambda));

    // Bounce and complaint rate alarms over the CloudWatch event destination, 24 h period, at least 50 sends.
    const alarmTopic = new Topic(stack, "AlarmTopic", { topicName: newsletterAlarmTopicName(config.siteId) });
    alarmTopic.addSubscription(new LambdaSubscription(lambda));
    const metric = (metricName: string) =>
      new Metric({
        namespace: "AWS/SES",
        metricName,
        dimensionsMap: { "ses:configuration-set": config.configurationSet },
        statistic: "Sum",
        period: Duration.hours(24),
      });
    const names = newsletterAlarmNames(config.siteId);
    for (const [id, alarmName, metricName, threshold] of [
      ["BounceRateAlarm", names.bounce, "Bounce", BOUNCE_RATE_THRESHOLD],
      ["ComplaintRateAlarm", names.complaint, "Complaint", COMPLAINT_RATE_THRESHOLD],
    ] as const) {
      const rate = new MathExpression({
        expression: `IF(sent >= ${ALARM_MINIMUM_SENDS}, FILL(events, 0) / sent, 0)`,
        usingMetrics: { sent: metric("Send"), events: metric(metricName) },
        period: Duration.hours(24),
        label: `${metricName} rate`,
      });
      const alarm = new Alarm(stack, id, {
        alarmName,
        alarmDescription: `${metricName} rate above ${threshold * 100}% of sends in 24 hours (at least ${ALARM_MINIMUM_SENDS} sends): pauses ${config.siteId} newsletter sending`,
        metric: rate,
        threshold,
        evaluationPeriods: 1,
        comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: TreatMissingData.NOT_BREACHING,
      });
      alarm.addAlarmAction(new SnsAction(alarmTopic));
    }

    lambda.addPermission("InvokeFromCmsCompute", {
      principal: new ArnPrincipal(config.computeRoleArn),
      action: "lambda:InvokeFunction",
    });

    backend.addOutput({ custom: { [NEWSLETTER_OUTPUT_KEY]: { actionsFunction: lambda.functionName } } });
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
