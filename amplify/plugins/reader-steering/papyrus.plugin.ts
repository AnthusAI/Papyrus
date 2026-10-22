import { ArnPrincipal } from "aws-cdk-lib/aws-iam";
import type { ITable } from "aws-cdk-lib/aws-dynamodb";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import type { PapyrusPlugin, PluginManifest, PluginWiringContext } from "../types";
import { resolveReaderSteeringConfig, type ReaderSteeringConfig } from "./config";
import { readerActions } from "./function/resource";
import { readerSteeringSchemaDefinitions } from "./schema";

export { resolveReaderSteeringConfig };
export type { ReaderSteeringConfig };

export const READER_STEERING_OUTPUT_KEY = "readerSteering";

export const readerSteeringManifest: PluginManifest = {
  name: "reader-steering",
  contract: 1,
  models: ["ReaderProfile", "ReaderHandle", "ReaderVote"],
  mutations: [],
  guest: { mutations: [] },
  newsroomPanels: [],
  staticAssets: [],
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
    lambda.addEnvironment("PAPYRUS_READER_SNAPSHOT_FUNCTION", contentActions.functionName);
    contentActions.grantInvoke(lambda);
    contentActions.addEnvironment("PAPYRUS_READER_SNAPSHOT_SETTINGS", JSON.stringify(readerSnapshotSettings(config)));

    lambda.addPermission("InvokeFromCmsCompute", {
      principal: new ArnPrincipal(config.computeRoleArn),
      action: "lambda:InvokeFunction",
    });

    backend.addOutput({ custom: { [READER_STEERING_OUTPUT_KEY]: { actionsFunction: lambda.functionName } } });
  },
};
