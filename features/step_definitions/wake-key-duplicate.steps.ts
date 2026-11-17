import assert from "node:assert/strict";
import { Given, Then, When } from "@cucumber/cucumber";
import { createHandler } from "../../amplify/functions/procedure-action/handler";
import { runIdForWakeKey } from "../../amplify/functions/procedure-action/wake-key";

// A data client holding the site's records in memory. A create over an existing id is refused with the error the scenario chose; the
// handler under test is the real one.
type Row = Record<string, unknown>;
type World = { runs: Map<string, Row>; refusal: unknown[]; answer?: Record<string, unknown>; failure?: Error };

const definition = { id: "def-1", procedureKey: "newsroom.fact-check", enabled: true, currentVersionId: "ver-1" };
const version = { id: "ver-1", versionNumber: 1, parameterSchema: "{}" };

function client(world: World) {
  const model = (rows: Map<string, Row>) => ({ get: async ({ id }: { id: string }) => ({ data: rows.get(id) ?? null }) });
  const runs = {
    ...model(world.runs),
    create: async (row: Row) => {
      if (world.runs.has(row.id as string)) return { data: null, errors: world.refusal };
      world.runs.set(row.id as string, row);
      return { data: row };
    },
  };
  return {
    models: {
      ProcedureDefinition: { ...model(new Map([[definition.id, definition]])), listProcedureDefinitionsByKeyAndUpdatedAt: async () => ({ data: [definition] }) },
      ProcedureVersion: model(new Map([[version.id, version]])),
      ProcedureRun: runs,
    },
  } as never;
}

const event = (wakeKey: string) => ({
  fieldName: "startNewsroomProcedureRun",
  arguments: { procedureKey: "newsroom.fact-check", wakeKey, input: JSON.stringify({ __papyrusExecutionMode: "external_cli" }) },
  identity: { sub: "person-1", username: "an editor" },
});

Given("a site whose procedure {string} is published", function (this: World, _key: string) {
  this.runs = new Map();
});
Given("the wake {string} already has its run record", function (this: World, key: string) {
  this.runs.set(runIdForWakeKey(key), { id: runIdForWakeKey(key), runStatus: "started" });
});
Given("the data API refuses the create with the error type {string} and a message it has not used before", function (this: World, type: string) {
  this.refusal = [{ errorType: type, message: "Mutation could not be applied (reworded by the platform)" }];
});
Given("the data API refuses the create with the message {string}", function (this: World, message: string) {
  this.refusal = [{ message }];
});
Given("the data API refuses the create with the error {string} that holds the error type {string}", function (this: World, message: string, type: string) {
  this.refusal = [{ message, originalError: { errorType: type } }];
});
Given("the data API refuses the create with the error type {string} and the message {string}", function (this: World, type: string, message: string) {
  this.refusal = [type === "(none)" ? { message } : { errorType: type, message }];
});

When("the wake {string} is started", async function (this: World, key: string) {
  try {
    this.answer = (await createHandler(async () => client(this))(event(key))) as Record<string, unknown>;
  } catch (error) {
    this.failure = error as Error;
  }
});

Then("the answer is a duplicate of the first run", function (this: World) {
  assert.equal(this.failure, undefined, this.failure?.message);
  assert.equal(this.answer?.duplicate, true);
  assert.equal(this.answer?.runId, runIdForWakeKey("fact-check|story-1|v7|story.stage_entered"));
  assert.equal(this.answer?.runStatus, "started");
});
Then("the answer says a run was created", function (this: World) {
  assert.equal(this.failure, undefined, this.failure?.message);
  assert.equal(this.answer?.duplicate, false);
});
Then("the start fails with {string}", function (this: World, text: string) {
  assert.equal(this.answer, undefined, "the start must not have answered");
  assert.match(this.failure?.message ?? "", new RegExp(text));
});
Then("the site still holds {int} run record", function (this: World, count: number) {
  assert.equal(this.runs.size, count);
});
Then("the site holds {int} run records", function (this: World, count: number) {
  assert.equal(this.runs.size, count);
});
