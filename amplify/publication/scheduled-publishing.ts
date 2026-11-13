import { Duration, Stack } from "aws-cdk-lib";
import { Alarm, ComparisonOperator, Metric, TreatMissingData } from "aws-cdk-lib/aws-cloudwatch";
import { Effect, PolicyStatement, Role, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { Queue, QueueEncryption } from "aws-cdk-lib/aws-sqs";
import { isIanaTimeZone } from "../site-backend-config";

/**
 * Scheduled publishing (docs/scheduled-publishing.md): every scheduled Story version gets one EventBridge Scheduler one-off schedule named
 * `papyrus-pub-<siteId>-<digest of the version id>` that invokes content-actions at the scheduled time. This wires what the function needs:
 * the role Scheduler assumes (invoke this function, nothing else), the dead letter queue for events Scheduler cannot deliver, an alarm on
 * that queue, the function's permission to manage schedules under the site's name prefix (and to pass the role), and the settings the function reads.
 */

export const SCHEDULE_NAME_PREFIX = "papyrus-pub-";
/** A schedule name is at most 64 characters: the prefix, the site id, a dash and the 16-character digest. */
export const SCHEDULE_NAME_DIGEST_LENGTH = 16;
const SCHEDULE_NAME_LIMIT = 64;
export const MAXIMUM_SITE_ID_LENGTH = SCHEDULE_NAME_LIMIT - SCHEDULE_NAME_PREFIX.length - 1 - SCHEDULE_NAME_DIGEST_LENGTH;

export const PUBLICATION_TIME_ZONE_ENV = "PAPYRUS_PUBLICATION_TIME_ZONE";
export const SCHEDULER_ROLE_ARN_ENV = "PAPYRUS_SCHEDULER_ROLE_ARN";
export const SCHEDULER_DEAD_LETTER_ARN_ENV = "PAPYRUS_SCHEDULER_DEAD_LETTER_ARN";
export const SCHEDULE_NAME_PREFIX_ENV = "PAPYRUS_SCHEDULE_NAME_PREFIX";

export function scheduleNamePrefix(siteId: string): string {
  if (!/^[a-z0-9][a-z0-9-]*$/.test(siteId) || siteId.length > MAXIMUM_SITE_ID_LENGTH) {
    throw new Error(`Scheduled publishing names its schedules after the site id, which must be 1-${MAXIMUM_SITE_ID_LENGTH} lowercase letters, digits or hyphens (got ${JSON.stringify(siteId)}).`);
  }
  return `${SCHEDULE_NAME_PREFIX}${siteId}-`;
}

export type ScheduledPublishing = { schedulerRole: Role; deadLetterQueue: Queue; alarm: Alarm; namePrefix: string };

export function addScheduledPublishing(lambda: LambdaFunction, options: { siteId: string; timeZone: string }): ScheduledPublishing {
  if (!isIanaTimeZone(options.timeZone)) {
    throw new Error(`publication.timeZone must be an IANA time zone name such as America/New_York (got ${JSON.stringify(options.timeZone)}).`);
  }
  const namePrefix = scheduleNamePrefix(options.siteId);
  // Everything lives in the function's own stack: the function's settings name the role and the queue, and the role's policy names the function, so a
  // second stack would make the two depend on each other.
  const stack = Stack.of(lambda);

  const deadLetterQueue = new Queue(stack, "ScheduledPublishingDeadLetterQueue", {
    retentionPeriod: Duration.days(14),
    encryption: QueueEncryption.SQS_MANAGED,
    enforceSSL: true,
  });
  const schedulerRole = new Role(stack, "ScheduledPublishingSchedulerRole", {
    assumedBy: new ServicePrincipal("scheduler.amazonaws.com", { conditions: { StringEquals: { "aws:SourceAccount": stack.account } } }),
    description: `Lets EventBridge Scheduler publish scheduled Stories on ${options.siteId}: it may invoke the content-actions function and send undeliverable events to the dead letter queue.`,
  });
  lambda.grantInvoke(schedulerRole);
  deadLetterQueue.grantSendMessages(schedulerRole);

  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule"],
      resources: [`arn:${stack.partition}:scheduler:${stack.region}:${stack.account}:schedule/default/${namePrefix}*`],
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
  lambda.addEnvironment(PUBLICATION_TIME_ZONE_ENV, options.timeZone);
  lambda.addEnvironment(SCHEDULER_ROLE_ARN_ENV, schedulerRole.roleArn);
  lambda.addEnvironment(SCHEDULER_DEAD_LETTER_ARN_ENV, deadLetterQueue.queueArn);
  lambda.addEnvironment(SCHEDULE_NAME_PREFIX_ENV, namePrefix);

  // One alarm on the queue, no alarm action: the account's operator listener reads every alarm on the default bus (as for every dead letter queue).
  const alarm = new Alarm(stack, "ScheduledPublishingDeadLetterAlarm", {
    alarmDescription: `${options.siteId}: a scheduled publish could not be delivered and is waiting in the dead letter queue. The Story shows as Overdue in the newsroom.`,
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
  return { schedulerRole, deadLetterQueue, alarm, namePrefix };
}
