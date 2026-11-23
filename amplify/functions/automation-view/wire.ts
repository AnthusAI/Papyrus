import { Stack } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import {
  MONITORING_TABLE_PARAMETER,
  MONITORING_VIEW_TABLE_ACTIONS,
  monitoringViewParameterArn,
  monitoringViewTableArns,
} from "../monitoring-view/wire";
import { connectToSiteApi } from "../../site-api-access";
import { allowWakeSending } from "../../agents/wake-queue";
import { PUBLICATION_TIME_ZONE_ENV } from "../../publication/scheduled-publishing";

/** The fields the function calls on its own site's API with its own role. Today reads the day's runs through the status index, the agents through the tenant index, an agent's run history through the automation index (PPY-577310),
 *  and the day's email sends through the released-Announcements index, each one's Deliveries and its `announces` links. Today's top (PPY-b6d5ad) reads the open review requests through the state index,
 *  the runs that need a person through the attention index, the Deliveries due through the due index and the Stories scheduled to publish through the schedule index. Wake now on an
 *  Overdue record (PPY-97180c) reads that one Delivery or review request by its id. Its one write is `updateProcedureRun`, which acknowledging or settling a run makes (it clears the
 *  run's attention key and records who and when). */
export const AUTOMATION_VIEW_FUNCTION_FIELDS = [
  "Query/fields/getAutomation",
  "Query/fields/getDelivery",
  "Query/fields/getNewsroomProcedureDefinition",
  "Query/fields/getProcedureRun",
  "Query/fields/getReviewRequest",
  "Query/fields/listAnnouncementDecisionsByStateAndReleaseAt",
  "Query/fields/listAutomations",
  "Query/fields/listAutomationsByTenant",
  "Query/fields/listDeliveriesByAnnouncementAndCreatedAt",
  "Query/fields/listDeliveriesByDueKeyAndDueAt",
  "Query/fields/listItemsByScheduleStateAndScheduledPublishAt",
  "Query/fields/listProcedureRunsByAttentionKeyAndDueAt",
  "Query/fields/listProcedureRunsByAutomationAndRequestedAt",
  "Query/fields/listProcedureRunsByProcedureAndRequestedAt",
  "Query/fields/listProcedureRunsByStatusAndRequestedAt",
  "Query/fields/listReviewRequestsByReviewStateKeyAndUpdatedAt",
  "Query/fields/listSemanticRelationsBySubjectState",
  "Mutation/fields/updateProcedureRun",
];

/** Run now writes one row of its own to the monitoring table, in a monitor's partition (`MONITOR#<id>`), and nothing else. */
export const AUTOMATION_RUN_NOW_TABLE_ACTIONS = ["dynamodb:PutItem"];
export const AUTOMATION_RUN_NOW_LEADING_KEYS = ["MONITOR#*"];

/**
 * Environment and least-privilege IAM for the automation-view function: a few read fields of the site's own API and the one write acknowledging a run makes,
 * the same read-only grant on the monitoring table that the Monitoring page has, one PutItem for Run now's row,
 * and permission to put a wake on the site's own wake queue (Run now, wake now). A site outside the
 * monitoring account finds no parameter and the page lists its records without runs.
 *
 * Wake now on an Overdue Delivery or soft review deadline (PPY-97180c) sends that record's own follow-up timer wake, which names where the runner finds the site's agent
 * policy: so a dedicated site with a tenant also gives the function the names its timers are built from, as the image service has them. It sets no timer.
 */
export type AutomationViewFollowUps = { tenantId: string };

export function wireAutomationView(backend: any, brandId: string, publicationTimeZone?: string, followUps?: AutomationViewFollowUps): void {
  const lambda = backend.automationView.resources.lambda as LambdaFunction;
  const stack = Stack.of(lambda);
  connectToSiteApi(lambda, backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl as string);
  // Today shows the day and its due times in the site's own time zone, the publication.timeZone scheduled publishing uses.
  if (publicationTimeZone !== undefined) lambda.addEnvironment(PUBLICATION_TIME_ZONE_ENV, publicationTimeZone);
  lambda.addEnvironment("PAPYRUS_MONITORING_TABLE_PARAMETER", MONITORING_TABLE_PARAMETER);
  const apiId = backend.data.resources.graphqlApi.apiId as string;
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["appsync:GraphQL"],
      resources: AUTOMATION_VIEW_FUNCTION_FIELDS.map((field) => `arn:aws:appsync:${stack.region}:${stack.account}:apis/${apiId}/types/${field}`),
    }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["ssm:GetParameter"],
      resources: [monitoringViewParameterArn(stack.region, stack.account)],
    }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: MONITORING_VIEW_TABLE_ACTIONS,
      resources: monitoringViewTableArns(stack.region, stack.account),
    }),
  );
  lambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: AUTOMATION_RUN_NOW_TABLE_ACTIONS,
      resources: monitoringViewTableArns(stack.region, stack.account).slice(0, 1),
      conditions: { "ForAllValues:StringLike": { "dynamodb:LeadingKeys": AUTOMATION_RUN_NOW_LEADING_KEYS } },
    }),
  );
  allowWakeSending(lambda, brandId);
  if (followUps !== undefined && followUps.tenantId !== "") {
    lambda.addEnvironment("PAPYRUS_AGENT_PUBLICATION_ID", brandId);
    // The tenant goes on each wake only: PAPYRUS_TENANT_ID would make the function read as that tenant, which it does not today.
    lambda.addEnvironment("PAPYRUS_AGENT_TENANT_ID", followUps.tenantId);
    lambda.addEnvironment("PAPYRUS_SITE_BUCKET", backend.storage.resources.bucket.bucketName);
    lambda.addEnvironment("PAPYRUS_AWS_ACCOUNT_ID", stack.account);
    lambda.addEnvironment("PAPYRUS_AWS_PARTITION", stack.partition);
  }
}
