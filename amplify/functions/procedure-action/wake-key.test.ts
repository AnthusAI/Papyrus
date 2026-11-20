import assert from "node:assert/strict";
import { test } from "node:test";
import { assertWakeKey, isAlreadyCreated, runIdForWakeKey } from "./wake-key.ts";

test("the same wake key always gives the same run id, and different keys give different ids", () => {
  const key = "fact-check|story-1|v7|story.stage_entered";
  assert.equal(runIdForWakeKey(key), runIdForWakeKey(key));
  assert.match(runIdForWakeKey(key), /^procedure-run-wake-[0-9a-f]{32}$/);
  assert.notEqual(runIdForWakeKey(key), runIdForWakeKey("fact-check|story-1|v8|story.stage_entered"));
  assert.notEqual(runIdForWakeKey("rate|manual|r1"), runIdForWakeKey("rate|schedule|r1"));
});

test("a malformed wake key is refused", () => {
  for (const bad of ["", "one", "a|b", "a|b|c|", "a|x|c", "a|b|c|d|e", 7, null]) assert.throws(() => assertWakeKey(bad));
  assert.equal(assertWakeKey("rate|schedule|2026-11-17T08:00:00Z"), "rate|schedule|2026-11-17T08:00:00Z");
});

const TYPE = "DynamoDB:ConditionalCheckFailedException";

test("a create refused with the conditional-check error type is a duplicate, whatever its message says", () => {
  assert.equal(isAlreadyCreated([{ errorType: TYPE, message: "Something the platform may reword someday" }]), true);
  assert.equal(isAlreadyCreated([{ errorType: TYPE }]), true);
  assert.equal(isAlreadyCreated([{ errorType: "ConditionalCheckFailedException" }]), true);
  assert.equal(isAlreadyCreated([{ name: "ConditionalCheckFailedException" }]), true);
  assert.equal(isAlreadyCreated([{ __type: "com.amazonaws.dynamodb.v20120810#ConditionalCheckFailedException" }]), true);
  assert.equal(isAlreadyCreated([{ code: "ConditionalCheckFailedException" }]), true);
});

test("a create refused with the old text is a duplicate", () => {
  assert.equal(isAlreadyCreated([{ message: "The conditional request failed" }]), true);
  assert.equal(isAlreadyCreated(["DynamoDB:ConditionalCheckFailedException"]), true);
  assert.equal(isAlreadyCreated(["Mutation failed: ConditionalCheckFailed"]), true);
});

test("the conditional-check error nested inside another error is found", () => {
  assert.equal(isAlreadyCreated([{ message: "Request failed", originalError: { errorType: TYPE } }]), true);
  assert.equal(isAlreadyCreated([{ message: "Request failed", cause: { message: "The conditional request failed" } }]), true);
  assert.equal(isAlreadyCreated([{ message: "Request failed", extensions: { errorType: TYPE } }]), true);
  assert.equal(isAlreadyCreated([{ message: "Request failed", errors: [{ message: "Throttled" }, { errorType: TYPE }] }]), true);
  const loop: Record<string, unknown> = { message: "Request failed" };
  loop.cause = loop;
  assert.equal(isAlreadyCreated([loop]), false, "an error that contains itself ends and is not a duplicate");
});

test("any other create error is not a duplicate", () => {
  assert.equal(isAlreadyCreated([{ message: "Not authorized" }]), false);
  assert.equal(isAlreadyCreated([{ errorType: "DynamoDB:ProvisionedThroughputExceededException", message: "Throttled" }]), false);
  assert.equal(isAlreadyCreated([{ errorType: "Unauthorized", originalError: { errorType: "Throttled" } }]), false);
  assert.equal(isAlreadyCreated(["Timeout"]), false);
  assert.equal(isAlreadyCreated([null, 7 as never, {}]), false);
  assert.equal(isAlreadyCreated([]), false);
  assert.equal(isAlreadyCreated(null), false);
  assert.equal(isAlreadyCreated(undefined), false);
});
