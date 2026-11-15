import { Duration } from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Architecture, CfnEventSourceMapping, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { pythonLambdaCode } from "../shared/python-bundle";
import { connectToSiteApi } from "../../site-api-access";
import { AUTOMATION_RUN_NOW_LEADING_KEYS, AUTOMATION_RUN_NOW_TABLE_ACTIONS, PROCEDURE_RUNNER_FUNCTION_NAME } from "../automation-view/wire";
import { MONITORING_TABLE_PARAMETER, MONITORING_VIEW_TABLE_ACTIONS, monitoringViewParameterArn, monitoringViewTableArns } from "../monitoring-view/wire";

/**
 * Translate on publish (docs/story-translation-procedure.md, "Translating on publish"): a DynamoDB Streams consumer on the LocalizationRequest table.
 * The publish path writes one desired-state record per enabled language (`languages.auto`); this function reacts to each change of those records: it
 * starts the waiting runs through the Automation they name (the same code as Run now) and asks the content-actions function to publish a translation a
 * run saved cleanly. It calls no model and publishes nothing itself.
 *
 * What it may do, and nothing else: read and update LocalizationRequest rows and read Automation records of its own site's API; read the monitoring
 * table and write one Run now row in a monitor's partition (the automation-view grant); start the procedure runner; invoke the content-actions function.
 * A shared stack (one backend for several tenants) is not wired: its rows carry a tenant the dispatcher does not act for (docs/multi-tenancy.md).
 */
export const DISPATCH_API_FIELDS = [
  "Query/fields/getAutomation",
  "Query/fields/getLocalizationRequest",
  "Query/fields/listLocalizationRequestsByStateAndRequestedAt",
  "Mutation/fields/updateLocalizationRequest",
];
const STREAM_READ_ACTIONS = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"];
export const CONTENT_ACTIONS_ENV = "PAPYRUS_CONTENT_ACTIONS_FUNCTION";

/** The LocalizationRequest table's stream, with both images (the dispatcher compares them to tell a fresh request from its own put-back). */
function localizationRequestStream(backend: any): string {
  const cfnResources = backend.data.resources.cfnResources;
  const wrapper = cfnResources.amplifyDynamoDbTables?.LocalizationRequest;
  if (wrapper !== undefined) {
    wrapper.streamSpecification = { streamViewType: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES };
    return wrapper.resource.getAtt("TableStreamArn").toString();
  }
  const cfnTables = cfnResources.cfnTables ?? {};
  const found =
    cfnTables.LocalizationRequest ??
    cfnTables.LocalizationRequestTable ??
    Object.entries(cfnTables).find(([key]) => key.toLowerCase().replace(/table$/, "") === "localizationrequest")?.[1];
  if (!found) throw new Error(`Translating on publish needs the LocalizationRequest table. cfnTables=${Object.keys(cfnTables).join(",")}`);
  found.streamSpecification = { streamViewType: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES };
  return found.attrStreamArn;
}

/** Wires the dispatcher, or nothing when the site's schema leaves out the localization models (`excludeModelGroups`: no table, nothing to dispatch). */
export function wireLocalizationDispatch(backend: any, contentActionsLambda: LambdaFunction): LambdaFunction | undefined {
  if (!backend.data.resources.tables.LocalizationRequest) return undefined;
  const streamArn = localizationRequestStream(backend);
  const stack = backend.createStack("localization-dispatch");
  const dispatcher = new LambdaFunction(stack, "LocalizationDispatcher", {
    runtime: Runtime.PYTHON_3_12,
    architecture: Architecture.ARM_64,
    handler: "handler.handler",
    timeout: Duration.seconds(60),
    memorySize: 256,
    code: pythonLambdaCode(
      { functionDir: "localization-dispatch", modules: ["papyrus_content"], noDeps: true },
      [
        "bash",
        "-c",
        [
          "set -euo pipefail",
          "mkdir -p /asset-output/papyrus_content",
          "cp amplify/functions/localization-dispatch/handler.py /asset-output/handler.py",
          "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
        ].join(" && "),
      ],
    ),
  });
  connectToSiteApi(dispatcher, backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl as string);
  dispatcher.addEnvironment("PAPYRUS_MONITORING_TABLE_PARAMETER", MONITORING_TABLE_PARAMETER);
  dispatcher.addEnvironment("PROCEDURE_RUNNER_FUNCTION", PROCEDURE_RUNNER_FUNCTION_NAME);
  dispatcher.addEnvironment(CONTENT_ACTIONS_ENV, contentActionsLambda.functionName);
  const apiId = backend.data.resources.graphqlApi.apiId as string;
  const region = stack.region;
  const account = stack.account;
  dispatcher.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["appsync:GraphQL"],
      resources: DISPATCH_API_FIELDS.map((field) => `arn:aws:appsync:${region}:${account}:apis/${apiId}/types/${field}`),
    }),
  );
  dispatcher.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["ssm:GetParameter"], resources: [monitoringViewParameterArn(region, account)] }));
  dispatcher.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: MONITORING_VIEW_TABLE_ACTIONS, resources: monitoringViewTableArns(region, account) }));
  dispatcher.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: AUTOMATION_RUN_NOW_TABLE_ACTIONS,
      resources: monitoringViewTableArns(region, account).slice(0, 1),
      conditions: { "ForAllValues:StringLike": { "dynamodb:LeadingKeys": AUTOMATION_RUN_NOW_LEADING_KEYS } },
    }),
  );
  dispatcher.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["lambda:InvokeFunction"],
      resources: [`arn:aws:lambda:${region}:${account}:function:${PROCEDURE_RUNNER_FUNCTION_NAME}`, contentActionsLambda.functionArn],
    }),
  );
  dispatcher.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: STREAM_READ_ACTIONS, resources: [streamArn] }));
  new CfnEventSourceMapping(stack, "LocalizationDispatcherStreamMapping", {
    eventSourceArn: streamArn,
    functionName: dispatcher.functionArn,
    startingPosition: "LATEST",
    batchSize: 10,
    maximumBatchingWindowInSeconds: 2,
    maximumRetryAttempts: 5,
    functionResponseTypes: ["ReportBatchItemFailures"],
  });
  return dispatcher;
}
