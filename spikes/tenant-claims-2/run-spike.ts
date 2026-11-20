// PPY-f4d892 driver. NOT YET RUN: needs the sandbox (npm run sandbox) and amplify_outputs.json.
// Usage: AWS_PROFILE=legacy AWS_REGION=us-east-1 SPIKE_SECRET=... npx tsx run-spike.ts
// Users are created without a password (AdminCreateUser, no invite) and sign in via the sandbox-only CUSTOM_AUTH challenge.
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import {
  CognitoIdentityProviderClient, AdminCreateUserCommand, InitiateAuthCommand, RespondToAuthChallengeCommand,
} from "@aws-sdk/client-cognito-identity-provider";

const out = JSON.parse(readFileSync("amplify_outputs.json", "utf8"));
const cognito = new CognitoIdentityProviderClient({ region: out.auth.aws_region });
const URL_ = out.data.url as string;
const SECRET = process.env.SPIKE_SECRET!;
const results: Record<string, unknown> = {};

async function signIn(email: string, tenant: string) {
  try { await cognito.send(new AdminCreateUserCommand({ UserPoolId: out.auth.user_pool_id, Username: email, MessageAction: "SUPPRESS", UserAttributes: [{ Name: "email", Value: email }, { Name: "email_verified", Value: "true" }] })); } catch (e: any) { if (e.name !== "UsernameExistsException") throw e; }
  const init = await cognito.send(new InitiateAuthCommand({ AuthFlow: "CUSTOM_AUTH", ClientId: out.auth.user_pool_client_id, AuthParameters: { USERNAME: email } }));
  const r = await cognito.send(new RespondToAuthChallengeCommand({ ClientId: out.auth.user_pool_client_id, ChallengeName: "CUSTOM_CHALLENGE", Session: init.Session, ChallengeResponses: { USERNAME: email, ANSWER: SECRET }, ClientMetadata: { tenant } }));
  return { id: r.AuthenticationResult!.IdToken!, access: r.AuthenticationResult!.AccessToken! };
}
const claims = (jwt: string) => JSON.parse(Buffer.from(jwt.split(".")[1], "base64url").toString());

async function gql(token: string, query: string, variables: object = {}) {
  const r = await fetch(URL_, { method: "POST", headers: { "content-type": "application/json", authorization: token }, body: JSON.stringify({ query, variables }) });
  return r.json() as Promise<{ data?: any; errors?: { message: string; errorType?: string }[] }>;
}
const pool = async <T,>(n: number, items: T[], fn: (x: T) => Promise<unknown>) => { let i = 0; await Promise.all(Array.from({ length: n }, async () => { while (i < items.length) await fn(items[i++]); })); };

const CREATE = `mutation($i: CreateReferenceInput!){ createReference(input:$i){ id tenantId } }`;
const UPDATE = `mutation($i: UpdateReferenceInput!){ updateReference(input:$i){ id tenantId tenantKey } }`;
const LIST_IDX = `query($k:String!,$limit:Int,$next:String){ listReferenceByTenantKey(tenantKey:$k, limit:$limit, nextToken:$next){ items{ id tenantId } nextToken } }`;
const LIST_STATUS = `query($limit:Int,$next:String){ listReferenceByStatus(status:"published", limit:$limit, nextToken:$next){ items{ id tenantId } nextToken } }`;

async function pages(token: string, q: string, vars: object) {
  const sizes: number[] = []; const tenants = new Set<string>(); let next: string | null = null;
  do {
    const r = await gql(token, q, { ...vars, limit: 100, next });
    const conn = Object.values(r.data ?? {})[0] as any;
    if (!conn) { sizes.push(-1); break; }
    sizes.push(conn.items.length); conn.items.forEach((x: any) => tenants.add(x.tenantId)); next = conn.nextToken;
  } while (next);
  return { sizes, tenants: [...tenants] };
}

