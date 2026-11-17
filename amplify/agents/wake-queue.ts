import { Duration, Stack } from "aws-cdk-lib";
import { Alarm, ComparisonOperator, Metric, TreatMissingData } from "aws-cdk-lib/aws-cloudwatch";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { CfnEventSourceMapping, type Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { Queue, QueueEncryption } from "aws-cdk-lib/aws-sqs";
import type { Construct } from "constructs";
import { assertLiteralResourceName, sanitizeAwsName } from "../site-backend-names";
import type { AgentPiece } from "./stack";

/**
 * The per-site wake queue (docs/design/always-on-agents-architecture.md, slice B1). A wake is one message; the shared procedure
 * runner is the queue's consumer, one message at a time, and holds it for the whole run. The message group is the agent plus its serial
 * scope and the deduplication id is the wake key (src/papyrus_content/agent_wakes.py builds both).
 *
 * This piece holds six resources: the queue and its dead-letter queue with one transport policy each, the alarm on the dead-letter queue,
 * and the mapping that makes the runner the consumer. `scripts/test-agents-stack.ts` prints the count and the headroom.
 *
 * What the piece does not create is any permission. The mapping reads the queue with the runner's own role, which a statement in
 * infra/procedures/papyrus-procedure-runner.yaml allows for every site's queue by name pattern (the pattern is `WAKE_QUEUE_NAME_PATTERN`).
 */

/** The shared procedure runner Lambda (infra/procedures/papyrus-procedure-runner.yaml). Every site's queue maps to it. */
export const PROCEDURE_RUNNER_FUNCTION_NAME = "papyrus-procedure-runner";

/**
 * The runner's real limits, read by the queue so the queue never invents a time of its own. `RUNNER_TIMEOUT_SECONDS` is the template's
 * `Timeout` and `RUNNER_RECORDING_MARGIN_SECONDS` is `SECONDS_KEPT_FOR_RECORDING` in procedure_runner.py: the runner keeps that long at the
 * end of its 15 minutes to record the outcome. `scripts/test-agents-stack.ts` fails if either file disagrees with these two numbers.
 */
export const RUNNER_TIMEOUT_SECONDS = 900;
export const RUNNER_RECORDING_MARGIN_SECONDS = 60;

/**
 * A message the runner is working on stays hidden for the run's whole possible length (the Lambda's 15 minutes, which already contains the
 * recording margin) plus the margin once more, so a live run is never delivered to a second runner. If the runner dies, the message comes
 * back this long after it was taken. Lambda also refuses a mapping whose queue hides messages for less than the function's timeout.
 */
export const WAKE_VISIBILITY_TIMEOUT_SECONDS = RUNNER_TIMEOUT_SECONDS + RUNNER_RECORDING_MARGIN_SECONDS;

/**
 * A wake is delivered at most twice: once to run, once to settle a run that died (slice A3). A third delivery can only mean that settling
 * itself failed, so the third receive moves the message to the dead-letter queue, whose alarm tells a person.
 */
export const WAKE_MAXIMUM_RECEIVES = 2;

/** The longest SQS keeps a message (14 days). A wake that waits is never dropped sooner. */
export const WAKE_RETENTION = Duration.days(14);

/** The site id in a queue name: lowercase letters, digits and hyphens, at most 40 (80 characters is the FIFO queue name limit). */
export const WAKE_QUEUE_SITE_ID_LENGTH = 40;

export const WAKE_QUEUE_NAME_PREFIX = "papyrus-";
export const WAKE_QUEUE_NAME_SUFFIX = "-agent-wakes.fifo";
export const WAKE_DEAD_LETTER_QUEUE_NAME_SUFFIX = "-agent-wakes-dead-letters.fifo";
/** The runner's role reads queues that match this, in its own account and region: one statement for every site. */
export const WAKE_QUEUE_NAME_PATTERN = `${WAKE_QUEUE_NAME_PREFIX}*${WAKE_QUEUE_NAME_SUFFIX}`;

export type WakeQueueNames = { queue: string; deadLetterQueue: string };

export function wakeQueueNames(brandId: string): WakeQueueNames {
  const siteId = sanitizeAwsName(brandId, WAKE_QUEUE_SITE_ID_LENGTH);
  if (siteId === "") throw new Error(`The wake queue is named after the site's brand id, which must contain a letter or digit (got ${JSON.stringify(brandId)}).`);
  return {
    queue: assertLiteralResourceName("Wake queue name", `${WAKE_QUEUE_NAME_PREFIX}${siteId}${WAKE_QUEUE_NAME_SUFFIX}`),
    deadLetterQueue: assertLiteralResourceName("Wake dead-letter queue name", `${WAKE_QUEUE_NAME_PREFIX}${siteId}${WAKE_DEAD_LETTER_QUEUE_NAME_SUFFIX}`),
  };
}

export function wakeQueueArn(brandId: string, partition: string, region: string, account: string): string {
  return `arn:${partition}:sqs:${region}:${account}:${wakeQueueNames(brandId).queue}`;
}

/**
 * Lets a site function start a procedure: it may look up and send to this site's wake queue, and nothing else. It may not read or delete
 * a message, and it may not touch another site's queue or any dead-letter queue. The queue is named by the site's brand id, so no
 * reference to the `agents` stack is made and the function's stack does not depend on it.
 */
export function allowWakeSending(lambda: LambdaFunction, brandId: string): void {
  const stack = Stack.of(lambda);
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["sqs:GetQueueUrl", "sqs:SendMessage"],
      resources: [wakeQueueArn(brandId, stack.partition, stack.region, stack.account)],
    }),
  );
}

