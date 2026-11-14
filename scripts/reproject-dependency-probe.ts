// Builds the post-deploy render next to a content-actions function in another stack, as the site backend does,
// and prints which stacks the render's stack waits for: {dependsOnFunctionStack, renderResourceInOwnStack}.
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { addReprojectOnDeploy } from "../amplify/publication/reproject-on-deploy";

const app = new App();
const env = { account: "123456789012", region: "us-east-1" };
const dataStack = new Stack(app, "Data", { env });
const renderStack = new Stack(app, "ReprojectOnDeploy", { env });
const contentActions = new lambda.Function(dataStack, "ContentActions", {
  runtime: lambda.Runtime.PYTHON_3_12,
  handler: "handler.handler",
  code: lambda.Code.fromInline("def handler(event, context):\n    return {}\n"),
});
addReprojectOnDeploy(renderStack, contentActions, "job-17");
const template = Template.fromStack(renderStack); // synthesizing adds the dependency that the function name reference creates
console.log(
  JSON.stringify({
    dependsOnFunctionStack: renderStack.dependencies.includes(dataStack),
    renderResourceInOwnStack: Object.keys(template.findResources("AWS::CloudFormation::CustomResource")).length === 1,
  }),
);
