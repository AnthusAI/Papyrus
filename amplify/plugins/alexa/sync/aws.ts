import { CognitoIdentityProviderClient, DescribeUserPoolClientCommand } from "@aws-sdk/client-cognito-identity-provider";
import { AddPermissionCommand, GetPolicyCommand, LambdaClient, RemovePermissionCommand } from "@aws-sdk/client-lambda";
import { GetParameterCommand, ParameterNotFound, PutParameterCommand, SSMClient } from "@aws-sdk/client-ssm";
import { ALEXA_APPKIT_PRINCIPAL_NAME } from "../principal";
import type { ClientSecretSource, FunctionPermissions, ParameterStore } from "./ports";

function isNotFound(error: unknown, name: string): boolean {
  return (error as { name?: string })?.name === name;
}

export function ssmParameterStore(client: SSMClient = new SSMClient({})): ParameterStore {
  return {
    async get(name) {
      try {
        return (await client.send(new GetParameterCommand({ Name: name, WithDecryption: true }))).Parameter?.Value;
      } catch (error) {
        if (error instanceof ParameterNotFound || isNotFound(error, "ParameterNotFound")) return undefined;
        throw error;
      }
    },
    async putString(name, value) {
      await client.send(new PutParameterCommand({ Name: name, Value: value, Type: "String", Overwrite: true }));
    },
  };
}

type PolicyStatement = { Sid?: string; Principal?: { Service?: string | string[] }; Condition?: { StringEquals?: Record<string, string> } };

export function lambdaFunctionPermissions(client: LambdaClient = new LambdaClient({})): FunctionPermissions {
  return {
    async alexaStatements(functionArn) {
      let policy: string | undefined;
      try {
        policy = (await client.send(new GetPolicyCommand({ FunctionName: functionArn }))).Policy;
      } catch (error) {
        if (!isNotFound(error, "ResourceNotFoundException")) throw error;
      }
      const statements = (policy === undefined ? [] : (JSON.parse(policy).Statement ?? [])) as PolicyStatement[];
      return statements
        .filter((statement) => [statement.Principal?.Service].flat().includes(ALEXA_APPKIT_PRINCIPAL_NAME) && statement.Sid !== undefined)
        .map((statement) => ({ statementId: statement.Sid as string, skillId: statement.Condition?.StringEquals?.["lambda:EventSourceToken"] }));
    },
    async addSkillPermission(functionArn, statementId, skillId) {
      await client.send(
        new AddPermissionCommand({
          FunctionName: functionArn,
          StatementId: statementId,
          Action: "lambda:InvokeFunction",
          Principal: ALEXA_APPKIT_PRINCIPAL_NAME,
          EventSourceToken: skillId,
        }),
      );
    },
    async removePermission(functionArn, statementId) {
      await client.send(new RemovePermissionCommand({ FunctionName: functionArn, StatementId: statementId }));
    },
  };
}

/** The pool's region is the part of its id before the underscore. */
export function cognitoClientSecrets(clientFor: (region: string) => CognitoIdentityProviderClient = (region) => new CognitoIdentityProviderClient({ region })): ClientSecretSource {
  return {
    async clientSecret({ userPoolId, clientId }) {
      const response = await clientFor(userPoolId.split("_")[0]).send(new DescribeUserPoolClientCommand({ UserPoolId: userPoolId, ClientId: clientId }));
      return response.UserPoolClient?.ClientSecret;
    },
  };
}
