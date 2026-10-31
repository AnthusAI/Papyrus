import { Duration, Stack } from "aws-cdk-lib";
import { StreamViewType, type CfnTable } from "aws-cdk-lib/aws-dynamodb";
import { Rule, RuleTargetInput, Schedule } from "aws-cdk-lib/aws-events";
import { LambdaFunction as LambdaFunctionTarget } from "aws-cdk-lib/aws-events-targets";
import { Effect, PolicyStatement, Role, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { CfnEventSourceMapping, type Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { PROJECTION_LOCK_TABLE_NAME, projectionLeaseTableArn } from "../../publication/projection-lease";
import type { PapyrusPlugin, PluginManifest, PluginWiringContext } from "../types";
import { resolveHomePageConfig, type HomePageConfig } from "./config";
import { homePageTrigger } from "./function/resource";

export { resolveHomePageConfig };
export type { HomePageConfig };

export const HOME_PAGE_SNAPSHOT_SCHEDULE_PREFIX = "papyrus-home-page-snapshot-";
export const HOME_PAGE_SNAPSHOT_TASK = { projectionTask: { task: "home-page-snapshot" } };
export const HOME_PAGE_STREAM_BATCH_SIZE = 100;
export const HOME_PAGE_STREAM_BATCH_WINDOW_SECONDS = 10;
export const HOME_PAGE_STREAM_RETRY_ATTEMPTS = 2;
const MINUTES_PER_HOUR = 60;

export const homePageManifest: PluginManifest = {
  name: "home-page",
  contract: 1,
  models: [],
  mutations: [],
  guest: { mutations: [] },
  newsroomPanels: [],
  staticAssets: [],
};

/**
 * Lambda event filter for the Reference stream: a record that carries a curation status (an insert or a change) or a REMOVE, which has
 * no new image. The handler then compares the six public fields itself.
 */
export function homePageStreamFilterPattern(): string {
  return JSON.stringify({
    $or: [{ eventName: ["REMOVE"] }, { dynamodb: { NewImage: { curationStatus: { S: [{ exists: true }] } } } }],
  });
}

function referenceCfnTable(backend: any): CfnTable {
  const cfnTables = backend.data.resources.cfnResources.cfnTables as Record<string, CfnTable>;
  const found =
    cfnTables.Reference ??
    cfnTables.ReferenceTable ??
    Object.entries(cfnTables).find(([key]) => key.toLowerCase().replace(/table$/, "") === "reference")?.[1];
  if (!found) throw new Error(`The home-page plugin needs the Reference table. cfnTables=${Object.keys(cfnTables).join(",")}`);
  return found;
}

function intervalRate(hours: number): Duration {
  return Number.isInteger(hours) ? Duration.hours(hours) : Duration.minutes(Math.round(hours * MINUTES_PER_HOUR));
}

export const homePagePlugin: PapyrusPlugin<HomePageConfig, { homePageTrigger: typeof homePageTrigger }> = {
  manifest: homePageManifest,
  resolveConfig: resolveHomePageConfig,
  functions: () => ({ homePageTrigger }),
  schemaDefinitions: () => ({}),
  publicSettings: (config) => ({
    contract: homePageManifest.contract,
    debounceSeconds: config.debounceSeconds,
    intervalHours: config.intervalHours,
    purge: config.purge,
  }),
  wire(backend, config, context: PluginWiringContext) {
    if (!context.projectionEnabled) {
      throw new Error("The home-page plugin writes pages through the S3 projection, so the site needs a publication (backend.publication) as well.");
    }
    const trigger = backend.homePageTrigger.resources.lambda as LambdaFunction;
    const contentActions = context.contentActionsLambda;
    const referenceTable = referenceCfnTable(backend);
    referenceTable.streamSpecification = { streamViewType: StreamViewType.NEW_AND_OLD_IMAGES };
    const streamArn = referenceTable.attrStreamArn;
    const stack = Stack.of(trigger);

    trigger.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"],
        resources: [streamArn],
      }),
    );
    new CfnEventSourceMapping(context.createStack("home-page-trigger") as Stack, "HomePageReferenceStreamMapping", {
      eventSourceArn: streamArn,
      functionName: trigger.functionArn,
      startingPosition: "TRIM_HORIZON",
      batchSize: HOME_PAGE_STREAM_BATCH_SIZE,
      maximumBatchingWindowInSeconds: HOME_PAGE_STREAM_BATCH_WINDOW_SECONDS,
      bisectBatchOnFunctionError: true,
      maximumRetryAttempts: HOME_PAGE_STREAM_RETRY_ATTEMPTS,
      filterCriteria: { filters: [{ pattern: homePageStreamFilterPattern() }] },
    });

    // The debounce item lives in the shared projection lock table (partition key `publication`), under a key of its own.
    trigger.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["dynamodb:PutItem", "dynamodb:DeleteItem"],
        resources: [projectionLeaseTableArn(stack.region, stack.account)],
      }),
    );

    // Trailing-edge debounce, as reader-steering does it: the trigger creates one-off schedules that invoke content-actions as this role.
    const schedulerRole = new Role(stack, "HomePageSnapshotSchedulerRole", {
      assumedBy: new ServicePrincipal("scheduler.amazonaws.com"),
      description: "Lets one-off schedules created by the home-page trigger invoke the home-page snapshot run.",
    });
    contentActions.grantInvoke(schedulerRole);
    trigger.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["scheduler:CreateSchedule"],
        resources: [`arn:${stack.partition}:scheduler:${stack.region}:${stack.account}:schedule/default/${HOME_PAGE_SNAPSHOT_SCHEDULE_PREFIX}*`],
      }),
    );
    trigger.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["iam:PassRole"], resources: [schedulerRole.roleArn] }));
    trigger.addEnvironment("PAPYRUS_HOME_PAGE_SNAPSHOT_FUNCTION_ARN", contentActions.functionArn);
    trigger.addEnvironment("PAPYRUS_HOME_PAGE_SCHEDULER_ROLE_ARN", schedulerRole.roleArn);
    trigger.addEnvironment("PAPYRUS_HOME_PAGE_DEBOUNCE_SECONDS", String(config.debounceSeconds));
    trigger.addEnvironment("PAPYRUS_PROJECTION_LOCK_TABLE", PROJECTION_LOCK_TABLE_NAME);

    if (config.intervalHours !== null) {
      new Rule(context.createStack("home-page-schedule"), "HomePageSnapshotSchedule", {
        description: "Runs the home-page snapshot on an interval, as a safety net for changes the stream missed.",
        schedule: Schedule.rate(intervalRate(config.intervalHours)),
        targets: [
          new LambdaFunctionTarget(contentActions, { event: RuleTargetInput.fromObject(HOME_PAGE_SNAPSHOT_TASK), retryAttempts: 0 }),
        ],
      });
    }
  },
};

