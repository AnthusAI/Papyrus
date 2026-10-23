import assert from "node:assert/strict";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import type {
  ChatRequest,
  ChatIdempotencyStore,
  SharedChatAdmissionDependencies,
  VerifiedChatCredential,
} from "../lib/shared-chat-admission";

type AdmissionErrorCode = "unauthorized" | "forbidden" | "invalid_request" | "idempotency_conflict";

const token: VerifiedChatCredential = {
  subject: "editor-sub-a",
  issuer: "https://cognito.example/pool-a",
  audiences: ["papyrus-client-a"],
  clientId: "papyrus-client-a",
  tokenUse: "configured-host-token-use",
  expiresAtEpochSeconds: 2_000,
};

const trust = {
  issuer: "https://cognito.example/pool-a",
  audienceRule: { claim: "aud" as const, expectedValue: "papyrus-client-a" },
  acceptedTokenUses: ["configured-host-token-use"],
  configuredSiteId: "site-a",
  clockSkewSeconds: 0,
};

function dependencies(overrides: Partial<SharedChatAdmissionDependencies> = {}): SharedChatAdmissionDependencies {
  return {
    trust,
    nowEpochSeconds: () => 1_000,
    verifyCredential: async (raw) => raw === "good-token" ? token : null,
    resolveMembership: async (subject, siteId) => subject === "editor-sub-a" && siteId === "site-a"
      ? { accountId: "account-a", siteId: "site-a", editorSub: subject, active: true }
      : null,
    resolveTranscriptOwner: async (channelId) => ({ accountId: "account-a", siteId: "site-a", editorSub: "editor-sub-a", channelId }),
    ...overrides,
  };
}

function request(overrides: Partial<ChatRequest> = {}) {
  return {
    authorization: "Bearer good-token",
    channelId: "channel-a",
    idempotencyKey: "request-key-000001",
    message: { text: "Hello" },
    ...overrides,
  };
}

async function rejectsCode(promise: Promise<unknown>, code: AdmissionErrorCode, label: string) {
  await assert.rejects(promise, (error: unknown) => error instanceof Error && error.name === "ChatAdmissionError"
    && (error as Error & { code?: string }).code === code, label);
}

