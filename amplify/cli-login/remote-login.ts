import { Annotations, Duration, Fn, RemovalPolicy, type Stack } from "aws-cdk-lib";
import { Alarm, ComparisonOperator, Metric, TreatMissingData } from "aws-cdk-lib/aws-cloudwatch";
import { AttributeType, BillingMode, Table, TableEncryption } from "aws-cdk-lib/aws-dynamodb";
import { Effect, ManagedPolicy, PolicyStatement, Role, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { Architecture, CfnPermission, CfnUrl, Function as LambdaFunction, type Code, Runtime } from "aws-cdk-lib/aws-lambda";
import { SnsAction } from "aws-cdk-lib/aws-cloudwatch-actions";
import { Topic } from "aws-cdk-lib/aws-sns";
import { FilterPattern, LogGroup, MetricFilter, RetentionDays } from "aws-cdk-lib/aws-logs";

/** The pages the broker's approval URL and callback name. Fixed by the cli-login protocol. */
export const CLI_APPROVE_PATH = "/cli/approve";
export const CLI_CALLBACK_PATH = "/cli/callback";

export type CliRemoteLoginPlan = {
  /** The site's public https origin: where the pages are served and the Cognito callback is registered. */
  origin: string;
  approvalUrl: string;
  callbackUri: string;
  /** The Amplify compute role the site's Next.js app runs as; it alone may invoke the pages function. */
  invokerRoleArn: string;
};

/**
 * `papyrus login --remote` is off unless a site turns it on. With it off this returns nothing, and nothing else in the
 * backend (no broker, no pages function, no Cognito callback, no output) changes.
 */
export function planCliRemoteLogin(enabled: boolean, environment: Record<string, string | undefined>): CliRemoteLoginPlan | undefined {
  if (!enabled) return undefined;
  const originText = (environment.PAPYRUS_SITE_ORIGIN ?? "").trim();
  let origin: URL;
  try {
    origin = new URL(originText);
  } catch {
    throw new Error("Remote CLI login needs PAPYRUS_SITE_ORIGIN, the site's public https origin.");
  }
  if (origin.protocol !== "https:" || origin.pathname !== "/" || origin.search !== "" || origin.username !== "") {
    throw new Error(`Remote CLI login needs PAPYRUS_SITE_ORIGIN to be a plain https origin, got ${originText}.`);
  }
  const invokerRoleArn = (environment.PAPYRUS_CLI_INVOKER_ROLE_ARN ?? "").trim();
  if (!/^arn:aws[a-z-]*:iam::\d{12}:role\/.+$/.test(invokerRoleArn)) {
    throw new Error("Remote CLI login needs PAPYRUS_CLI_INVOKER_ROLE_ARN, the ARN of the site's Amplify compute role (the app-shell stack sets it when cms.cliRemoteLogin is true).");
  }
  return {
    origin: origin.origin,
    approvalUrl: `${origin.origin}${CLI_APPROVE_PATH}`,
    callbackUri: `${origin.origin}${CLI_CALLBACK_PATH}`,
    invokerRoleArn,
  };
}

export type CliRemoteLoginProps = {
  plan: CliRemoteLoginPlan;
  /** The Cognito app client the CLI signs in with (the one `papyrus-cli.json` publishes). */
  clientId: string;
  /** The API the CLI signs in to; the broker serves only this target. */
  graphqlEndpoint: string;
  /** The Cognito hosted UI's `/oauth2/authorize` URL. */
  authorizeEndpoint: string;
  /** The site's name on the approval page. */
  product: string;
  brokerCode: Code;
  pagesCode: Code;
  /** The site's alarm topic. Both broker alarms notify it on alarm and on recovery; without it nobody is notified and synth warns. */
  alarmTopicArn?: string;
  /** The most broker invocations at once; bounds what an abusive caller can cost. */
  reservedConcurrency?: number;
};

export type CliRemoteLogin = {
  brokerEndpoint: string;
  brokerFunctionArn: string;
  pagesFunctionArn: string;
  remoteCallbackUri: string;
};

/**
 * One cli-login broker for the site, ported from cli-login's infra/broker.yaml with its security properties kept:
 * - the function URL takes no credentials, and the public permission covers only calls through that URL;
 * - the private operations (describe, bind, complete, deny) may be invoked only by the pages function's role;
 * - the broker may read and write only its own table, and its concurrency is reserved;
 * - a start-ceiling metric filter (no dimensions) feeds an alarm, and so does throttling.
 * Plus the approval pages function, run from the same pinned cli-login release, that only the site's compute role may invoke.
 */
export function addCliRemoteLogin(stack: Stack, props: CliRemoteLoginProps): CliRemoteLogin {
  const transactions = new Table(stack, "Transactions", {
    partitionKey: { name: "pk", type: AttributeType.STRING },
    billingMode: BillingMode.PAY_PER_REQUEST,
    timeToLiveAttribute: "expires_at",
    encryption: TableEncryption.AWS_MANAGED,
    removalPolicy: RemovalPolicy.DESTROY,
  });

  const brokerRole = new Role(stack, "BrokerRole", {
    assumedBy: new ServicePrincipal("lambda.amazonaws.com"),
    managedPolicies: [ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole")],
  });
  brokerRole.addToPolicy(new PolicyStatement({
    effect: Effect.ALLOW,
    actions: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"],
    resources: [transactions.tableArn],
  }));

  const brokerLogs = new LogGroup(stack, "BrokerLogs", { retention: RetentionDays.ONE_MONTH, removalPolicy: RemovalPolicy.DESTROY });
  const broker = new LambdaFunction(stack, "Broker", {
    runtime: Runtime.PYTHON_3_12,
    architecture: Architecture.ARM_64,
    handler: "cli_login.broker.handler.lambda_handler",
    code: props.brokerCode,
    role: brokerRole,
    timeout: Duration.seconds(10),
    memorySize: 256,
    reservedConcurrentExecutions: props.reservedConcurrency ?? 10,
    logGroup: brokerLogs,
    environment: {
      BROKER_TABLE: transactions.tableName,
      BROKER_CLIENT_ID: props.clientId,
      BROKER_TARGETS: Fn.join("", ['["', props.graphqlEndpoint, '"]']),
      BROKER_APPROVAL_URL: props.plan.approvalUrl,
      BROKER_CALLBACK_URI: props.plan.callbackUri,
    },
  });

  const brokerUrl = new CfnUrl(stack, "BrokerUrl", { targetFunctionArn: broker.functionArn, authType: "NONE" });
  new CfnPermission(stack, "PublicUrlPermission", {
    functionName: broker.functionName, action: "lambda:InvokeFunctionUrl", principal: "*", functionUrlAuthType: "NONE",
  });
  new CfnPermission(stack, "PublicUrlInvokePermission", {
    functionName: broker.functionName, action: "lambda:InvokeFunction", principal: "*", invokedViaFunctionUrl: true,
  });

  const pagesLogs = new LogGroup(stack, "PagesLogs", { retention: RetentionDays.ONE_MONTH, removalPolicy: RemovalPolicy.DESTROY });
  const pages = new LambdaFunction(stack, "Pages", {
    runtime: Runtime.PYTHON_3_12,
    architecture: Architecture.ARM_64,
    handler: "handler.handler",
    code: props.pagesCode,
    timeout: Duration.seconds(10),
    memorySize: 256,
    logGroup: pagesLogs,
    environment: {
      BROKER_FUNCTION_ARN: broker.functionArn,
      AUTHORIZE_ENDPOINT: props.authorizeEndpoint,
      PRODUCT: props.product,
      PRIVILEGES: "read and change this site's newsroom content as you, with your newsroom role, until you sign out",
      IDENTITY_PROVIDER: "Google",
    },
  });
  new CfnPermission(stack, "PagesInvokePermission", {
    functionName: broker.functionName, action: "lambda:InvokeFunction", principal: pages.role!.roleArn,
  });
  new CfnPermission(stack, "SiteInvokePagesPermission", {
    functionName: pages.functionName, action: "lambda:InvokeFunction", principal: props.plan.invokerRoleArn,
  });

  new MetricFilter(stack, "StartCeilingFilter", {
    logGroup: brokerLogs,
    filterPattern: FilterPattern.literal('{ $.event = "cli_login_start_ceiling" }'),
    metricNamespace: "cli-login",
    metricName: "StartCeilingReached",
    metricValue: "1",
    defaultValue: 0,
  });
  const startCeilingAlarm = new Alarm(stack, "StartCeilingAlarm", {
    alarmDescription: "The cli-login broker refused starts at its ceiling across all callers (a flood from many addresses)",
    metric: new Metric({ namespace: "cli-login", metricName: "StartCeilingReached", statistic: "Sum", period: Duration.minutes(5) }),
    evaluationPeriods: 1,
    threshold: 0,
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });
  const throttledAlarm = new Alarm(stack, "ThrottledAlarm", {
    alarmDescription: "The cli-login broker is being throttled at its reserved concurrency",
    metric: broker.metricThrottles({ statistic: "Sum", period: Duration.minutes(5) }),
    evaluationPeriods: 1,
    threshold: 0,
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });

  if (props.alarmTopicArn) {
    const alarmAction = new SnsAction(Topic.fromTopicArn(stack, "AlarmTopic", props.alarmTopicArn));
    for (const alarm of [startCeilingAlarm, throttledAlarm]) {
      alarm.addAlarmAction(alarmAction);
      alarm.addOkAction(alarmAction);
    }
  } else {
    Annotations.of(stack).addWarning(
      "The remote-login broker alarms (StartCeilingAlarm, ThrottledAlarm) notify nobody: set cms.alarmTopicArn in the site's app-shell site.json (PAPYRUS_ALARM_TOPIC_ARN) to an SNS topic ARN.",
    );
  }

  return {
    brokerEndpoint: brokerUrl.attrFunctionUrl,
    brokerFunctionArn: broker.functionArn,
    pagesFunctionArn: pages.functionArn,
    remoteCallbackUri: props.plan.callbackUri,
  };
}
