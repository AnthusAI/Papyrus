import { CustomResource, Duration, Stack } from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import { PolicyStatement } from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Provider } from "aws-cdk-lib/custom-resources";

export const REPROJECT_ON_DEPLOY_TIMEOUT_SECONDS = 900;
export const DEPLOY_RENDER_METRIC_NAMESPACE = "Papyrus/Projection";
export const DEPLOY_RENDER_DRIFT_METRIC_NAME = "DeployRenderDrift";
export const DEPLOY_RENDER_TASK = "deploy-render";
const FAILURE_MESSAGE_LIMIT = 600;
const RESULT_SUMMARY_LIMIT = 900;

export function reprojectDeployToken(environment: Record<string, string | undefined>, now: () => number = Date.now): string {
  const buildJobId = (environment.AWS_JOB_ID ?? "").trim();
  return buildJobId !== "" ? `job-${buildJobId}` : `time-${now()}`;
}

/**
 * Runs inside the deploy: invokes the content-actions Lambda synchronously, so a render that fails fails the
 * stack update (and with it the Amplify build) with the failure in the build log. The Lambda's result, which
 * includes the drift check, is written to its log and returned as the resource's data.
 */
export const DEPLOY_RENDER_HANDLER_SOURCE = `
const { LambdaClient, InvokeCommand } = require("@aws-sdk/client-lambda");

exports.handler = async (event) => {
  if (event.RequestType === "Delete") return { PhysicalResourceId: event.PhysicalResourceId };
  const properties = event.ResourceProperties;
  const client = new LambdaClient({ maxAttempts: 1 });
  const response = await client.send(new InvokeCommand({
    FunctionName: properties.FunctionName,
    InvocationType: "RequestResponse",
    Payload: JSON.stringify({ projectionTask: { task: properties.Task, deployToken: properties.DeployToken } }),
  }));
  const text = Buffer.from(response.Payload || []).toString("utf8");
  console.log("deploy render result: " + text);
  if (response.FunctionError) {
    throw new Error("The post-deploy render failed (" + response.FunctionError + "): " + text.slice(0, ${FAILURE_MESSAGE_LIMIT}));
  }
  return { PhysicalResourceId: "reproject-" + properties.DeployToken, Data: { Result: text.slice(0, ${RESULT_SUMMARY_LIMIT}) } };
};
`;

/**
 * Renders every published page after each backend deploy and checks the site store for drift (a dry run:
 * nothing is deleted). The token is a property, so CloudFormation runs the resource again on every deploy.
 */
export function addReprojectOnDeploy(stack: Stack, contentActions: lambda.IFunction, deployToken: string): CustomResource {
  const handler = new lambda.Function(stack, "DeployRenderHandler", {
    runtime: lambda.Runtime.NODEJS_20_X,
    handler: "index.handler",
    code: lambda.Code.fromInline(DEPLOY_RENDER_HANDLER_SOURCE),
    timeout: Duration.seconds(REPROJECT_ON_DEPLOY_TIMEOUT_SECONDS),
    description: "Starts the post-deploy render of the site and fails the deploy if it cannot finish.",
  });
  handler.addToRolePolicy(new PolicyStatement({ actions: ["lambda:InvokeFunction"], resources: [contentActions.functionArn] }));
  const provider = new Provider(stack, "DeployRenderProvider", { onEventHandler: handler });
  new cloudwatch.Alarm(stack, "DeployRenderDriftAlarm", {
    metric: new cloudwatch.Metric({
      namespace: DEPLOY_RENDER_METRIC_NAMESPACE,
      metricName: DEPLOY_RENDER_DRIFT_METRIC_NAME,
      dimensionsMap: { FunctionName: contentActions.functionName },
      statistic: "Maximum",
      period: Duration.days(1),
    }),
    evaluationPeriods: 1,
    threshold: 1,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    alarmDescription:
      "The last post-deploy render found drift between the published content and the site store (stale pages, orphan pages or redirects). Nothing was deleted; run papyrus ops content project --reconcile to repair.",
  });
  return new CustomResource(stack, "ReprojectOnDeploy", {
    serviceToken: provider.serviceToken,
    properties: { FunctionName: contentActions.functionName, Task: DEPLOY_RENDER_TASK, DeployToken: deployToken },
  });
}
