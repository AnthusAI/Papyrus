#!/usr/bin/env node
/**
 * Sandbox proof for Pretext staging (PPY-3e5e9d). Needs:
 *   - an `ampx sandbox --identifier wave2-prv` backend, with its outputs file at
 *     PAPYRUS_AMPLIFY_OUTPUTS (default ./amplify_outputs.json),
 *   - a staging server  (SITE_ENV=staging PAPYRUS_CONTENT_SOURCE=drafts)   at STAGING_URL,
 *   - a published server (SITE_ENV=production)                              at PRODUCTION_URL,
 *   - AWS credentials in the environment (AWS_PROFILE=legacy) for Cognito admin calls.
 * Test users get random in-memory passwords, are created and deleted here, and
 * nothing secret is printed.
 */
import { randomBytes, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { Amplify } from "aws-amplify";
import { signIn, signOut, fetchAuthSession } from "aws-amplify/auth";
import { generateClient } from "aws-amplify/data";
import { defaultStorage } from "aws-amplify/utils";
import {
  AdminAddUserToGroupCommand,
  AdminCreateUserCommand,
  AdminDeleteUserCommand,
  AdminSetUserPasswordCommand,
  CognitoIdentityProviderClient,
} from "@aws-sdk/client-cognito-identity-provider";

const outputsPath = path.resolve(process.env.PAPYRUS_AMPLIFY_OUTPUTS ?? "amplify_outputs.json");
const stagingUrl = process.env.STAGING_URL ?? "http://localhost:3001";
const productionUrl = process.env.PRODUCTION_URL ?? "http://localhost:3002";
const outputs = JSON.parse(readFileSync(outputsPath, "utf8"));
const userPoolId = outputs.auth.user_pool_id;
const userPoolClientId = outputs.auth.user_pool_client_id;
const bodyIr = JSON.parse(readFileSync(path.resolve("scripts/fixtures/body-ir/plain.json"), "utf8"));

const cognito = new CognitoIdentityProviderClient({ region: outputs.auth.aws_region });
const runId = randomBytes(4).toString("hex");
const draftSlug = `staging-auth-draft-${runId}`;
const draftHeadline = `Staging auth draft ${runId}`;

const results = [];
function record(name, passed, detail = "") {
  results.push({ name, passed });
  console.log(`${passed ? "PASS" : "FAIL"} ${name}${detail ? ` (${detail})` : ""}`);
}

async function createUser(group) {
  const username = `staging-auth-${group ?? "none"}-${runId}@example.com`;
  const password = `Aa1!${randomBytes(12).toString("base64url")}`;
  await cognito.send(new AdminCreateUserCommand({
    UserPoolId: userPoolId,
    Username: username,
    MessageAction: "SUPPRESS",
    UserAttributes: [{ Name: "email", Value: username }, { Name: "email_verified", Value: "true" }],
  }));
  await cognito.send(new AdminSetUserPasswordCommand({
    UserPoolId: userPoolId, Username: username, Password: password, Permanent: true,
  }));
  if (group) {
    await cognito.send(new AdminAddUserToGroupCommand({ UserPoolId: userPoolId, Username: username, GroupName: group }));
  }
  return { username, password };
}

async function deleteUser(username) {
  try {
    await cognito.send(new AdminDeleteUserCommand({ UserPoolId: userPoolId, Username: username }));
  } catch (error) {
    console.error(`cleanup: could not delete ${username}: ${error.name}`);
  }
}

async function sessionCookieHeader({ username, password }) {
  await signOut();
  await signIn({ username, password });
  const { tokens } = await fetchAuthSession();
  const subject = tokens.accessToken.payload.username;
  const prefix = `CognitoIdentityServiceProvider.${userPoolClientId}`;
  const refreshToken = await defaultStorage.getItem(`${prefix}.${subject}.refreshToken`);
  const cookies = {
    [`${prefix}.LastAuthUser`]: subject,
    [`${prefix}.${subject}.idToken`]: tokens.idToken.toString(),
    [`${prefix}.${subject}.accessToken`]: tokens.accessToken.toString(),
    [`${prefix}.${subject}.clockDrift`]: "0",
  };
  if (refreshToken) cookies[`${prefix}.${subject}.refreshToken`] = refreshToken;
  return Object.entries(cookies).map(([name, value]) => `${name}=${encodeURIComponent(value)}`).join("; ");
}

async function itemBySlugOverUserPool(client) {
  const response = await client.models.Item.itemBySlug({ slug: draftSlug }, { authMode: "userPool" });
  return response;
}

function isUnauthorized(response) {
  const text = JSON.stringify(response.errors ?? []);
  return /Unauthorized|not authorized/i.test(text);
}

const createdUsers = [];
let draftItemId = null;
let editorClient = null;
let editorCredentials = null;

try {
  // No { ssr: true }: its cookie token storage needs a browser `document`; this Node script builds the cookie header itself.
  Amplify.configure(outputs);

  const editor = await createUser("editor");
  const outsider = await createUser(null);
  createdUsers.push(editor.username, outsider.username);
  editorCredentials = { username: editor.username, password: editor.password };

  await signIn({ username: editor.username, password: editor.password });
  editorClient = generateClient();
  draftItemId = randomUUID();
  const lineageId = randomUUID();
  const created = await editorClient.models.Item.create({
    id: draftItemId,
    lineageId,
    versionNumber: 1,
    versionState: "current",
    versionCreatedAt: new Date().toISOString(),
    type: "article",
    status: "draft",
    typeStatus: "article#draft",
    slug: draftSlug,
    section: "news",
    headline: draftHeadline,
    title: draftHeadline,
    byline: "Staging Test",
    dateline: "NEWSROOM",
    publishedAt: new Date().toISOString(),
    bodyIr: JSON.stringify(bodyIr),
  }, { authMode: "userPool" });
  if (created.errors?.length) throw new Error(`could not create the draft Item: ${JSON.stringify(created.errors)}`);

  const editorRead = await itemBySlugOverUserPool(editorClient);
  record("editor reads the draft Item over userPool", editorRead.data?.[0]?.slug === draftSlug);

  const editorCookies = await sessionCookieHeader(editor);
  const editorPage = await fetch(new URL(`/articles/${draftSlug}`, stagingUrl), { headers: { cookie: editorCookies }, redirect: "manual" });
  const editorBody = await editorPage.text();
  record("editor gets 200 for the draft article on staging", editorPage.status === 200, `status ${editorPage.status}`);
  record("editor sees the draft headline", editorBody.includes(draftHeadline));
  record("editor sees the staging banner", editorBody.includes("data-staging-banner"));
  record("staging page is noindex", /<meta name="robots" content="noindex/.test(editorBody));

  const anonymousPage = await fetch(new URL(`/articles/${draftSlug}`, stagingUrl), { redirect: "manual" });
  record(
    "anonymous visitor is redirected to /newsroom",
    anonymousPage.status === 307 && new URL(anonymousPage.headers.get("location"), stagingUrl).pathname === "/newsroom",
    `status ${anonymousPage.status}`,
  );

  const outsiderCookies = await sessionCookieHeader(outsider);
  const outsiderPage = await fetch(new URL(`/articles/${draftSlug}`, stagingUrl), { headers: { cookie: outsiderCookies }, redirect: "manual" });
  const outsiderBody = await outsiderPage.text();
  record("signed-in non-editor gets 403 on staging", outsiderPage.status === 403, `status ${outsiderPage.status}`);
  record("403 body names the restriction", outsiderBody.includes("limited to editors and admins"));

  const outsiderClient = generateClient();
  const outsiderRead = await itemBySlugOverUserPool(outsiderClient);
  record(
    "signed-in non-editor is Unauthorized on Item over userPool",
    isUnauthorized(outsiderRead) || !(outsiderRead.data ?? []).length,
    isUnauthorized(outsiderRead) ? "Unauthorized" : "empty",
  );

  await signOut();
  const guestClient = generateClient();
  const guestRead = await guestClient.models.Item.itemBySlug({ slug: draftSlug }, { authMode: "identityPool" });
  record("guest cannot read the draft Item", isUnauthorized(guestRead) || !(guestRead.data ?? []).length);

  const publishedPage = await fetch(new URL(`/articles/${draftSlug}`, productionUrl), { redirect: "manual" });
  record("published (guest) server returns 404 for the draft slug", publishedPage.status === 404, `status ${publishedPage.status}`);
} catch (error) {
  record("script completed without an unexpected error", false, error.message);
} finally {
  if (draftItemId && editorCredentials) {
    try {
      await signOut();
      await signIn(editorCredentials);
      await generateClient().models.Item.delete({ id: draftItemId }, { authMode: "userPool" });
    } catch (error) {
      console.error(`cleanup: could not delete the draft Item: ${error.message}`);
    }
  }
  for (const username of createdUsers) await deleteUser(username);
}

const failed = results.filter((entry) => !entry.passed).length;
console.log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed === 0 ? 0 : 1);
