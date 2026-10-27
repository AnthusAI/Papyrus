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
export const READER_SCHEDULED_SNAPSHOT_TASK = { projectionTask: { task: "reader-snapshot", retirementPoll: true } };
export const READER_POLL_SECRET_PARAMETER_ENV = "PAPYRUS_READER_POLL_SECRET_PARAMETER";

export const readerSteeringManifest: PluginManifest = {
  name: "reader-steering",
  contract: 1,
  models: ["ReaderProfile", "ReaderHandle", "ReaderVote", "ReaderFlag", "ReaderSubmission", "ReaderComment", "ReaderReport", "ModerationAction"],
  mutations: ["moderateReader"],
  guest: { mutations: [] },
  newsroomPanels: [{ id: "moderation", label: "Moderation" }],
  staticAssets: ["_plugins/papyrus-reader@1.js", "_plugins/papyrus-reader@1.css"],
};

/** What the reader-actions function reads from `PAPYRUS_READER_SETTINGS`. */
export function readerActionsSettings(config: ReaderSteeringConfig, allowInterimSubjects: boolean) {
  return {
    dimensions: config.dimensions,
    limits: config.limits,
    submissions: config.submissions,
    subjects: config.subjects,
    comments: config.comments,
    moderation: config.moderation,
    reservedHandles: config.reservedHandles,
    allowInterimSubjects,
    snapshotDebounceSeconds: 60,
  };
}

/** What the `reader-snapshot` projection task reads from `PAPYRUS_READER_SNAPSHOT_SETTINGS`. */
export function readerSnapshotSettings(config: ReaderSteeringConfig) {
  return {
    dimensions: config.dimensions,
    submissions: config.submissions,
    subjects: config.subjects,
    karma: config.karma,
    ranking: config.ranking,
    limits: { newAccountHours: config.limits.newAccountHours },
    hypeMinimum: config.snapshot.hypeMinimum,
    ...(config.hypeGap ? { hypeGap: config.hypeGap } : {}),
    retirementPoll: config.retirementPoll,
  };
}

export function interimSubjectsAllowedAtSynth(environment: Record<string, string | undefined> = process.env): boolean {
  return ["development", "test"].includes((environment.SITE_ENV ?? "").trim()) && environment.NODE_ENV !== "production";
}

/**
 * The scheduled run polls Prospectus through the CMS route /api/reader/retired (docs/reader-steering.md), so it needs the
 * site origin and the poll secret parameter that the app-shell stack generates (`cms.readerRetirementPoll`); both reach the
 * backend build as branch variables. It also deletes and re-keys rows, and keeps its cursor in the rate table.
 */
function wireRetirementPoll(readerLambda: LambdaFunction, contentActions: LambdaFunction, tables: Record<string, ITable>) {
  const origin = (process.env.PAPYRUS_SITE_ORIGIN ?? "").trim();
  const parameterName = (process.env[READER_POLL_SECRET_PARAMETER_ENV] ?? "").trim();
  if (!origin.startsWith("https://") || !parameterName.startsWith("/")) {
    throw new Error(
      "reader-steering retirementPoll needs PAPYRUS_SITE_ORIGIN (an https origin) and PAPYRUS_READER_POLL_SECRET_PARAMETER (an SSM parameter name). The app-shell template sets both on the production branch when site.json has cms.readerRetirementPoll: true; see docs/reader-steering.md.",
    );
  }
  const rateTable = readerLambda.node.scope?.node.tryFindChild("PapyrusReaderRateWindows") as ITable | undefined;
  if (!rateTable) throw new Error("reader-steering retirementPoll could not find the reader-actions rate table to keep its cursor in");
  tables.ReaderVote.grantReadWriteData(contentActions);
  tables.ReaderHandle.grantReadWriteData(contentActions);
  rateTable.grantReadWriteData(contentActions);
  contentActions.addEnvironment("PAPYRUS_READER_RATE_TABLE", rateTable.tableName);
  contentActions.addEnvironment("PAPYRUS_READER_POLL_URL", origin);
  contentActions.addEnvironment(READER_POLL_SECRET_PARAMETER_ENV, parameterName);
  const stack = Stack.of(contentActions);
  contentActions.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["ssm:GetParameter"],
      resources: [`arn:${stack.partition}:ssm:${stack.region}:${stack.account}:parameter${parameterName}`],
    }),
  );
}

/**
 * AI moderation (`moderation.mode: ai`). The debounced run becomes a run of reader-actions itself (a one-off schedule that
 * invokes this function), which judges the new items and then asks content-actions for the snapshot. So the scheduler role may
 * invoke reader-actions, reader-actions may invoke content-actions (its ARN is already in the environment) and may read exactly
 * one SSM SecureString: the API key, which the plugin never creates and never receives.
 */
