import assert from "node:assert/strict";
import test from "node:test";
import { runReferenceReviewRequest } from "../lib/reference-review-request";

test("repeated clicks share one pending save, and a failed save can be retried", async () => {
  const pending = new Map<string, Promise<void>>();
  let calls = 0;
  let fail!: (error: Error) => void;
  const save = () => { calls += 1; return new Promise<void>((_resolve, reject) => { fail = reject; }); };
  const first = runReferenceReviewRequest(pending, "reference-a", save);
  const repeated = runReferenceReviewRequest(pending, "reference-a", save);
  assert.equal(first, repeated, "a second click must not create another curation Message");
  await Promise.resolve();
  assert.equal(calls, 1);
  fail(new Error("Permission expired"));
  await assert.rejects(first, /Permission expired/);
  assert.equal(pending.size, 0);
  await runReferenceReviewRequest(pending, "reference-a", async () => { calls += 1; });
  assert.equal(calls, 2, "explicit retry after a refusal is allowed");
});

test("different references save independently and synchronous failures release their lock", async () => {
  const pending = new Map<string, Promise<void>>();
  let finish!: () => void;
  const first = runReferenceReviewRequest(pending, "reference-a", () => new Promise<void>((resolve) => { finish = resolve; }));
  await runReferenceReviewRequest(pending, "reference-b", async () => undefined);
  assert.equal(pending.has("reference-a"), true);
  finish();
  await first;
  await assert.rejects(runReferenceReviewRequest(pending, "reference-a", () => { throw new Error("Invalid reason"); }), /Invalid reason/);
  assert.equal(pending.size, 0);
});
