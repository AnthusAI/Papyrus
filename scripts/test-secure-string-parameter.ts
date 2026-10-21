/**
 * SecureStringParameter: the value is generated at runtime inside a Lambda, so it
 * must be in no template, output or log, and the Lambda must create only.
 */
import assert from "node:assert/strict";
import vm from "node:vm";
import { createRequire } from "node:module";
import path from "node:path";
import { SecureStringParameter } from "../infra/amplify-app-shell/lib/secure-string-parameter";
// Load aws-cdk-lib the way the construct does (infra/amplify-app-shell/node_modules when installed, else the root),
// so the test and the construct never see two copies of constructs.
const libDirectory = path.resolve(__dirname, "../infra/amplify-app-shell/lib");
const requireFromLib = createRequire(path.join(libDirectory, "x.js"));
const { App, Stack } = requireFromLib("aws-cdk-lib");
const { Template } = requireFromLib("aws-cdk-lib/assertions");
import { SECURE_STRING_PARAMETER_HANDLER_SOURCE } from "../infra/amplify-app-shell/lib/secure-string-parameter-handler";

type PutInput = { Name: string; Description: string; Type: string; Tier: string; Overwrite: boolean; Value: string };

function loadHandler() {
  const exported: Record<string, any> = {};
  const logs: string[] = [];
  const capture = (...parts: unknown[]) => logs.push(parts.map(String).join(" "));
  vm.runInNewContext(SECURE_STRING_PARAMETER_HANDLER_SOURCE, {
    exports: exported,
    require: (name: string) => {
      if (name === "node:crypto") return require("node:crypto");
      throw new Error(`unexpected require ${name}`);
    },
    console: { log: capture, info: capture, warn: capture, error: capture, debug: capture },
  });
  return { createHandler: exported.createHandler as (ssm: unknown, command: unknown) => (event: unknown) => Promise<any>, logs };
}

class FakePutParameterCommand {
  constructor(public input: PutInput) {}
}

function fakeSsm(outcome: "created" | "exists" | "denied") {
  const puts: PutInput[] = [];
  return {
    puts,
    send: async (command: FakePutParameterCommand) => {
      puts.push(command.input);
      if (outcome === "exists") throw Object.assign(new Error("exists"), { name: "ParameterAlreadyExists" });
      if (outcome === "denied") throw Object.assign(new Error(`AccessDenied for ${command.input.Value}`), { name: "AccessDeniedException" });
      return {};
    },
  };
}

const name = "/papyrus/p-apyr-us/prospectus-session-sealing";
const properties = { ParameterName: name, Description: "Seals the cookies", Length: "64" };

async function handlerTests() {
  const { createHandler, logs } = loadHandler();

  const created = fakeSsm("created");
  const result = JSON.parse(JSON.stringify(await createHandler(created, FakePutParameterCommand)({ RequestType: "Create", ResourceProperties: properties })));
  assert.deepEqual(result, { PhysicalResourceId: name }, "the response carries only the parameter name");
  assert.equal(created.puts.length, 1);
  const put = created.puts[0];
  assert.equal(put.Name, name);
  assert.equal(put.Type, "SecureString");
  assert.equal(put.Tier, "Standard", "standard tier is free");
  assert.equal(put.Overwrite, false, "create never overwrites");
  assert.match(put.Value, /^[A-Za-z0-9]{64}$/, "a 64-character alphanumeric value");
  assert.equal(JSON.stringify(result).includes(put.Value), false, "the value is not returned");

  const second = fakeSsm("created");
  await createHandler(second, FakePutParameterCommand)({ RequestType: "Create", ResourceProperties: properties });
  assert.notEqual(second.puts[0].Value, put.Value, "each create generates a fresh value");

  const existing = fakeSsm("exists");
  const adopted = JSON.parse(JSON.stringify(await createHandler(existing, FakePutParameterCommand)({ RequestType: "Update", ResourceProperties: properties, PhysicalResourceId: name })));
  assert.deepEqual(adopted, { PhysicalResourceId: name }, "an existing parameter is adopted, not replaced");
  assert.equal(existing.puts[0].Overwrite, false, "update never overwrites");

  const deleted = fakeSsm("created");
  const deletion = JSON.parse(JSON.stringify(await createHandler(deleted, FakePutParameterCommand)({ RequestType: "Delete", ResourceProperties: properties, PhysicalResourceId: name })));
  assert.deepEqual(deletion, { PhysicalResourceId: name });
  assert.equal(deleted.puts.length, 0, "delete touches nothing");

  const denied = fakeSsm("denied");
  await assert.rejects(
    createHandler(denied, FakePutParameterCommand)({ RequestType: "Create", ResourceProperties: properties }),
    (error: Error) => {
      assert.equal(error.message.includes(denied.puts[0].Value), false, "an SDK error message cannot leak the value");
      assert.match(error.message, /AccessDeniedException/);
      return true;
    },
  );
  assert.deepEqual(logs, [], "the handler logs nothing, so no value reaches CloudWatch");
}

