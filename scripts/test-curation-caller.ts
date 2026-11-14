import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { classifyCurationCaller, requireDelegationAgent, requireDelegationApprover, tokenClientId } from "../amplify/functions/shared/curation-caller";

const clients = { web: "web", cli: "cli", mcp: "mcp" };
const caller = (claims: Record<string, unknown>) => classifyCurationCaller({ claims }, clients);
const editor = { sub: "person", "cognito:groups": ["editor"] };
assert.equal(caller({ ...editor, token_use: "access", client_id: "cli", aud: "https://resource" }).lane, "cli-session");
assert.equal(caller({ ...editor, token_use: "id", aud: "web" }).lane, "newsroom-session");
assert.equal(tokenClientId({ token_use: "id", client_id: "web" }), null);
assert.equal(tokenClientId({ token_use: "access", aud: "web" }), null);
assert.equal(tokenClientId({ aud: "web", client_id: "cli" }), null);
for (const claims of [{ ...editor, aud: "mcp" }, { ...editor, aud: "unknown" }, { ...editor }, { aud: "web", "cognito:groups": ["editor"] }]) {
  assert.throws(() => requireDelegationApprover(caller(claims)));
}
assert.throws(() => requireDelegationApprover(caller({ ...editor, aud: "web", "cognito:groups": ["reader"] })));
assert.equal(requireDelegationApprover(caller({ ...editor, aud: "web" })).sub, "person");
assert.throws(() => requireDelegationAgent(caller({ ...editor, aud: "mcp" })));
const sharedAgentClient = { ...clients, mcp: "cli" };
assert.throws(() => requireDelegationAgent(classifyCurationCaller({ claims: { ...editor, aud: "cli" } }, sharedAgentClient)));
assert.equal(requireDelegationApprover(classifyCurationCaller({ claims: { ...editor, aud: "web" } }, sharedAgentClient)).sub, "person");
assert.throws(() => requireDelegationApprover(classifyCurationCaller({ claims: { ...editor, aud: "web" } }, { ...clients, mcp: "web" })));
assert.throws(() => requireDelegationAgent(classifyCurationCaller({ claims: {}, userArn: "arn:aws:sts::1:assumed-role/x/y", accountId: "1" }, clients)));
requireDelegationAgent(classifyCurationCaller({ userArn: "arn:aws:sts::1:assumed-role/x/y", accountId: "1" }, clients));
const backend = readFileSync("amplify/site-backend.ts", "utf8");
assert.match(backend, /addEnvironment\("CURATION_WEB_CLIENT_ID",\s*backend\.auth\.resources\.userPoolClient\.userPoolClientId\)/);
console.log("curation caller classification: ok");
