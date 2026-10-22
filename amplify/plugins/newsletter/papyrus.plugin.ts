import { Duration, RemovalPolicy, Stack } from "aws-cdk-lib";
import { AttributeType, BillingMode, ProjectionType, Table, TableEncryption } from "aws-cdk-lib/aws-dynamodb";
import { ArnPrincipal, Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Key } from "aws-cdk-lib/aws-kms";
import { Architecture, type Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SecureStringParameter } from "./secure-string-parameter";
import { pythonLambdaCode } from "../../functions/shared/python-bundle";
import type { PapyrusPlugin, PluginManifest, PluginWiringContext } from "../types";
import { resolveNewsletterConfig, type NewsletterConfig } from "./config";
import { newsletterSchemaDefinitions } from "./schema";

export { resolveNewsletterConfig };
export type { NewsletterConfig };

export const NEWSLETTER_OUTPUT_KEY = "newsletter";
export const NEWSLETTER_HANDLER = "papyrus_content.newsletter.handler.handler";
export const NEWSLETTER_REQUIREMENTS = ["PyYAML>=6.0.2,<7", "citeproc-py>=0.8.2,<1", "anthus-markus==0.7.0", "Pillow>=11.3,<12"];
/** Relative to `amplify/functions/`, which is where the shared bundler looks for a function's `handler.py`. */
const FUNCTION_DIRECTORY = "../plugins/newsletter/function";

export const newsletterManifest: PluginManifest = {
  name: "newsletter",
  contract: 1,
  models: [],
  mutations: [],
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
    LISTS_JSON: JSON.stringify(config.lists.map(({ id, name, description, kind }) => ({ id, name, description, kind }))),
    THEME_JSON: JSON.stringify(config.theme),
  };
}

export const newsletterPlugin: PapyrusPlugin<NewsletterConfig, Record<never, never>> = {
  manifest: newsletterManifest,
  resolveConfig: resolveNewsletterConfig,
  functions: () => ({}),
  schemaDefinitions: newsletterSchemaDefinitions,
  publicSettings: (config) => ({
    contract: newsletterManifest.contract,
    fromName: config.fromName,
    lists: config.lists.map(({ id, name, description, kind }) => ({ id, name, description, kind })),
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

    const keyParameter = new SecureStringParameter(stack, "NewsletterKeyParameter", {
      parameterName: newsletterKeyParameterName(config.siteId),
      description: `Root key for ${config.siteId} newsletter subscriber hashing and link signing (HKDF-derived)`,
    });

    const functionDirectory = path.dirname(fileURLToPath(import.meta.url));
    const lambda = new LambdaFunction(stack, "NewsletterFunction", {
      runtime: Runtime.PYTHON_3_12,
      architecture: Architecture.ARM_64,
      handler: NEWSLETTER_HANDLER,
      timeout: Duration.seconds(30),
      memorySize: 512,
      description: `Newsletter subscriptions for ${config.siteId}: double opt-in signup and confirmation`,
      environment: newsletterEnvironment(config, table.tableName, keyParameter.parameterName),
      code: codeForTests ?? pythonLambdaCode(
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
      ),
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
