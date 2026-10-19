import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import {
  MAXIMUM_PENDING_DELEGATION_REQUESTS,
  PENDING_DELEGATION_MINUTES,
  USER_CODE_ALPHABET,
  delegationVerdict,
  hashDelegationToken,
  normalizeUserCode,
  type CurationDelegation,
} from "../amplify/functions/shared/curation-delegation";
import {
  approveDelegation,
  delegationResult,
  denyDelegation,
  delegationStatus,
  livePendingRequests,
  requestDelegation,
  type DelegationStore,
} from "../amplify/functions/shared/curation-delegation-flow";

function inMemoryStore(): DelegationStore & { records: Map<string, CurationDelegation> } {
  const records = new Map<string, CurationDelegation>();
  return {
    records,
    read: async (id) => records.get(id) ?? null,
    write: async (delegation) => { records.set(delegation.delegationId, { ...delegation }); },
    listPending: async () => [...records.values()].filter((record) => record.grantorSub === "pending-device-authorization"),
  };
}

function agentSecret() {
  const delegationId = `curation-delegation-${randomUUID()}`;
  const token = `${delegationId}~agent-held-secret-${randomUUID()}`;
  return { delegationId, token, tokenHash: hashDelegationToken(token) };
}

const person = { sub: "sub-1", label: "editor@example.org", isAdmin: false };
const start = "2026-10-18T12:00:00.000Z";
const minutesAfter = (minutes: number) => new Date(Date.parse(start) + minutes * 60_000).toISOString();

async function requestFor(store: DelegationStore, agentLabel: string, now = start, hours?: number) {
  const secret = agentSecret();
  const response = await requestDelegation(store, { delegationId: secret.delegationId, tokenHash: secret.tokenHash, agentLabel, hours }, now);
  return { ...secret, response };
}