function wireAiModeration(readerLambda: LambdaFunction, contentActions: LambdaFunction, schedulerRole: Role, apiKeyParameter: string) {
  const stack = Stack.of(readerLambda);
  readerLambda.grantInvoke(schedulerRole);
  contentActions.grantInvoke(readerLambda);
  readerLambda.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["ssm:GetParameter"],
      resources: [`arn:${stack.partition}:ssm:${stack.region}:${stack.account}:parameter${apiKeyParameter}`],
    }),
  );
}

export const readerSteeringPlugin: PapyrusPlugin<ReaderSteeringConfig, { readerActions: typeof readerActions }> = {
  manifest: readerSteeringManifest,
  resolveConfig: resolveReaderSteeringConfig,
  functions: () => ({ readerActions }),
  schemaDefinitions: readerSteeringSchemaDefinitions,
  publicSettings: (config) => ({
    contract: readerSteeringManifest.contract,
    dimensions: config.dimensions,
    subjects: { types: config.subjects.types },
    moderation: { mode: config.moderation.mode },
  }),
  wire(backend, config, context: PluginWiringContext) {
    const lambda = backend.readerActions.resources.lambda as LambdaFunction;
    const tables = backend.data.resources.tables as Record<string, ITable>;
    const contentActions = context.contentActionsLambda;

    for (const [variable, model] of [
      ["PAPYRUS_READER_PROFILE_TABLE", "ReaderProfile"],
      ["PAPYRUS_READER_HANDLE_TABLE", "ReaderHandle"],
      ["PAPYRUS_READER_VOTE_TABLE", "ReaderVote"],
      ["PAPYRUS_READER_FLAG_TABLE", "ReaderFlag"],
      ["PAPYRUS_READER_SUBMISSION_TABLE", "ReaderSubmission"],
      ["PAPYRUS_READER_COMMENT_TABLE", "ReaderComment"],
      ["PAPYRUS_READER_REPORT_TABLE", "ReaderReport"],
      ["PAPYRUS_READER_ACTION_TABLE", "ModerationAction"],
    ] as const) {
      tables[model].grantReadWriteData(lambda);
      lambda.addEnvironment(variable, tables[model].tableName);
      contentActions.addEnvironment(variable, tables[model].tableName);
    }
    // Promoting a submission writes one draft Item (a version 1 draft; nothing is published by this function).
    tables.Item.grantWriteData(lambda);
    lambda.addEnvironment("PAPYRUS_READER_ITEM_TABLE", tables.Item.tableName);
    tables.PublishedItem.grantReadData(lambda);
    lambda.addEnvironment("PAPYRUS_READER_PUBLISHED_ITEM_TABLE", tables.PublishedItem.tableName);
    tables.ReaderVote.grantReadData(contentActions);
    tables.ReaderFlag.grantReadData(contentActions);
    tables.ReaderProfile.grantReadWriteData(contentActions);
    // The snapshot reads submissions, and the review step writes their signals and moderation state.
    tables.ReaderSubmission.grantReadWriteData(contentActions);
    tables.ReaderComment.grantReadWriteData(contentActions);
    // The snapshot reads proposals and freezes the community result of one that reaches editor review. The Proposal model and the
    // functions that file and move proposals are core (amplify/functions/proposal-actions); this plugin only reads the same table.
    tables.Proposal.grantReadWriteData(contentActions);
    contentActions.addEnvironment("PAPYRUS_READER_PROPOSAL_TABLE", tables.Proposal.tableName);

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
    // Proposals are private unless the site opts in (docs/reader-steering.md, Proposals); the snapshot reads this flag.
    contentActions.addEnvironment("PAPYRUS_READER_PUBLISH_PROPOSALS", config.proposals.publish ? "true" : "false");

    if (config.moderation.ai) wireAiModeration(lambda, contentActions, schedulerRole, config.moderation.ai.apiKeyParameter);

    lambda.addPermission("InvokeFromCmsCompute", {
      principal: new ArnPrincipal(config.computeRoleArn),
      action: "lambda:InvokeFunction",
    });

    if (config.retirementPoll) wireRetirementPoll(lambda, contentActions, tables);

    if (config.snapshot.schedule) {
      new Rule(context.createStack("reader-steering-schedule"), "ReaderSnapshotSchedule", {
        description: "Rebuilds the reader snapshot (time decay, Rising) and, when enabled, applies Prospectus subject retirements.",
        schedule: Schedule.rate(Duration.hours(config.snapshot.intervalHours)),
        targets: [
          new LambdaFunctionTarget(contentActions, {
            event: RuleTargetInput.fromObject(config.retirementPoll ? READER_SCHEDULED_SNAPSHOT_TASK : READER_SNAPSHOT_TASK),
            retryAttempts: 0,
          }),
        ],
      });
    }

    backend.addOutput({ custom: { [READER_STEERING_OUTPUT_KEY]: { actionsFunction: lambda.functionName } } });
  },
};
