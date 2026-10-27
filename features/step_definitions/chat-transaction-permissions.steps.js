const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { Given, Then } = require("@cucumber/cucumber");

Given("the private chat candidate infrastructure is synthesized", function () {
  this.chatTemplate = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../infra/shared-chat-runtime/cdk/PapyrusChatDataCandidate.template.json"), "utf8"));
});

Then("only the gateway messaging table and run worker conversation table allow ownership checks", function () {
  const checks = Object.entries(this.chatTemplate.Resources).flatMap(([policy, resource]) =>
    resource.Type !== "AWS::IAM::Policy" ? [] : resource.Properties.PolicyDocument.Statement
      .filter((statement) => [].concat(statement.Action).includes("dynamodb:ConditionCheckItem"))
      .map((statement) => ({ policy, statement })));
  assert.deepEqual(checks, [
    { policy: "PapyrusChatGatewayRolePolicyD9310960", statement: { Action: "dynamodb:ConditionCheckItem", Effect: "Allow", Resource: { "Fn::GetAtt": ["PrivateMessagingAEAE53CD", "Arn"] } } },
    { policy: "RunWorkerRoleDefaultPolicy8EE24203", statement: { Action: "dynamodb:ConditionCheckItem", Effect: "Allow", Resource: { "Fn::GetAtt": ["PrivateConversationIndex81B3261A", "Arn"] } } },
  ]);
});
