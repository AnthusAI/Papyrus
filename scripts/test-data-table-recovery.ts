import assert from "node:assert/strict";
import { AmplifyDynamoDbTableWrapper } from "@aws-amplify/graphql-api-construct";
import { App, CfnResource, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { enablePointInTimeRecoveryOnDataTables } from "../amplify/data-table-recovery";

const MODEL_NAMES = ["Reference", "Message", "Vote", "CurationDecision"];

function synthesizeDataStack(enable: boolean) {
  const app = new App();
  const stack = new Stack(app, "Data", { env: { account: "123456789012", region: "us-east-1" } });
  const tables: Record<string, AmplifyDynamoDbTableWrapper> = {};
  for (const name of MODEL_NAMES) {
    const resource = new CfnResource(stack, `${name}Managed`, {
      type: "Custom::AmplifyDynamoDBTable",
      properties: { tableName: `${name}-test`, billingMode: "PAY_PER_REQUEST" },
    });
    tables[name] = new AmplifyDynamoDbTableWrapper(resource);
  }
  const enabled = enable ? enablePointInTimeRecoveryOnDataTables(tables) : [];
  return { template: Template.fromStack(stack).toJSON() as { Resources: Record<string, { Type: string; Properties: Record<string, unknown> }> }, enabled };
}

const withRecovery = synthesizeDataStack(true);
const withoutRecovery = synthesizeDataStack(false);

assert.deepEqual(withRecovery.enabled, MODEL_NAMES);

const managedIds = (resources: Record<string, { Type: string }>) =>
  Object.keys(resources).filter((id) => resources[id].Type === "Custom::AmplifyDynamoDBTable");

assert.equal(managedIds(withRecovery.template.Resources).length, MODEL_NAMES.length);
for (const id of managedIds(withRecovery.template.Resources)) {
  assert.deepEqual(withRecovery.template.Resources[id].Properties.pointInTimeRecoverySpecification, { pointInTimeRecoveryEnabled: true }, `${id} has recovery on`);
}

assert.deepEqual(Object.keys(withRecovery.template.Resources).sort(), Object.keys(withoutRecovery.template.Resources).sort(), "no resource is added, removed or renamed");
for (const id of managedIds(withRecovery.template.Resources)) {
  const { pointInTimeRecoverySpecification, ...restWith } = withRecovery.template.Resources[id].Properties;
  assert.deepEqual(restWith, withoutRecovery.template.Resources[id].Properties, `${id} differs only in the recovery setting, which is not a replacement property`);
  assert.ok(pointInTimeRecoverySpecification);
}

console.log("data table recovery: ok");