function templateTests() {
  const stack = new Stack(new App(), "TestStack", { env: { account: "712236451410", region: "us-east-1" } });
  const sealing = new SecureStringParameter(stack, "SealingParameter", { parameterName: name, description: "Seals the cookies" });
  const other = new SecureStringParameter(stack, "OtherParameter", { parameterName: "/papyrus/p-apyr-us/revalidate-secret", description: "Other" });
  assert.equal(sealing.parameterArn.includes("parameter/papyrus/p-apyr-us/prospectus-session-sealing"), true);
  assert.equal(other.parameterName, "/papyrus/p-apyr-us/revalidate-secret");
  const template = Template.fromStack(stack);
  const json = template.toJSON();
  const text = JSON.stringify(json);

  template.resourceCountIs("Custom::SecureStringParameter", 2);
  template.resourceCountIs("AWS::Lambda::Function", 2); // the handler and the provider framework: one pair per stack
  template.resourceCountIs("AWS::SecretsManager::Secret", 0);
  for (const resource of Object.values<any>(json.Resources).filter((entry) => entry.Type === "Custom::SecureStringParameter")) {
    assert.equal(resource.DeletionPolicy, "Retain", "delete retains the parameter");
    assert.equal(resource.UpdateReplacePolicy, "Retain", "replacement retains the parameter");
    assert.deepEqual(Object.keys(resource.Properties).sort(), ["Description", "Length", "ParameterName", "ServiceToken"], "the resource carries no value");
  }
  assert.equal(Object.keys(json.Outputs ?? {}).length, 0, "no outputs");
  template.resourceCountIs("AWS::SSM::Parameter", 0);
  assert.equal(text.includes("SecureString\""), false, "the template never spells out a SecureString put; only the Lambda source does, and it has no value");

  const policies = Object.values<any>(json.Resources).filter((entry) => entry.Type === "AWS::IAM::Policy");
  const putStatements = policies.flatMap((policy) => policy.Properties.PolicyDocument.Statement).filter((statement: any) => statement.Action === "ssm:PutParameter");
  assert.equal(putStatements.length, 2, "one PutParameter grant per parameter");
  assert.deepEqual(
    putStatements.map((statement: any) => `arn:aws:${statement.Resource["Fn::Join"][1][2].slice(1)}`).sort(),
    [
      "arn:aws:ssm:us-east-1:712236451410:parameter/papyrus/p-apyr-us/prospectus-session-sealing",
      "arn:aws:ssm:us-east-1:712236451410:parameter/papyrus/p-apyr-us/revalidate-secret",
    ].sort(),
    "each grant names exactly its parameter",
  );
  assert.equal(/ssm:(GetParameter|DeleteParameter|PutParameter\*)|"ssm:\*"|kms:/.test(text.replace(/ssm:PutParameter/g, "")), false, "the creator can only put");

  assert.throws(() => new SecureStringParameter(stack, "Relative", { parameterName: "papyrus/x", description: "x" }), /absolute/);
  assert.throws(() => new SecureStringParameter(stack, "Short", { parameterName: "/papyrus/x", description: "x", length: 8 }), /at least 32/);
}

templateTests();
handlerTests().then(() => console.log("secure string parameter: ok"), (error) => { console.error(error); process.exit(1); });
