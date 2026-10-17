import { Duration } from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import type { Construct } from "constructs";

export const FREE_INVALIDATION_PATHS_PER_MONTH = 1000;
export const DAYS_PER_MONTH = 30.4;
export const ALARM_WINDOW_DAYS = 7;
export const INVALIDATION_METRIC_NAMESPACE = "Papyrus/Edge";
export const INVALIDATION_METRIC_NAME = "InvalidatedPaths";

/** CloudWatch cannot alarm across more than seven days, so the monthly free allowance is checked as its weekly pace. */
export const WEEKLY_INVALIDATION_PATH_THRESHOLD = Math.round((FREE_INVALIDATION_PATHS_PER_MONTH * ALARM_WINDOW_DAYS) / DAYS_PER_MONTH);

export function addInvalidationPathAlarm(scope: Construct, id: string, distributionId: string): cloudwatch.Alarm {
  const metric = new cloudwatch.Metric({
    namespace: INVALIDATION_METRIC_NAMESPACE,
    metricName: INVALIDATION_METRIC_NAME,
    dimensionsMap: { DistributionId: distributionId },
    statistic: "Sum",
    period: Duration.days(ALARM_WINDOW_DAYS),
  });
  return new cloudwatch.Alarm(scope, id, {
    metric,
    evaluationPeriods: 1,
    threshold: WEEKLY_INVALIDATION_PATH_THRESHOLD,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    alarmDescription: `CloudFront invalidation paths on ${distributionId} are on pace to pass the ${FREE_INVALIDATION_PATHS_PER_MONTH} free paths a month.`,
  });
}
