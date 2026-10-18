import assert from "node:assert/strict";
import {
  buildDelegatedCommandLine,
  delegationExpiryText,
  describeDelegationError,
  isDelegationActive,
  validateDelegationInput,
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

assert.deepEqual(validateDelegationInput(" curator ", "8"), { ok: true, agentLabel: "curator", hours: 8 });
assert.equal(validateDelegationInput("", "8").ok, false);
assert.equal(validateDelegationInput("two words", "8").ok, false);
for (const bad of ["0", "73", "1.5", "abc", "", "-2"]) assert.equal(validateDelegationInput("a", bad).ok, false, bad);
assert.equal(validateDelegationInput("a", "72").ok, true);
assert.equal(validateDelegationInput("a", "1").ok, true);

assert.equal(
  buildDelegatedCommandLine({ email: "ryan@example.com", agentLabel: "curator", token: "t~abc", action: "reject" }),
  "papyrus references reject <reference-id> --on-behalf-of ryan@example.com --agent curator --delegation-token t~abc",
);
assert.match(buildDelegatedCommandLine({ email: "", agentLabel: "c", token: "t" }), /--on-behalf-of <your-email>/);

assert.match(describeDelegationError(new Error("Not Authorized to access")), /Only editors and administrators/);
assert.match(describeDelegationError(new Error("A delegation lasts between 1 and 72 hours.")), /server refused/);
assert.match(describeDelegationError(null), /Nothing was changed/);
console.log("curation delegation helpers ok");
