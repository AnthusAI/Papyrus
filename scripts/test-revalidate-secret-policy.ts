import assert from "node:assert/strict";
import { REVALIDATE_SECRET_READ_ACTIONS, revalidateSecretReadStatement } from "../amplify/revalidate-secret-policy";

const statement = revalidateSecretReadStatement({
  partition: "aws",
  region: "us-east-1",
  account: "111122223333",
  parameterName: "/papyrus/site-a/revalidate-secret",
});
assert.deepEqual(statement.actions, REVALIDATE_SECRET_READ_ACTIONS);
assert.ok(statement.actions.includes("ssm:GetParameters"), "boto3 get_parameters needs ssm:GetParameters");
assert.ok(statement.actions.includes("ssm:GetParameter"), "the CLI fallback needs ssm:GetParameter");
assert.deepEqual(statement.resources, ["arn:aws:ssm:us-east-1:111122223333:parameter/papyrus/site-a/revalidate-secret"]);
