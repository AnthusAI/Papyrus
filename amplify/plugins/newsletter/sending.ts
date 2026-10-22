import { Duration, Stack } from "aws-cdk-lib";
import type { Table } from "aws-cdk-lib/aws-dynamodb";
import { Effect, PolicyStatement, Role, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { Architecture, type Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { SqsEventSource } from "aws-cdk-lib/aws-lambda-event-sources";
import { CfnSchedule } from "aws-cdk-lib/aws-scheduler";
import { Queue, QueueEncryption } from "aws-cdk-lib/aws-sqs";
import type { PluginWiringContext } from "../types";
import type { NewsletterConfig, RoundupList } from "./config";

export const NEWSLETTER_WORKER_HANDLER = "papyrus_content.newsletter.worker.handler";
/** The worker mails up to 50 subscribers per message at the SES send rate; the visibility timeout is six times this. */
export const WORKER_TIMEOUT_SECONDS = 180;
export const SEND_MAX_RECEIVE_COUNT = 3;
/** The schedule names the function may manage at run time: `papyrus-nl-<siteId>-<issue8>`. */
export const SCHEDULE_NAME_PREFIX = "papyrus-nl-";

export const newsletterFunctionName = (siteId: string) => `papyrus-newsletter-${siteId}`;
export const newsletterWorkerName = (siteId: string) => `papyrus-newsletter-send-${siteId}`;
export const newsletterSendQueueName = (siteId: string) => `papyrus-newsletter-send-${siteId}`;

/** The AppSync fields the `newsletter` function reads and writes through the content API (the roundup draft, the issue's Item, and the published item an alert is about). */
export const NEWSLETTER_APPSYNC_FIELDS = [
  "Query/fields/getItem",
  "Query/fields/getPublishedItem",
  "Query/fields/listPublishedItems",
  "Mutation/fields/createItem",
  "Mutation/fields/updateItem",
];

/** The only two SSM parameters that hold the postal address: the site's override and the shared default. */
export function postalAddressParameterArns(stack: Stack, siteId: string): string[] {
  return [`/papyrus/${siteId}/email/postal-address`, "/papyrus/email/postal-address"].map(
    (name) => `arn:${stack.partition}:ssm:${stack.region}:${stack.account}:parameter${name}`,
  );
}

export function scheduleArnPattern(stack: Stack, siteId: string): string {
  return `arn:${stack.partition}:scheduler:${stack.region}:${stack.account}:schedule/default/${SCHEDULE_NAME_PREFIX}${siteId}-*`;
}

export function functionArn(stack: Stack, name: string): string {
  return `arn:${stack.partition}:lambda:${stack.region}:${stack.account}:function:${name}`;
}

type SendingInputs = {
  stack: Stack;
  config: NewsletterConfig;
  context: PluginWiringContext;
  backend: any;
  table: Table;
  lambda: LambdaFunction;
  environment: Record<string, string>;
  keyParameterArn: string;
  sesResources: string[];
  code: Code;
};

/**
 * Everything that sends: the queue and its dead letter queue, the send worker, the scheduler role and the per-list
 * draft schedules, and the IAM they need. Nothing here lets the function reach anything but its own queue, its own
 * schedules (`papyrus-nl-<siteId>-*`), two postal address parameters and five content API fields.
 */
export function wireSending(inputs: SendingInputs): { queue: Queue; deadLetterQueue: Queue; worker: LambdaFunction; schedulerRole: Role } {
  const { stack, config, context, backend, table, lambda, environment, keyParameterArn, sesResources, code } = inputs;

  const deadLetterQueue = new Queue(stack, "SendDeadLetterQueue", {
    queueName: `${newsletterSendQueueName(config.siteId)}-dlq`,
    retentionPeriod: Duration.days(14),
    encryption: QueueEncryption.SQS_MANAGED,
    enforceSSL: true,
  });
  const queue = new Queue(stack, "SendQueue", {
    queueName: newsletterSendQueueName(config.siteId),
    visibilityTimeout: Duration.seconds(WORKER_TIMEOUT_SECONDS * 6),
    encryption: QueueEncryption.SQS_MANAGED,
    enforceSSL: true,
    deadLetterQueue: { queue: deadLetterQueue, maxReceiveCount: SEND_MAX_RECEIVE_COUNT },
  });

  // The role EventBridge Scheduler assumes to invoke the function, for the draft schedules and the one-time send schedules.
  const schedulerRole = new Role(stack, "SchedulerRole", {
    assumedBy: new ServicePrincipal("scheduler.amazonaws.com", { conditions: { StringEquals: { "aws:SourceAccount": stack.account } } }),
    description: `Lets EventBridge Scheduler invoke the ${config.siteId} newsletter function`,
  });
  lambda.grantInvoke(schedulerRole);

  const contentActions = context.contentActionsLambda;
  lambda.addEnvironment("FUNCTION_ARN", functionArn(stack, newsletterFunctionName(config.siteId)));
  lambda.addEnvironment("SCHEDULER_ROLE_ARN", schedulerRole.roleArn);
  lambda.addEnvironment("QUEUE_URL", queue.queueUrl);
  lambda.addEnvironment("CONTENT_ACTIONS_FUNCTION", contentActions.functionName);
  lambda.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", context.graphqlEndpoint);

  queue.grantSendMessages(lambda);
  contentActions.grantInvoke(lambda);
  lambda.addToRolePolicy(
    new PolicyStatement({ effect: Effect.ALLOW, actions: ["ssm:GetParameter"], resources: postalAddressParameterArns(stack, config.siteId) }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule"],
      resources: [scheduleArnPattern(stack, config.siteId)],
    }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["iam:PassRole"],
      resources: [schedulerRole.roleArn],
      conditions: { StringEquals: { "iam:PassedToService": "scheduler.amazonaws.com" } },
    }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["appsync:GraphQL"],
      resources: NEWSLETTER_APPSYNC_FIELDS.map(
        (field) => `arn:${stack.partition}:appsync:${stack.region}:${stack.account}:apis/${context.graphqlApiId}/types/${field}`,
      ),
    }),
  );

  const worker = new LambdaFunction(stack, "SendWorkerFunction", {
    functionName: newsletterWorkerName(config.siteId),
    runtime: Runtime.PYTHON_3_12,
    architecture: Architecture.ARM_64,
    handler: NEWSLETTER_WORKER_HANDLER,
    timeout: Duration.seconds(WORKER_TIMEOUT_SECONDS),
    memorySize: 512,
    // One message at a time, so the send rate is the account's SES rate, never a multiple of it.
    reservedConcurrentExecutions: 1,
    description: `Mails queued newsletter batches for ${config.siteId}, paced under the SES send rate`,
    environment: { ...environment, QUEUE_URL: queue.queueUrl, CONTENT_ACTIONS_FUNCTION: contentActions.functionName },
    code,
  });
  worker.addEventSource(new SqsEventSource(queue, { batchSize: 1 }));
  table.grantReadWriteData(worker);
  queue.grantSendMessages(worker);
  contentActions.grantInvoke(worker);
  worker.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["ssm:GetParameter"], resources: [keyParameterArn] }));
  worker.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["ses:SendEmail", "ses:SendRawEmail"],
      resources: sesResources,
      conditions: { StringEquals: { "ses:FromAddress": config.fromAddress } },
    }),
  );
  // GetAccount (the send rate) does not support resource-level permissions.
  worker.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["sesv2:GetAccount"], resources: ["*"] }));

  // A roundup list drafts itself on its schedule, in the schedule's own time zone.
  const roundups = config.lists.filter((list): list is RoundupList => list.kind === "roundup");
  for (const list of roundups) {
    new CfnSchedule(stack, `Draft${list.id.replace(/(^|-)([a-z0-9])/g, (_match, _dash, letter: string) => letter.toUpperCase())}`, {
      description: `Draft the ${list.id} roundup for ${config.siteId}`,
      scheduleExpression: list.schedule.draft,
      scheduleExpressionTimezone: list.schedule.timezone,
      flexibleTimeWindow: { mode: "OFF" },
      state: "ENABLED",
      target: {
        arn: lambda.functionArn,
        roleArn: schedulerRole.roleArn,
        input: JSON.stringify({ task: "assemble-roundup", listId: list.id }),
        retryPolicy: { maximumRetryAttempts: 2, maximumEventAgeInSeconds: 3600 },
      },
    });
  }

  // The newsroom operations reach the function through the thin AppSync function the plugin defines.
  const operations = backend.newsletterOps?.resources.lambda as LambdaFunction | undefined;
  if (operations) {
    const operationsStack = Stack.of(operations);
    operations.addEnvironment("NEWSLETTER_FUNCTION_NAME", newsletterFunctionName(config.siteId));
    operations.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["lambda:InvokeFunction"],
        resources: [functionArn(operationsStack, newsletterFunctionName(config.siteId))],
      }),
    );
  }
  return { queue, deadLetterQueue, worker, schedulerRole };
}