/** The wake queue, its dead-letter queue, the alarm on the dead-letter queue and the mapping that makes the runner the consumer. */
export function wakeQueuePiece(brandId: string): AgentPiece {
  const names = wakeQueueNames(brandId);
  return {
    id: "wake-queue",
    add(scope: Construct) {
      const deadLetterQueue = new Queue(scope, "WakeDeadLetterQueue", {
        queueName: names.deadLetterQueue,
        fifo: true,
        retentionPeriod: WAKE_RETENTION,
        encryption: QueueEncryption.SQS_MANAGED,
        enforceSSL: true,
      });
      const queue = new Queue(scope, "WakeQueue", {
        queueName: names.queue,
        fifo: true, // the wake key is the deduplication id, set on each message, so no content-based deduplication
        visibilityTimeout: Duration.seconds(WAKE_VISIBILITY_TIMEOUT_SECONDS),
        retentionPeriod: WAKE_RETENTION,
        encryption: QueueEncryption.SQS_MANAGED,
        enforceSSL: true,
        deadLetterQueue: { queue: deadLetterQueue, maxReceiveCount: WAKE_MAXIMUM_RECEIVES },
      });
      // One message at a time: the runner holds it for the whole run. No maximum concurrency is set here; that is the model provider's rate limit (slice B4).
      new CfnEventSourceMapping(scope, "RunnerMapping", {
        functionName: PROCEDURE_RUNNER_FUNCTION_NAME,
        eventSourceArn: queue.queueArn,
        batchSize: 1,
        enabled: true,
      });
      // No alarm action: the account's operator listener reads every alarm on the default bus (docs/operator-alerts.md), as for every dead-letter queue.
      new Alarm(scope, "WakeDeadLetterAlarm", {
        alarmDescription: `${names.queue}: a wake the runner could not run after its second delivery is waiting in the dead-letter queue. Nothing was lost; read the message and the run record before it is moved back.`,
        metric: new Metric({
          namespace: "AWS/SQS",
          metricName: "ApproximateNumberOfMessagesVisible",
          dimensionsMap: { QueueName: deadLetterQueue.queueName },
          statistic: "Maximum",
          period: Duration.minutes(5),
        }),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: TreatMissingData.NOT_BREACHING,
      });
    },
  };
}
