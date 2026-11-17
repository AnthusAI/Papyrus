/**
 * Checks GraphQL operations a client builds against the site API's real schema, so a request that AppSync would refuse is a failing test here.
 *
 *   tsx scripts/graphql-operations-contract.mts <operations.json>
 *
 * `operations.json` is a list of `{ "query": "...", "variables": {...} }`. The schema is the one Amplify generates for the base data
 * schema (`amplify/data/schema.ts`), expanded by the same transformers a deployment uses, so it holds the generated input types
 * (`ModelXConditionInput` carries no key field, `CreateXInput`, and so on). Each operation must validate against it, and its variables must
 * coerce to the types it declares: an unknown input field is the error AppSync gives, named the same way. Exits 1 and prints every problem.
 */
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { App, Duration, Stack } from "aws-cdk-lib";
import { UserPool } from "aws-cdk-lib/aws-cognito";
import { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { AmplifyGraphqlApi, AmplifyGraphqlDefinition } from "@aws-amplify/graphql-api-construct";
import { buildASTSchema, parse, validate, type GraphQLSchema } from "graphql";
import { getVariableValues } from "graphql/execution/values";

type Operation = { query: string; variables?: Record<string, unknown> | null };

/** The expanded GraphQL schema of the base data schema, as the generated SDL AppSync receives. */
async function generatedSchema(): Promise<GraphQLSchema> {
  const warn = console.warn;
  const log = console.log;
  console.warn = () => undefined; // the transformers warn about every field-level auth rule; none of it is about the operations
  console.log = () => undefined;
  const outdir = mkdtempSync(path.join(os.tmpdir(), "graphql-contract-"));
  try {
    const { schema } = await import("../amplify/data/schema");
    const transformed = (schema as unknown as { transform(): { schema: string } }).transform();
    const app = new App({ outdir });
    const stack = new Stack(app, "Contract", { env: { account: "123456789012", region: "us-east-1" } });
    const functionNames = new Set([...transformed.schema.matchAll(/@function\(name: "([^"]*)"/g)].map((match) => match[1]));
    const functionNameMap = Object.fromEntries([...functionNames].map((name) => [name, LambdaFunction.fromFunctionArn(stack, `Fn${name}`, `arn:aws:lambda:us-east-1:123456789012:function:${name}`)]));
    new AmplifyGraphqlApi(stack, "Api", {
      definition: AmplifyGraphqlDefinition.fromString(transformed.schema, { dbType: "DYNAMODB", provisionStrategy: "AMPLIFY_TABLE" }),
      authorizationModes: {
        defaultAuthorizationMode: "AMAZON_COGNITO_USER_POOLS",
        userPoolConfig: { userPool: new UserPool(stack, "Pool") },
        iamConfig: { enableIamAuthorizationMode: true },
        apiKeyConfig: { expires: Duration.days(365) },
      },
      functionNameMap,
    });
    app.synth();
    const file = readdirSync(outdir).find((name) => name.endsWith(".graphql"));
    if (!file) throw new Error("The generated API has no GraphQL schema file.");
    const sdl = readFileSync(path.join(outdir, file), "utf8");
    // AppSync's own scalars and auth directives are built in on its side, so the SDL does not declare them.
    const scalars = [...new Set(sdl.match(/\bAWS[A-Za-z]+\b/g) ?? [])].map((name) => `scalar ${name}`).join("\n");
    return buildASTSchema(parse(`${scalars}\n${sdl}`), { assumeValidSDL: true });
  } finally {
    console.warn = warn;
    console.log = log;
    rmSync(outdir, { recursive: true, force: true });
  }
}

function problems(schema: GraphQLSchema, operation: Operation): string[] {
  const document = parse(operation.query);
  const found = validate(schema, document).map((error) => error.message);
  for (const definition of document.definitions) {
    if (definition.kind !== "OperationDefinition") continue;
    const { errors } = getVariableValues(schema, [...(definition.variableDefinitions ?? [])], operation.variables ?? {});
    found.push(...(errors ?? []).map((error) => error.message));
  }
  return found;
}

const [, , operationsFile] = process.argv;
if (!operationsFile) throw new Error("usage: graphql-operations-contract.mts <operations.json>");
const operations: Operation[] = JSON.parse(readFileSync(operationsFile, "utf8"));
const schema = await generatedSchema();
let failed = 0;
for (const operation of operations) {
  const found = problems(schema, operation);
  const name = operation.query.match(/(?:query|mutation)\s+(\w+)/)?.[1] ?? operation.query.slice(0, 40);
  if (found.length) failed += 1;
  console.log(JSON.stringify({ operation: name, problems: found }));
}
process.exit(failed ? 1 : 0);