async function main() {
  const store = inMemoryStore();
  const agent = await requestFor(store, "curator", start, 4);
  assert.match(agent.response.userCode, /^[A-Z2-9]{4}-[A-Z2-9]{4}$/);
  for (const character of agent.response.userCode.replace("-", "")) assert.ok(USER_CODE_ALPHABET.includes(character));
  assert.equal(agent.response.pendingExpiresAt, minutesAfter(PENDING_DELEGATION_MINUTES));
  assert.equal(agent.response.requestedHours, 4);
  assert.deepEqual(await delegationStatus(store, agent.delegationId, start), {
    delegationId: agent.delegationId, state: "pending", expiresAt: agent.response.pendingExpiresAt, grantorLabel: null,
  });
  assert.deepEqual(
    delegationVerdict(store.records.get(agent.delegationId)!, { token: agent.token, agentLabel: "curator", now: start }),
    { ok: false, reason: "not-approved" },
  );

  const approvalTime = minutesAfter(3);
  const approved = await approveDelegation(store, person, agent.response.userCode.toLowerCase().replace("-", " "), approvalTime);
  assert.equal(approved.state, "approved");
  assert.equal(approved.grantorLabel, person.label);
  assert.equal(approved.expiresAt, new Date(Date.parse(approvalTime) + 4 * 3_600_000).toISOString());
  assert.equal(approved.userCode, null);
  const stored = store.records.get(agent.delegationId)!;
  assert.equal(stored.grantorSub, person.sub);
  assert.deepEqual(delegationVerdict(stored, { token: agent.token, agentLabel: "Curator", now: approvalTime }), { ok: true });
  assert.deepEqual(delegationVerdict(stored, { token: agent.token, agentLabel: "someone-else", now: approvalTime }), { ok: false, reason: "wrong-agent" });
  assert.deepEqual(delegationVerdict(stored, { token: `${agent.delegationId}~guess`, agentLabel: "curator", now: approvalTime }), { ok: false, reason: "unknown-token" });
  assert.deepEqual(await delegationStatus(store, agent.delegationId, approvalTime), {
    delegationId: agent.delegationId, state: "approved", expiresAt: approved.expiresAt, grantorLabel: person.label,
  });
  await assert.rejects(approveDelegation(store, person, agent.response.userCode, approvalTime), /No pending delegation request/);

  const revokedAt = minutesAfter(30);
  store.records.set(agent.delegationId, { ...stored, revokedAt });
  assert.equal((await delegationStatus(store, agent.delegationId, revokedAt)).state, "revoked");
  assert.deepEqual(delegationVerdict(store.records.get(agent.delegationId)!, { token: agent.token, agentLabel: "curator", now: revokedAt }), { ok: false, reason: "revoked" });

  const lapsed = await requestFor(store, "lapsing");
  const afterLapse = minutesAfter(PENDING_DELEGATION_MINUTES + 1);
  assert.equal((await delegationStatus(store, lapsed.delegationId, afterLapse)).state, "expired");
  assert.deepEqual(
    delegationVerdict(store.records.get(lapsed.delegationId)!, { token: lapsed.token, agentLabel: "lapsing", now: afterLapse }),
    { ok: false, reason: "not-approved" },
  );
  await assert.rejects(approveDelegation(store, person, lapsed.response.userCode, afterLapse), /No pending delegation request/);
  assert.equal((await livePendingRequests(store, afterLapse)).length, 0);
  assert.equal(store.records.get(lapsed.delegationId)!.grantorSub, "expired-device-authorization");

  const refused = await requestFor(store, "refused");
  const denied = await denyDelegation(store, person, refused.response.userCode, minutesAfter(1));
  assert.equal(denied.state, "denied");
  assert.equal((await delegationStatus(store, refused.delegationId, minutesAfter(2))).state, "denied");
  assert.deepEqual(
    delegationVerdict(store.records.get(refused.delegationId)!, { token: refused.token, agentLabel: "refused", now: minutesAfter(2) }),
    { ok: false, reason: "not-approved" },
  );
  await assert.rejects(denyDelegation(store, person, refused.response.userCode, minutesAfter(2)), /No pending delegation request/);
  await assert.rejects(approveDelegation(store, person, refused.response.userCode, minutesAfter(2)), /No pending delegation request/);

  await assert.rejects(approveDelegation(store, person, "ZZZZ-ZZZZ", start), /No pending delegation request/);
  await assert.rejects(approveDelegation(store, person, "not a code", start), /No pending delegation request/);
  await assert.rejects(approveDelegation(store, person, "", start), /No pending delegation request/);
  await assert.rejects(delegationStatus(store, "curation-delegation-unknown", start), /not found/);

  const crowded = inMemoryStore();
  const codes = new Set<string>();
  for (let index = 0; index < MAXIMUM_PENDING_DELEGATION_REQUESTS; index += 1) {
    codes.add((await requestFor(crowded, `agent${index}`)).response.userCode);
  }
  assert.equal(codes.size, MAXIMUM_PENDING_DELEGATION_REQUESTS);
  await assert.rejects(requestFor(crowded, "one-too-many"), /Too many delegation requests/);
  const roomAgain = await requestFor(crowded, "after-lapse", afterLapse);
  assert.ok(roomAgain.response.userCode);

  const hygiene = inMemoryStore();
  const first = await requestFor(hygiene, "first");
  const duplicate = agentSecret();
  await requestDelegation(hygiene, { ...duplicate, agentLabel: "x", hours: null }, start);
  await assert.rejects(requestDelegation(hygiene, { ...duplicate, agentLabel: "x", hours: null }, start), /already in use/);
  await assert.rejects(requestDelegation(hygiene, { ...agentSecret(), delegationId: "curation-delegation-1", agentLabel: "x", hours: null }, start), /must look like/);
  await assert.rejects(requestDelegation(hygiene, { ...agentSecret(), tokenHash: "abc", agentLabel: "x", hours: null }, start), /64 lowercase/);
  await assert.rejects(requestDelegation(hygiene, { ...agentSecret(), agentLabel: "   ", hours: null }, start), /Name the agent/);
  await assert.rejects(requestDelegation(hygiene, { ...agentSecret(), agentLabel: "x", hours: 500 }, start), /between 1 and 72/);
  assert.equal(first.response.requestedHours, 8);
  assert.equal(normalizeUserCode("abcd-efgh"), "ABCDEFGH");
  assert.equal(normalizeUserCode("ABCD-EFG0"), null);

  const shaped = [agent.response, approved, denied, await delegationStatus(store, agent.delegationId, start)];
  for (const output of shaped) {
    const text = JSON.stringify(output);
    assert.ok(!("tokenHash" in output));
    assert.ok(!text.includes(agent.token) && !text.includes(agent.tokenHash) && !text.includes("agent-held-secret"));
  }
  const listed = (await livePendingRequests(crowded, start)).map((record) => delegationResult(record, start));
  for (const output of listed) {
    const text = JSON.stringify(output);
    assert.ok(!text.includes("tokenHash") && !text.includes("agent-held-secret"));
    assert.match(output.userCode ?? "", /^[A-Z2-9]{4}-[A-Z2-9]{4}$/);
  }
  console.log("curation delegation device flow: ok");
}

main();
