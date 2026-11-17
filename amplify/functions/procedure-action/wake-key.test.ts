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

test("a refused duplicate create is recognised", () => {
  assert.equal(isAlreadyCreated([{ message: "The conditional request failed" }]), true);
  assert.equal(isAlreadyCreated(["DynamoDB:ConditionalCheckFailedException"]), true);
  assert.equal(isAlreadyCreated([{ message: "Not authorized" }]), false);
  assert.equal(isAlreadyCreated(null), false);
});
