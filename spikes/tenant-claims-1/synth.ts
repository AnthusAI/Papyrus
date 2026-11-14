// Offline synth: no AWS calls. Generates the AppSync resolvers and the Cognito trigger wiring Amplify would deploy.
// Usage: npx tsx spikes/tenant-claims-1/synth.ts <outdir>
import { App, Stack } from "aws-cdk-lib";
import { AmplifyGraphqlApi, AmplifyGraphqlDefinition } from "@aws-amplify/graphql-api-construct";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { schema } from "./schema";

const app = new App({ outdir: process.argv[2] });
const stack = new Stack(app, "Spike");
const pool = new cognito.UserPool(stack, "Pool");
const trigger = new lambda.Function(stack, "PreToken", {
  runtime: lambda.Runtime.NODEJS_20_X,
  handler: "index.handler",
  code: lambda.Code.fromAsset(new URL("./pre-token", import.meta.url).pathname),
});
// V2 event shape (claimsAndScopeOverrideDetails). Amplify's triggers.preTokenGeneration cannot select this version.
pool.addTrigger(cognito.UserPoolOperation.PRE_TOKEN_GENERATION_CONFIG, trigger, cognito.LambdaVersion.V2_0);
new AmplifyGraphqlApi(stack, "Api", {
  definition: AmplifyGraphqlDefinition.fromString((schema as any).transform().schema, {
    dbType: "DYNAMODB",
    provisionStrategy: "AMPLIFY_TABLE",
  }),
  authorizationModes: { defaultAuthorizationMode: "AMAZON_COGNITO_USER_POOLS", userPoolConfig: { userPool: pool } },
});
app.synth();
