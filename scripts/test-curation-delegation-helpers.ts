import assert from "node:assert/strict";
import {
  delegationExpiryText,
  describeDelegationError,
  isDelegationActive,
  delegationStateText,
  isPendingDelegation,
  pendingCountdownText,
  requestedHoursText,
} from "../lib/curation-delegation-helpers";

const now = Date.parse("2026-10-18T12:00:00.000Z");
const inHours = (hours: number) => new Date(now + hours * 3_600_000).toISOString();

assert.equal(delegationExpiryText(inHours(8), null, now), "Expires in 8 hours");
assert.equal(delegationExpiryText(inHours(1), null, now), "Expires in 1 hour");
assert.equal(delegationExpiryText(new Date(now + 90_000).toISOString(), null, now), "Expires in 2 minutes");
assert.equal(delegationExpiryText(inHours(-1), null, now), "Expired");
assert.equal(delegationExpiryText(inHours(5), new Date(now).toISOString(), now), "Revoked");

const record = { delegationId: "d", agentLabel: "a", grantorLabel: null, expiresAt: inHours(2), revokedAt: null };
assert.equal(isDelegationActive(record, now), true);
assert.equal(isDelegationActive({ ...record, revokedAt: "x" }, now), false);
assert.equal(isDelegationActive({ ...record, expiresAt: inHours(-1) }, now), false);

const pending = { ...record, state: "pending" as const, userCode: "WDJB-MJHT", requestedHours: 1, pendingExpiresAt: new Date(now + 9 * 60_000 + 30_000).toISOString(), expiresAt: new Date(now + 9 * 60_000 + 30_000).toISOString() };
assert.equal(isPendingDelegation(pending, now), true);
assert.equal(isPendingDelegation({ ...pending, userCode: null }, now), false, "a pending request without a code cannot be approved");
assert.equal(isPendingDelegation({ ...pending, state: "approved" }, now), false);
assert.equal(isPendingDelegation(pending, now + 10 * 60_000), false, "a lapsed request is not listed as pending");
assert.equal(pendingCountdownText(pending.pendingExpiresAt, now), "9:30 left");
assert.equal(pendingCountdownText(pending.pendingExpiresAt, now + 9 * 60_000 + 25_000), "0:05 left");
assert.equal(pendingCountdownText(pending.pendingExpiresAt, now + 10 * 60_000), "Expired");
assert.equal(pendingCountdownText(null, now), "Expired");
assert.equal(requestedHoursText(1), "Asks for 1 hour");
assert.equal(requestedHoursText(8), "Asks for 8 hours");
assert.equal(requestedHoursText(null), "Duration not stated");
assert.equal(delegationStateText({ ...record, state: "denied" }, now), "Denied");
assert.equal(delegationStateText({ ...record, state: "approved" }, now), "Expires in 2 hours");
assert.equal(delegationStateText({ ...record, state: "revoked", revokedAt: "x" }, now), "Revoked");
assert.equal(delegationStateText({ ...pending, pendingExpiresAt: inHours(-1), expiresAt: inHours(-1) }, now), "Request expired");

assert.match(describeDelegationError(new Error("Not Authorized to access")), /Only editors and administrators/);
assert.match(describeDelegationError(new Error("A delegation lasts between 1 and 72 hours.")), /server refused/);
assert.match(describeDelegationError(null), /Nothing was changed/);
console.log("curation delegation helpers ok");