async function main() {
  const { admitSharedChatMessage, ChatAdmissionError, runAdmittedChatMessage } = await import(
    pathToFileURL(resolve(process.cwd(), "lib/shared-chat-admission.ts")).href
  );
  const accepted = await admitSharedChatMessage(request(), dependencies());
  assert.deepEqual(accepted.owner, { accountId: "account-a", siteId: "site-a", editorSub: "editor-sub-a", channelId: "channel-a" }, "host membership supplies the owner tuple");

  await rejectsCode(admitSharedChatMessage(request(), dependencies({
    verifyCredential: async () => ({ ...token, issuer: "https://attacker.invalid" }),
  })), "unauthorized", "wrong issuer rejected");
  await rejectsCode(admitSharedChatMessage(request(), dependencies({
    verifyCredential: async () => ({ ...token, audiences: ["other-client"], clientId: "papyrus-client-a" }),
  })), "unauthorized", "client_id does not substitute for a mismatched aud");
  const clientIdContract = await admitSharedChatMessage(request(), dependencies({
    trust: { ...trust, audienceRule: { claim: "client_id", expectedValue: "papyrus-client-a" } },
  }));
  assert.equal(clientIdContract.owner.editorSub, "editor-sub-a", "host may explicitly select client_id when that is its verified token contract");
  await rejectsCode(admitSharedChatMessage(request(), dependencies({
    verifyCredential: async () => ({ ...token, tokenUse: "unconfigured-token-use" }),
  })), "unauthorized", "unconfigured token_use rejected");
  await rejectsCode(admitSharedChatMessage(request(), dependencies({
    verifyCredential: async () => ({ ...token, expiresAtEpochSeconds: 999 }),
  })), "unauthorized", "expired credential rejected");
  await rejectsCode(admitSharedChatMessage(request(), dependencies({
    verifyCredential: async () => ({ ...token, notBeforeEpochSeconds: 1_001 }),
  })), "unauthorized", "not-yet-valid credential rejected");
  await rejectsCode(admitSharedChatMessage(request({ authorization: undefined }), dependencies()), "unauthorized", "missing bearer rejected");
  await rejectsCode(admitSharedChatMessage(request(), dependencies({ resolveMembership: async () => null })), "forbidden", "non-member rejected");
  await rejectsCode(admitSharedChatMessage(request(), dependencies({ resolveMembership: async (subject, siteId) => ({ accountId: "account-a", siteId, editorSub: subject, active: false }) })), "forbidden", "inactive membership rejected");
  await rejectsCode(admitSharedChatMessage(request(), dependencies({ resolveMembership: async () => ({ accountId: "account-a", siteId: "other-site", editorSub: "editor-sub-a", active: true }) })), "forbidden", "membership from another site rejected");
  await rejectsCode(admitSharedChatMessage(request({ message: { text: "Hello", authorSub: "editor-sub-b" } }), dependencies()), "forbidden", "client cannot claim another author");
  await rejectsCode(admitSharedChatMessage(request({ message: { text: "Hello", accountId: "account-b" } }), dependencies()), "forbidden", "client cannot select another Account");
  await rejectsCode(admitSharedChatMessage(request(), dependencies({
    resolveTranscriptOwner: async () => ({ accountId: "account-a", siteId: "site-a", editorSub: "editor-sub-b", channelId: "channel-a" }),
  })), "forbidden", "cross-editor transcript rejected");

  const storeState = new Map<string, { fingerprint: string; result: unknown }>();
  const store: ChatIdempotencyStore = {
    async executeOnce<T>(input: { scope: string; key: string; payloadFingerprint: string; run: () => Promise<T> }): Promise<T> {
      const composite = `${input.scope}:${input.key}`;
      const existing = storeState.get(composite);
      if (existing) {
        if (existing.fingerprint !== input.payloadFingerprint) throw new ChatAdmissionError("idempotency_conflict");
        return existing.result as T;
      }
      const result = await input.run();
      storeState.set(composite, { fingerprint: input.payloadFingerprint, result });
      return result;
    },
  };
  let operationCalls = 0;
  const first = await runAdmittedChatMessage(accepted, store, async () => ({ messageId: `message-${++operationCalls}` }));
  const replay = await runAdmittedChatMessage(accepted, store, async () => ({ messageId: `message-${++operationCalls}` }));
  assert.deepEqual(replay, first, "same scoped key and payload replays the canonical result");
  assert.equal(operationCalls, 1, "replay creates no second message");

  const changedPayload = await admitSharedChatMessage(request({ message: { text: "Different body" } }), dependencies());
  await rejectsCode(runAdmittedChatMessage(changedPayload, store, async () => "must not run"), "idempotency_conflict", "same key with changed body rejected");

  const otherEditorDependencies = dependencies({
    verifyCredential: async () => ({ ...token, subject: "editor-sub-b" }),
    resolveMembership: async (subject, siteId) => ({ accountId: "account-a", siteId, editorSub: subject, active: true }),
    resolveTranscriptOwner: async (channelId) => ({ accountId: "account-a", siteId: "site-a", editorSub: "editor-sub-b", channelId }),
  });
  const otherEditor = await admitSharedChatMessage(request(), otherEditorDependencies);
  let otherEditorCalls = 0;
  await runAdmittedChatMessage(otherEditor, store, async () => { otherEditorCalls += 1; return "other editor"; });
  assert.equal(otherEditorCalls, 1, "same opaque key is isolated by server-derived editor scope");

  await rejectsCode(admitSharedChatMessage(request({ idempotencyKey: "short" }), dependencies()), "invalid_request", "malformed key rejected");
  console.log("PASS: shared chat admission contract, trust-profile rejections, transcript ownership and scoped idempotency");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
