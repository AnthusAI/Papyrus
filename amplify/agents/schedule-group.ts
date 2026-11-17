import { Duration, Stack } from "aws-cdk-lib";
import { Alarm, ComparisonOperator, Metric, TreatMissingData } from "aws-cdk-lib/aws-cloudwatch";
import { Effect, PolicyDocument, PolicyStatement, Role, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { CfnScheduleGroup } from "aws-cdk-lib/aws-scheduler";
import type { Construct } from "constructs";
import { assertLiteralResourceName, sanitizeAwsName } from "../site-backend-names";
import type { AgentPiece } from "./stack";
import { wakeQueueArn, wakeQueueNames } from "./wake-queue";

/**
 * The schedule trigger's group and the role the scheduler assumes (docs/design/always-on-agents-architecture.md, slice C1).
 *
 * Every agent that names a schedule gets one EventBridge Scheduler entry in this group, made by the deploy step (`papyrus agents schedules`,
 * src/papyrus_content/agent_definitions/schedules.py) and by nothing else: no entry is made by hand. An entry's only target is the site's wake queue, and a
 * timer does nothing but put a wake on it.
 *
 * This piece holds three resources: the group, the role the scheduler assumes (its one permission is in the role, as an inline policy) and the alarm that
 * says a tick was dropped. It creates no queue and no function: the reconciler is the deploy step, run by the site's build.
 *
 * What the role may do: send a message to this site's wake queue, and nothing else. It may not read or delete a message, touch another site's queue or
 * the dead-letter queue, or call any other service. Only the scheduler service, acting for this account, may assume it.
 */

export const SCHEDULE_GROUP_NAME_PREFIX = "papyrus-";
export const SCHEDULE_GROUP_NAME_SUFFIX = "-agent-schedules";
export const SCHEDULER_ROLE_NAME_SUFFIX = "-agent-scheduler";
/** The site id in a group or role name: lowercase letters, digits and hyphens, at most 40, so each name is at most 64 characters (the group and role limit). */
export const SCHEDULE_SITE_ID_LENGTH = 40;

export type ScheduleNames = { group: string; role: string };

export function scheduleNames(brandId: string): ScheduleNames {
  const siteId = sanitizeAwsName(brandId, SCHEDULE_SITE_ID_LENGTH);
  if (siteId === "") throw new Error(`The schedule group is named after the site's brand id, which must contain a letter or digit (got ${JSON.stringify(brandId)}).`);
  return {
    group: assertLiteralResourceName("Schedule group name", `${SCHEDULE_GROUP_NAME_PREFIX}${siteId}${SCHEDULE_GROUP_NAME_SUFFIX}`),
    role: assertLiteralResourceName("Scheduler role name", `${SCHEDULE_GROUP_NAME_PREFIX}${siteId}${SCHEDULER_ROLE_NAME_SUFFIX}`),
  };
}

/** The group, the role the scheduler assumes and the alarm on a tick that could not be delivered. */
export function scheduleGroupPiece(brandId: string): AgentPiece {
  const names = scheduleNames(brandId);
  return {
    id: "schedule-group",
    add(scope: Construct) {
      const stack = Stack.of(scope);
      new CfnScheduleGroup(scope, "ScheduleGroup", { name: names.group });
      new Role(scope, "SchedulerRole", {
        roleName: names.role,
        description: `Lets EventBridge Scheduler put a wake on ${wakeQueueNames(brandId).queue}: one permission, send to that queue.`,
        assumedBy: new ServicePrincipal("scheduler.amazonaws.com", { conditions: { StringEquals: { "aws:SourceAccount": stack.account } } }),
        inlinePolicies: {
          SendWakes: new PolicyDocument({
            statements: [
              new PolicyStatement({
                effect: Effect.ALLOW,
                actions: ["sqs:SendMessage"],
                resources: [wakeQueueArn(brandId, stack.partition, stack.region, stack.account)],
              }),
            ],
          }),
        },
      });
      // No alarm action: the account's operator listener reads every alarm on the default bus (docs/operator-alerts.md), as for every dead-letter queue.
      new Alarm(scope, "DroppedTickAlarm", {
        alarmDescription: `${names.group}: the scheduler gave up on a tick, so an agent did not wake at its time. Read the agent's schedule entry and the wake queue; the next tick is not affected.`,
        metric: new Metric({
          namespace: "AWS/Scheduler",
          metricName: "InvocationDroppedCount",
          dimensionsMap: { ScheduleGroup: names.group },
          statistic: "Sum",
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
