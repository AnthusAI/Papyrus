import { ArnPrincipal, Effect, PolicyStatement, Role, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { Duration, Stack } from "aws-cdk-lib";
import type { ITable } from "aws-cdk-lib/aws-dynamodb";
import { Rule, RuleTargetInput, Schedule } from "aws-cdk-lib/aws-events";
import { LambdaFunction as LambdaFunctionTarget } from "aws-cdk-lib/aws-events-targets";
import { CfnFunction, type Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import type { PapyrusPlugin, PluginManifest, PluginWiringContext } from "../types";
import { resolveReaderSteeringConfig, type ReaderSteeringConfig } from "./config";
import { readerActions } from "./function/resource";
import { readerSteeringSchemaDefinitions } from "./schema";

export { resolveReaderSteeringConfig };
export type { ReaderSteeringConfig };

export const READER_STEERING_OUTPUT_KEY = "readerSteering";
export const SNAPSHOT_SCHEDULE_PREFIX = "papyrus-reader-snapshot-";
export const READER_SNAPSHOT_TASK = { projectionTask: { task: "reader-snapshot" } };

export const readerSteeringManifest: PluginManifest = {
  name: "reader-steering",
  contract: 1,
  models: ["ReaderProfile", "ReaderHandle", "ReaderVote"],
  mutations: [],
  guest: { mutations: [] },
  newsroomPanels: [],
  staticAssets: ["_plugins/papyrus-reader@1.js", "_plugins/papyrus-reader@1.css"],
};

/** What the reader-actions function reads from `PAPYRUS_READER_SETTINGS`. */
export function readerActionsSettings(config: ReaderSteeringConfig, allowInterimSubjects: boolean) {
  return {
    dimensions: config.dimensions,
    limits: config.limits,
    reservedHandles: config.reservedHandles,
    allowInterimSubjects,
    snapshotDebounceSeconds: 60,
  };
}

/** What the `reader-snapshot` projection task reads from `PAPYRUS_READER_SNAPSHOT_SETTINGS`. */
export function readerSnapshotSettings(config: ReaderSteeringConfig) {
  return {
    dimensions: config.dimensions,
    karma: config.karma,
    ranking: config.ranking,
    hypeMinimum: config.snapshot.hypeMinimum,
    ...(config.hypeGap ? { hypeGap: config.hypeGap } : {}),
    retirementPoll: config.retirementPoll,
  };
}

export function interimSubjectsAllowedAtSynth(environment: Record<string, string | undefined> = process.env): boolean {
  return ["development", "test"].includes((environment.SITE_ENV ?? "").trim()) && environment.NODE_ENV !== "production";
}

export const readerSteeringPlugin: PapyrusPlugin<ReaderSteeringConfig, { readerActions: typeof readerActions }> = {
  manifest: readerSteeringManifest,
  resolveConfig: resolveReaderSteeringConfig,
  functions: () => ({ readerActions }),
  schemaDefinitions: readerSteeringSchemaDefinitions,
  publicSettings: (config) => ({ contract: readerSteeringManifest.contract, dimensions: config.dimensions }),
  wire(backend, config, context: PluginWiringContext) {
    const lambda = backend.readerActions.resources.lambda as LambdaFunction;
    const tables = backend.data.resources.tables as Record<string, ITable>;
    const contentActions = context.contentActionsLambda;

    for (const [variable, model] of [
      ["PAPYRUS_READER_PROFILE_TABLE", "ReaderProfile"],
      ["PAPYRUS_READER_HANDLE_TABLE", "ReaderHandle"],
      ["PAPYRUS_READER_VOTE_TABLE", "ReaderVote"],
    ] as const) {
      tables[model].grantReadWriteData(lambda);
      lambda.addEnvironment(variable, tables[model].tableName);
      contentActions.addEnvironment(variable, tables[model].tableName);
    }
    tables.PublishedItem.grantReadData(lambda);
    lambda.addEnvironment("PAPYRUS_READER_PUBLISHED_ITEM_TABLE", tables.PublishedItem.tableName);
    tables.ReaderVote.grantReadData(contentActions);
    tables.ReaderProfile.grantReadWriteData(contentActions);

    lambda.addEnvironment("PAPYRUS_READER_SETTINGS", JSON.stringify(readerActionsSettings(config, interimSubjectsAllowedAtSynth())));
    if (config.reservedConcurrency !== undefined) {
      (lambda.node.defaultChild as CfnFunction).addPropertyOverride("ReservedConcurrentExecutions", config.reservedConcurrency);
    }

    // Trailing-edge debounce: the first write in a window creates a one-off EventBridge Scheduler schedule at the end of
    // the window (docs/reader-steering.md). The schedule invokes content-actions as this role; reader-actions may create
    // schedules named for this feature, and pass exactly this role.
    const schedulerRole = new Role(Stack.of(lambda), "ReaderSnapshotSchedulerRole", {
      assumedBy: new ServicePrincipal("scheduler.amazonaws.com"),
      description: "Lets one-off schedules created by reader-actions invoke the reader-snapshot run.",
    });
    contentActions.grantInvoke(schedulerRole);
    const stack = Stack.of(lambda); // the role lives with the function, so the stacks keep their existing one-way dependency
    lambda.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["scheduler:CreateSchedule"],
        resources: [`arn:${stack.partition}:scheduler:${stack.region}:${stack.account}:schedule/default/${SNAPSHOT_SCHEDULE_PREFIX}*`],
      }),
    );
    lambda.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["iam:PassRole"], resources: [schedulerRole.roleArn] }));
    lambda.addEnvironment("PAPYRUS_READER_SNAPSHOT_FUNCTION_ARN", contentActions.functionArn);
    lambda.addEnvironment("PAPYRUS_READER_SCHEDULER_ROLE_ARN", schedulerRole.roleArn);
    contentActions.addEnvironment("PAPYRUS_READER_SNAPSHOT_SETTINGS", JSON.stringify(readerSnapshotSettings(config)));

    lambda.addPermission("InvokeFromCmsCompute", {
      principal: new ArnPrincipal(config.computeRoleArn),
      action: "lambda:InvokeFunction",
    });

    if (config.snapshot.schedule) {
      new Rule(context.createStack("reader-steering-schedule"), "ReaderSnapshotSchedule", {
        description: "Rebuilds the reader snapshot (time decay, Rising) and polls nothing else.",
        schedule: Schedule.rate(Duration.hours(config.snapshot.intervalHours)),
        targets: [new LambdaFunctionTarget(contentActions, { event: RuleTargetInput.fromObject(READER_SNAPSHOT_TASK), retryAttempts: 0 })],
      });
    }

    backend.addOutput({ custom: { [READER_STEERING_OUTPUT_KEY]: { actionsFunction: lambda.functionName } } });
  },
};
