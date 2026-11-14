import assert from "node:assert/strict";
import {
  delegationExpiry, delegationIdFromToken, delegationVerdict, hashDelegationToken, newDelegationToken, type CurationDelegation,
} from "../amplify/functions/shared/curation-delegation";
import { referenceVoteFields } from "../amplify/functions/shared/reference-curation-metadata";

const { token, tokenHash } = newDelegationToken("curation-delegation-1");
assert.equal(delegationIdFromToken(token), "curation-delegation-1");
assert.equal(delegationIdFromToken("no-separator"), null);
assert.equal(tokenHash, hashDelegationToken(token));
assert.notEqual(newDelegationToken("curation-delegation-1").token, token);

const now = "2026-10-18T12:00:00.000Z";
const delegation: CurationDelegation = {
  delegationId: "d1", tokenHash, grantorSub: "sub-1", grantorLabel: "editor@example.org", agentLabel: "ChatGPT",
  createdAt: now, expiresAt: delegationExpiry(now, 8), revokedAt: null,
};
assert.equal(delegation.expiresAt, "2026-10-18T20:00:00.000Z");
assert.deepEqual(delegationVerdict(delegation, { token, agentLabel: "chatgpt", now }), { ok: true });
assert.deepEqual(delegationVerdict(delegation, { token: "curation-delegation-1~other", agentLabel: "ChatGPT", now }), { ok: false, reason: "unknown-token" });
assert.deepEqual(delegationVerdict(null, { token, agentLabel: "ChatGPT", now }), { ok: false, reason: "unknown-token" });
assert.deepEqual(delegationVerdict(delegation, { token, agentLabel: "Claude", now }), { ok: false, reason: "wrong-agent" });
assert.deepEqual(delegationVerdict({ ...delegation, revokedAt: now }, { token, agentLabel: "ChatGPT", now }), { ok: false, reason: "revoked" });
assert.deepEqual(delegationVerdict(delegation, { token, agentLabel: "ChatGPT", now: "2026-10-18T20:00:00.000Z" }), { ok: false, reason: "expired" });
assert.throws(() => delegationExpiry(now, 0));
assert.throws(() => delegationExpiry(now, 500));

const vote = referenceVoteFields({
  actorKind: "human", delegation: { delegationId: "d1", relayedBy: "ChatGPT", instruction: "Yes, approve the Anthropic advisory." },
});
assert.equal(vote.curationActorKind, "human");
assert.deepEqual(JSON.parse(vote.curationDelegation as string), {
  delegationId: "d1", relayedBy: "ChatGPT", instruction: "Yes, approve the Anthropic advisory.",
});

console.log("curation delegation: ok");