const alpha = await signIn("alpha-editor@example.test", "alpha");
const beta = await signIn("beta-editor@example.test", "beta");
results.tokenClaims = { alphaIdHasClaim: claims(alpha.id).papyrus_tenant_editor, alphaAccessHasClaim: claims(alpha.access).papyrus_tenant_editor };
// Which token does AppSync accept with claims? (Amplify v6 sends the access token.)
results.accessTokenCall = (await gql(alpha.access, LIST_IDX, { k: "alpha#reference", limit: 1 })).errors ?? "ok";
results.idTokenCall = (await gql(alpha.id, LIST_IDX, { k: "alpha#reference", limit: 1 })).errors ?? "ok";

// Seed 300 + 300, interleaved so the shared "published" partition mixes tenants.
const jobs = Array.from({ length: 300 }, (_, n) => n).flatMap((n) => [["alpha", alpha, n], ["beta", beta, n]] as const);
await pool(10, [...jobs], async ([t, tok, n]) => { const r = await gql(tok.access, CREATE, { i: { tenantId: t, tenantKey: `${t}#reference`, status: "published", seq: n, title: `${t} ${n}` } }); if (r.errors) throw new Error(JSON.stringify(r.errors)); });

results.prefixedIndexAlpha = await pages(alpha.access, LIST_IDX, { k: "alpha#reference" });   // expect 3 x 100, only alpha
results.foreignPrefixAlpha = await pages(alpha.access, LIST_IDX, { k: "beta#reference" });     // expect empty
results.sharedPartitionAlpha = await pages(alpha.access, LIST_STATUS, {});                     // the trap: short pages
// Immutability
const one = (await gql(alpha.access, LIST_IDX, { k: "alpha#reference", limit: 1 })).data.listReferenceByTenantKey.items[0].id;
results.moveTenantId = (await gql(alpha.access, UPDATE, { i: { id: one, tenantId: "beta" } })).errors ?? "ALLOWED";
results.moveTenantKey = (await gql(alpha.access, UPDATE, { i: { id: one, tenantKey: "beta#reference" } })).errors ?? "ALLOWED";
results.foreignCreate = (await gql(alpha.access, CREATE, { i: { tenantId: "beta", tenantKey: "beta#reference", status: "published", seq: 999, title: "x" } })).errors ?? "ALLOWED";

// Subscriptions: alpha listens, beta creates; count what alpha receives.
async function listen(token: string, ms: number) {
  const host = new URL(URL_).host; const rt = host.replace("appsync-api", "appsync-realtime-api");
  const hdr = Buffer.from(JSON.stringify({ host, Authorization: token })).toString("base64");
  const ws = new WebSocket(`wss://${rt}/graphql?header=${hdr}&payload=e30=`, "graphql-ws");
  const got: string[] = []; let denied: unknown = null;
  ws.onopen = () => ws.send(JSON.stringify({ type: "connection_init" }));
  ws.onmessage = (m) => { const d = JSON.parse(String(m.data));
    if (d.type === "connection_ack") ws.send(JSON.stringify({ id: "1", type: "start", payload: { data: JSON.stringify({ query: "subscription { onCreateReference { id tenantId } }" }), extensions: { authorization: { host, Authorization: token } } } }));
    if (d.type === "data") got.push(d.payload.data.onCreateReference.tenantId);
    if (d.type === "error") denied = d.payload; };
  await new Promise((r) => setTimeout(r, ms)); ws.close(); return { got, denied };
}
const listening = listen(alpha.access, 20000);
await new Promise((r) => setTimeout(r, 5000));
for (const [t, tok] of [["beta", beta], ["alpha", alpha], ["beta", beta]] as const) await gql(tok.access, CREATE, { i: { tenantId: t, tenantKey: `${t}#reference`, status: "published", seq: 1000, title: "sub" } });
results.subscriptionAlpha = await listening; // expect only ["alpha"]

mkdirSync(".spike-results", { recursive: true });
writeFileSync(".spike-results/results.json", JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
