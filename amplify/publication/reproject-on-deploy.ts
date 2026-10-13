import { Stack } from "aws-cdk-lib";
import { PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { IFunction } from "aws-cdk-lib/aws-lambda";
import { AwsCustomResource, AwsCustomResourcePolicy, PhysicalResourceId } from "aws-cdk-lib/custom-resources";

export const REPROJECT_ON_DEPLOY_TIMEOUT_SECONDS = 300;

export function reprojectDeployToken(environment: Record<string, string | undefined>, now: () => number = Date.now): string {
  const buildJobId = (environment.AWS_JOB_ID ?? "").trim();
  return buildJobId !== "" ? `job-${buildJobId}` : `time-${now()}`;
}

/**
 * Starts the content-actions `all` projection task (asynchronously) every time the stack deploys.
 * The token is in the request, so CloudFormation sees a changed property on each deploy.
 */
export function addReprojectOnDeploy(stack: Stack, contentActions: IFunction, deployToken: string): AwsCustomResource {
  const invocation = {
    service: "Lambda",
    action: "invoke",
    parameters: {
      FunctionName: contentActions.functionName,
      InvocationType: "Event",
      Payload: JSON.stringify({ projectionTask: { task: "all", deployToken } }),
    },
    physicalResourceId: PhysicalResourceId.of(`reproject-${deployToken}`),
  };
  return new AwsCustomResource(stack, "ReprojectOnDeploy", {
    onCreate: invocation,
    onUpdate: invocation,
    installLatestAwsSdk: false,
    policy: AwsCustomResourcePolicy.fromStatements([
      new PolicyStatement({ actions: ["lambda:InvokeFunction"], resources: [contentActions.functionArn] }),
    ]),
  });
}
