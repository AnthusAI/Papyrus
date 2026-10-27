import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { derivePapyrusChatScope } from "../lib/papyrus-hosted-chat";

// Run the separate infrastructure package's harness (same reason as test-cloud-email-infra.ts).
const harness = fileURLToPath(new URL("../infra/amplify-app-shell/lib/chat.test.ts", import.meta.url));
const result = spawnSync(process.execPath, ["--import", "tsx", harness], { stdio: "inherit" });
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);

// Scenario: editor history stays isolated per site, issuer and subject. The chat namespace is the site's own
// bucket and table (plus the app client), so two sites never share a tenant or an editor.
const namespace = (bucket: string, table: string, clientId = "client") => JSON.stringify([bucket, table, clientId]);
const issuer = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_example";
const siteA = derivePapyrusChatScope(namespace("papyrus-chat-anth-us-bucket", "papyrus-chat-anth-us-messaging"), issuer, "editor-1");
const siteB = derivePapyrusChatScope(namespace("papyrus-chat-pilobol-us-bucket", "papyrus-chat-pilobol-us-messaging"), issuer, "editor-1");
assert.notEqual(siteA.tenantId, siteB.tenantId);
assert.notEqual(siteA.editorId, siteB.editorId);
const sameSite = namespace("papyrus-chat-anth-us-bucket", "papyrus-chat-anth-us-messaging");
assert.notEqual(derivePapyrusChatScope(sameSite, "https://other-issuer", "editor-1").editorId, siteA.editorId);
assert.notEqual(derivePapyrusChatScope(sameSite, issuer, "editor-2").editorId, siteA.editorId);
assert.deepEqual(derivePapyrusChatScope(sameSite, issuer, "editor-1"), siteA);
console.log("per-site chat identity isolation tests passed");
