import { Duration, type Stack } from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import { shortHash } from "./isolation";
import type { SharedTierPlan } from "./names";
import type { SharedStackSettings } from "./settings";

/**
 * Layer 5 of the isolation: alarms that belong to one shared stack, separate from any dedicated site's. They carry no action:
 * every CloudWatch alarm in the account reaches the operator through the default-bus listener (docs/operator-alerts.md), and
 * the alarm names start with the stack's prefix so the operator sees which tier it is.
 */

export type SharedFunctionAlarmTarget = {
  /** The function's own name, which `applySharedStackIsolation` set, so no cross-stack reference is needed. */
  functionName: string;
  /** Reserved concurrency; undefined for a function with none (an infrastructure function), which gets no concurrency alarm. */
  reserved?: number;
};

export type SharedAlarmInputs = {
  functions: SharedFunctionAlarmTarget[];
  appSyncApiId: string;
  tableNames: string[];
  /** The projection dead-letter queue's name, when the stack has a publication. */
  projectionDeadLetterQueueName?: string;
  /** The shared distribution's id, once one exists (PPY-3bbbf9); until then there is no purge to count. */
  distributionId?: string;
};

export const DYNAMODB_TABLES_PER_ALARM = 5;

const minutes = (settings: SharedStackSettings) => Duration.minutes(settings.alarms.periodMinutes);

function metricAlarm(scope: Stack, plan: SharedTierPlan, kind: string, key: string, metric: cloudwatch.IMetric, threshold: number, description: string, operator = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD) {
  return new cloudwatch.Alarm(scope, `${kind}${shortHash(key, 8)}`, {
    alarmName: `${plan.stackPrefix}-${kind}-${key.replace(new RegExp(`^${plan.stackPrefix}-`), "").slice(0, 60)}`.slice(0, 255),
    alarmDescription: description,
    metric,
    threshold,
    evaluationPeriods: 1,
    comparisonOperator: operator,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
  });
}

export function addSharedStackAlarms(scope: Stack, plan: SharedTierPlan, settings: SharedStackSettings, inputs: SharedAlarmInputs): cloudwatch.Alarm[] {
  const period = minutes(settings);
  const alarms: cloudwatch.Alarm[] = [];
  const where = `the ${plan.tier} shared stack`;

  for (const target of inputs.functions) {
    const dimensionsMap = { FunctionName: target.functionName };
    const lambdaMetric = (metricName: string, statistic: string) => new cloudwatch.Metric({ namespace: "AWS/Lambda", metricName, dimensionsMap, statistic, period });
    alarms.push(
      metricAlarm(scope, plan, "errors", target.functionName, lambdaMetric("Errors", "Sum"), settings.alarms.functionErrors,
        `${target.functionName} in ${where} returned errors.`),
      metricAlarm(scope, plan, "throttles", target.functionName, lambdaMetric("Throttles", "Sum"), settings.alarms.functionThrottles,
        `${target.functionName} in ${where} was throttled: it reached its reserved concurrency.`),
    );
    if (target.reserved !== undefined) {
      // Concurrency against the reserved share: the reservation is also this function's ceiling, so a share of it is the early warning.
      const threshold = Math.max(1, Math.ceil(target.reserved * settings.alarms.concurrencyShareOfReserved));
      alarms.push(
        metricAlarm(scope, plan, "concurrency", target.functionName, lambdaMetric("ConcurrentExecutions", "Maximum"), threshold,
          `${target.functionName} in ${where} reached ${settings.alarms.concurrencyShareOfReserved * 100}% of its reserved concurrency of ${target.reserved}.`),
      );
    }
  }

  const appSync = (metricName: string) => new cloudwatch.Metric({ namespace: "AWS/AppSync", metricName, dimensionsMap: { GraphQLAPIId: inputs.appSyncApiId }, statistic: "Sum", period });
  alarms.push(
    metricAlarm(scope, plan, "appsync-5xx", "api", appSync("5XXError"), settings.alarms.appSyncServerErrors, `The AppSync API of ${where} returned server errors.`),
    // AppSync has no throttle metric: a throttled request is answered 429 and counted in 4XXError.
    metricAlarm(scope, plan, "appsync-4xx", "api", appSync("4XXError"), settings.alarms.appSyncClientErrors, `The AppSync API of ${where} returned many client errors; throttled requests (429) are counted here.`),
  );

  for (let index = 0; index < inputs.tableNames.length; index += DYNAMODB_TABLES_PER_ALARM) {
    const chunk = inputs.tableNames.slice(index, index + DYNAMODB_TABLES_PER_ALARM);
    const usingMetrics: Record<string, cloudwatch.IMetric> = {};
    chunk.forEach((tableName, position) => {
      for (const metricName of ["ReadThrottleEvents", "WriteThrottleEvents"]) {
        usingMetrics[`m${position}${metricName[0].toLowerCase()}`] = new cloudwatch.Metric({ namespace: "AWS/DynamoDB", metricName, dimensionsMap: { TableName: tableName }, statistic: "Sum", period });
      }
    });
    const group = `group-${index / DYNAMODB_TABLES_PER_ALARM + 1}`;
    alarms.push(metricAlarm(
      scope, plan, "dynamodb-throttles", group,
      new cloudwatch.MathExpression({ expression: "SUM(METRICS())", usingMetrics, period, label: "Throttled reads and writes" }),
      settings.alarms.dynamoDbThrottledRequests, `DynamoDB throttled reads or writes on ${chunk.length} tables of ${where}.`,
    ));
  }

  if (inputs.projectionDeadLetterQueueName !== undefined) {
    alarms.push(
      metricAlarm(scope, plan, "projection-dlq", "queue",
        new cloudwatch.Metric({ namespace: "AWS/SQS", metricName: "ApproximateNumberOfMessagesVisible", dimensionsMap: { QueueName: inputs.projectionDeadLetterQueueName }, statistic: "Maximum", period }),
        settings.alarms.projectionDeadLetterMessages, `Failed projections are waiting in the dead-letter queue of ${where}.`),
    );
  }

  if (inputs.distributionId !== undefined) {
    alarms.push(
      metricAlarm(scope, plan, "purged-paths", inputs.distributionId,
        new cloudwatch.Metric({ namespace: "Papyrus/Edge", metricName: "InvalidatedPaths", dimensionsMap: { DistributionId: inputs.distributionId }, statistic: "Sum", period: Duration.days(7) }),
        settings.alarms.purgedPathsPerWeek, `The shared distribution of ${where} purged many paths in a week (billable past the free allowance).`),
    );
  }
  return alarms;
}
