import assert from "node:assert/strict";
import { App, NestedStack, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as sns from "aws-cdk-lib/aws-sns";
import { Construct } from "constructs";
import { DEFAULT_RESOLVER_WAVE_SIZE, orderModelStacksInWaves, planResolverWaves } from "../amplify/resolver-waves";

assert.equal(DEFAULT_RESOLVER_WAVE_SIZE, 12);
assert.deepEqual(planResolverWaves([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
assert.deepEqual(planResolverWaves([1, 2, 3], 0), []);
assert.deepEqual(planResolverWaves([1, 2, 3], -1), []);
assert.deepEqual(planResolverWaves([], 5), []);

function buildDataStack() {
  const app = new App();
  const dataStack = new Stack(app, "Data");
  const api = new Construct(dataStack, "Api");
  const names = ["A", "B", "C", "D", "E"];
  for (const name of names) {
    const nested = new NestedStack(api, name);
    new sns.Topic(nested, `${name}Topic`);
  }
  new NestedStack(api, "ConnectionStack");
  return { dataStack, api, names };
}

function dependsOnOf(template: Template, nestedLogicalPrefix: string): string[] {
  const resources = template.findResources("AWS::CloudFormation::Stack");
  const key = Object.keys(resources).find((logicalId) => logicalId.startsWith(`Api${nestedLogicalPrefix}`));
  assert.ok(key, `nested stack ${nestedLogicalPrefix} not found`);
  return (resources[key].DependsOn ?? []) as string[];
}

const withoutWaves = buildDataStack();
const baseline = Template.fromStack(withoutWaves.dataStack);
assert.equal(dependsOnOf(baseline, "A").length, 0);
assert.equal(dependsOnOf(baseline, "E").length, 0);

const withWaves = buildDataStack();
const waveCount = orderModelStacksInWaves(withWaves.api, withWaves.names, 2);
assert.equal(waveCount, 3);
const ordered = Template.fromStack(withWaves.dataStack);
assert.equal(dependsOnOf(ordered, "A").length, 0);
assert.equal(dependsOnOf(ordered, "B").length, 0);
assert.equal(dependsOnOf(ordered, "C").length, 2);
assert.equal(dependsOnOf(ordered, "D").length, 2);
assert.equal(dependsOnOf(ordered, "E").length, 2);
assert.equal(dependsOnOf(ordered, "ConnectionStack").length, 0);

const disabled = buildDataStack();
assert.equal(orderModelStacksInWaves(disabled.api, disabled.names, 0), 0);
assert.equal(dependsOnOf(Template.fromStack(disabled.dataStack), "E").length, 0);

console.log("resolver wave tests passed");
