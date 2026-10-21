import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { loadCurationBootstrap } from "../components/newsroom-curation-bootstrap";
import { CURATION_MAXIMUM_REQUEST_BYTES, CURATION_MAXIMUM_RESPONSE_BYTES, UPSTREAM_REFUSAL_MESSAGES, handleCurationRoute, primingCapability, type CurationRoute, type CurationRouteOptions } from "../lib/curation-routes";
import { PROSPECTUS_SESSION_COOKIE, sealProspectusCookie, type ProspectusSignInRuntime } from "../lib/prospectus-session";
import { ProspectusAccountsError, ProspectusSiteAccounts, type ProspectusRequest } from "../lib/prospectus-site-identity";

const sealingSecret = "synthetic-sealing-secret-0123456789abcdefghijklmnopqrstuvwxyz";
const origin = "https://p.apyr.us";
const now = 1_000;
const accessToken = "synthetic-access-token-SECRET-1234";
const person = { id: "person-1", createdAt: "2026-01-01T00:00:00Z" };
const scope = { accountId: "account-1", publicationId: "pub-1", bindingRevision: "binding-1" };
const pinHeaders = { "x-cyclotron-account": "account-1", "x-papyrus-publication": "pub-1", "x-papyrus-binding": "binding-1" };

type World = { role: string; removed: boolean; refuse: boolean; onDirectory?: () => void };

function cookieFor(selectedAccountId: string | null = "account-1", expiresAt = 5_000, token = accessToken): string {
  const session = { personId: "person-1", accessToken: token, accessTokenExpiresAt: expiresAt, ...(selectedAccountId ? { selectedAccountId } : {}) };
  return `${PROSPECTUS_SESSION_COOKIE}=${sealProspectusCookie(sealingSecret, PROSPECTUS_SESSION_COOKIE, session, expiresAt)}`;
}

function worldRuntime(world: World) {
  const prospectusCalls: ProspectusRequest[] = [];
  const runtime: ProspectusSignInRuntime = {
    accounts: new ProspectusSiteAccounts(async (request) => {
      prospectusCalls.push(request);
      if (request.path === "/v1/account-directory") {
        world.onDirectory?.();
        return { person, accounts: world.removed ? [] : [{ id: "account-1", name: "A", role: world.role, products: [{ product: "papyrus-p-apyr-us", status: "active" }] }] };
      }
      if (request.path === "/v1/identities/me") return { person };
      if (request.path === "/v1/accounts/account-1/authorize") {
        if (world.refuse) throw new ProspectusAccountsError(403, "forbidden", "no");
        return { allowed: true, accountId: "account-1", personId: "person-1", product: "papyrus-p-apyr-us", role: world.role, operation: "console:read", revision: 1 };
      }
      throw new Error(`unexpected ${request.path}`);
    }),
    cognitoClient: { hostedUiOrigin: "https://h", userPoolId: "p", clientId: "c", redirectUri: "https://p.apyr.us/cb" },
    sealingSecret,
  };
  return { runtime, prospectusCalls };
}

type UpstreamCall = { url: string; init: RequestInit };
function setup(overrides: Partial<World> = {}, upstream?: (call: UpstreamCall) => Response | Promise<Response>) {
  const world: World = { role: "member", removed: false, refuse: false, ...overrides };
  const { runtime, prospectusCalls } = worldRuntime(world);
  const upstreamCalls: UpstreamCall[] = [];
  const fetcher = (async (input: URL | string, init: RequestInit) => {
    const call = { url: String(input), init };
    upstreamCalls.push(call);
    return (upstream ?? defaultUpstream)(call);
  }) as unknown as typeof fetch;
  const options: CurationRouteOptions = {
    resolveRuntime: async () => runtime, nowInSeconds: () => now, siteProduct: "papyrus-p-apyr-us",
    upstreamUrl: "https://lab.example.test", publicationId: "pub-1", fetcher,
  };
  return { world, options, prospectusCalls, upstreamCalls };
}

function defaultUpstream(call: UpstreamCall): Response {
  const headers = { "content-type": "application/json", ...pinHeaders };
  if (call.url.endsWith("/context")) {
    return Response.json({ scope, mode: "remote", priming: { listId: "examples", classifiers: [{ id: "c", revision: 1 }], transformers: [] }, capabilities: ["read", "review"], bindingRef: null }, { headers });
  }
  if (call.url.endsWith("/publication")) return Response.json({ contractVersion: "cyclotron-publication/v1", ...scope, outputs: [] }, { headers });
  return Response.json({ data: { primingContract: {} } }, { headers });
}

function post(route: CurationRoute, body: unknown, { cookie = cookieFor(), headers = pinHeaders, originHeader = origin as string | null, contentType = "application/json" } = {}): NextRequest {
  return new NextRequest(new URL(`/api/newsroom/curation/${route}`, origin), {
    method: "POST",
    headers: { ...(cookie ? { cookie } : {}), ...(contentType ? { "content-type": contentType } : {}), ...(originHeader ? { origin: originHeader } : {}), ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function get(cookie: string | null = cookieFor(), originHeader?: string): NextRequest {
  return new NextRequest(new URL("/api/newsroom/curation/context", origin), { headers: { ...(cookie ? { cookie } : {}), ...(originHeader ? { origin: originHeader } : {}) } });
}

const statusBody = { operation: "status", payload: {} };
const primingQuery = { query: "query($list:ID!,$refs:JSON!){primingContract(listId:$list,classifiers:$refs)}", variables: { list: "examples", refs: [] } };
const primingMutation = { query: "mutation($action:String!,$payload:JSON!){primingCommand(action:$action,payload:$payload)}", variables: { action: "file", payload: {} } };

async function assertNoLeak(response: Response, label: string) {
  const text = JSON.stringify([await response.clone().text(), [...response.headers.entries()]]);
  assert.ok(!text.includes(accessToken) && !text.includes("SECRET"), `${label}: no token in the response`);
}

async function main() {
  const logged: string[] = [];
  const originalError = console.error;
  console.error = (...args: unknown[]) => { logged.push(args.map(String).join(" ")); };

  // Not configured.
  {
    const { options, upstreamCalls } = setup();
    for (const upstreamUrl of [null, "", "not a url", "http://lab.example.test", "https://user:pw@lab.example.test"]) {
      const response = await handleCurationRoute(post("priming", primingQuery), "priming", { ...options, upstreamUrl });
      assert.equal(response.status, 503, `upstream ${JSON.stringify(upstreamUrl)}`);
      assert.equal((await response.json()).error, "curation_not_configured");
    }
    assert.equal(upstreamCalls.length, 0);
  }

  // Signed out, expired, tampered, no selection: nothing reaches Prospectus or the upstream.
  for (const [label, cookie] of [["no cookie", ""], ["expired", cookieFor("account-1", 900)], ["tampered", cookieFor().replace(/.{8}$/, (tail) => (tail === "AAAAAAAA" ? "BBBBBBBB" : "AAAAAAAA"))], ["no selection", cookieFor(null)]] as const) {
    const { options, prospectusCalls, upstreamCalls } = setup();
    const response = await handleCurationRoute(post("publication", statusBody, { cookie }), "publication", options);
    assert.equal(response.status, 401, label);
    assert.equal(prospectusCalls.length + upstreamCalls.length, 0, `${label}: nothing downstream`);
  }

  // Origin, content type, size.
  {
    const { options, prospectusCalls } = setup();
    assert.equal((await handleCurationRoute(post("publication", statusBody, { originHeader: "https://evil.example" }), "publication", options)).status, 403);
    assert.equal((await handleCurationRoute(post("publication", statusBody, { originHeader: null }), "publication", options)).status, 403, "a POST without Origin is refused");
    assert.equal((await handleCurationRoute(get(cookieFor(), "https://evil.example"), "context", options)).status, 403);
    assert.equal((await handleCurationRoute(post("publication", statusBody, { contentType: "text/plain" }), "publication", options)).status, 415);
    const big = JSON.stringify({ query: "x".repeat(CURATION_MAXIMUM_REQUEST_BYTES + 10) });
    assert.equal((await handleCurationRoute(post("priming", big), "priming", options)).status, 413);
    assert.equal(prospectusCalls.length, 0, "refused before any Prospectus call");
  }

  // Pins.
  {
    const { options, upstreamCalls } = setup();
    assert.equal((await handleCurationRoute(post("publication", statusBody, { headers: {} as typeof pinHeaders }), "publication", options)).status, 400, "missing pins");
    const partial = { ...pinHeaders, "x-papyrus-binding": "" };
    assert.equal((await handleCurationRoute(post("publication", statusBody, { headers: partial }), "publication", options)).status, 400);
    const otherAccount = await handleCurationRoute(post("publication", statusBody, { headers: { ...pinHeaders, "x-cyclotron-account": "account-2" } }), "publication", options);
    assert.equal(otherAccount.status, 409);
    assert.equal((await otherAccount.json()).code, "account_changed");
    assert.equal((await handleCurationRoute(post("publication", statusBody, { headers: { ...pinHeaders, "x-papyrus-publication": "pub-2" } }), "publication", options)).status, 409);
    assert.equal(upstreamCalls.length, 0, "wrong pins never reach the upstream");
  }

  // Fresh Prospectus re-authorization and capability.
  {
    const removed = setup({ removed: true });
    assert.equal((await handleCurationRoute(post("publication", statusBody), "publication", removed.options)).status, 403, "removed member");
    const refused = setup({ refuse: true });
    assert.equal((await handleCurationRoute(post("priming", primingQuery), "priming", refused.options)).status, 403, "Prospectus refusal");
    assert.equal(removed.upstreamCalls.length + refused.upstreamCalls.length, 0);

    const viewer = setup({ role: "viewer" });
    assert.equal((await handleCurationRoute(post("publication", statusBody), "publication", viewer.options)).status, 200, "a viewer reads");
    assert.equal((await handleCurationRoute(post("priming", primingQuery), "priming", viewer.options)).status, 200, "a viewer reads priming");
    const viewerImport = await handleCurationRoute(post("priming", primingMutation), "priming", viewer.options);
    assert.equal(viewerImport.status, 403, "priming imports need review");
    assert.equal((await viewerImport.json()).code, "capability_refused");
    assert.equal((await handleCurationRoute(post("publication", { operation: "review", payload: {} }), "publication", viewer.options)).status, 403);
    assert.equal(viewer.upstreamCalls.length, 2);

    const member = setup({ role: "member" });
    assert.equal((await handleCurationRoute(post("priming", primingMutation), "priming", member.options)).status, 200, "a member imports");
    assert.equal((await handleCurationRoute(post("publication", { operation: "steer", payload: {} }), "publication", member.options)).status, 403, "steering needs admin");
    const admin = setup({ role: "admin" });
    assert.equal((await handleCurationRoute(post("publication", { operation: "steer", payload: {} }), "publication", admin.options)).status, 200);

    assert.equal(primingCapability("query{a}"), "read");
    assert.equal(primingCapability("  MUTATION x{primingCommand}"), "review");
    assert.equal(primingCapability("query{primingCommand}"), "review", "fails closed on the command field");
    for (const malformed of [{ operation: "drop", payload: {} }, { operation: "status" }, { operation: "status", payload: {}, extra: 1 }, { operation: "status", payload: [] }]) {
      assert.equal((await handleCurationRoute(post("publication", malformed), "publication", member.options)).status, 400);
    }
    for (const malformed of [{}, { query: "" }, { query: "{a}", extra: 1 }, { query: "{a}", variables: [] }, "not json"]) {
      assert.equal((await handleCurationRoute(post("priming", malformed), "priming", member.options)).status, 400);
    }
  }

  // Forwarding: token from the cookie, pins, no redirects, timeout signal, and echoed scope returned.
  {
    const { options, upstreamCalls, prospectusCalls } = setup();
    const response = await handleCurationRoute(post("publication", statusBody), "publication", options);
    assert.equal(response.status, 200);
    const call = upstreamCalls[0];
    assert.equal(call.url, "https://lab.example.test/api/newsroom/curation/publication");
    const headers = call.init.headers as Record<string, string>;
    assert.equal(headers.authorization, `Bearer ${accessToken}`);
    assert.deepEqual(Object.fromEntries(Object.entries(headers).filter(([name]) => name.startsWith("x-"))), pinHeaders);
    assert.equal(call.init.redirect, "manual");
    assert.ok(call.init.signal, "a timeout signal is attached");
    assert.equal(call.init.body, JSON.stringify(statusBody));
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get("x-papyrus-binding"), "binding-1");
    assert.ok(prospectusCalls.some((request) => request.path === "/v1/accounts/account-1/authorize"));
    await assertNoLeak(response, "publication");

    // A different cookie token on the next call is the one forwarded (read fresh each call).
    const rotated = await handleCurationRoute(post("publication", statusBody, { cookie: cookieFor("account-1", 5_000, "rotated-token") }), "publication", options);
    assert.equal(rotated.status, 200);
    assert.equal((upstreamCalls[1].init.headers as Record<string, string>).authorization, "Bearer rotated-token");

    const contextCall = await handleCurationRoute(get(), "context", options);
    assert.equal(contextCall.status, 200);
    assert.equal(upstreamCalls[2].init.method, "GET");
    assert.equal(upstreamCalls[2].init.body, undefined);
    assert.deepEqual(await contextCall.clone().json(), { scope, mode: "remote", priming: { listId: "examples", classifiers: [{ id: "c", revision: 1 }], transformers: [] }, capabilities: ["read", "review"], bindingRef: null }, "the lab context passes through");
    assert.equal(contextCall.headers.get("x-papyrus-binding"), "binding-1");
    const viewerContext = setup({ role: "viewer" });
    assert.deepEqual((await (await handleCurationRoute(get(), "context", viewerContext.options)).json()).capabilities, ["read"], "capabilities are capped at the viewer role");
  }

  // Upstream failures: redirects, refusals, size, bad JSON, throws, timeouts.
  {
    const redirect = setup({}, () => new Response(null, { status: 302, headers: { location: "https://evil.example" } }));
    assert.equal((await handleCurationRoute(post("priming", primingQuery), "priming", redirect.options)).status, 502);
    const refusedUpstream = setup({}, () => Response.json({ error: "engine said: " + accessToken, code: "account_changed", detail: accessToken }, { status: 409 }));
    const refusedResponse = await handleCurationRoute(post("publication", statusBody), "publication", refusedUpstream.options);
    assert.deepEqual([refusedResponse.status, await refusedResponse.json()], [409, { error: UPSTREAM_REFUSAL_MESSAGES.account_changed, code: "account_changed" }], "only the mapped refusal is forwarded");
    const labRefusals: Array<[number, string]> = [[400, "pins_required"], [400, "invalid_request"], [401, "bearer_invalid"], [403, "access_refused"], [403, "outside_publication"], [409, "account_changed"], [409, "operation_unavailable"], [409, "firewall_overlap"], [409, "auto_prime_failed"], [413, "request_too_large"], [413, "import_too_large"], [413, "storage_limit"], [415, "json_required"], [503, "authority_unavailable"], [503, "priming_not_configured"], [503, "status_unavailable"], [503, "live_disabled"], [400, "no_hosted_transformer"]];
    for (const [status, code] of labRefusals) {
      const lab = setup({}, () => Response.json({ error: "lab words: " + code, code }, { status }));
      const labResponse = await handleCurationRoute(post("priming", primingQuery), "priming", lab.options);
      assert.deepEqual([labResponse.status, await labResponse.json()], [status, { error: UPSTREAM_REFUSAL_MESSAGES[code], code }], `${status} ${code}`);
      assert.doesNotMatch(UPSTREAM_REFUSAL_MESSAGES[code], /engine|classifier|binding|cyclotron|prime|priming|account_|pin/i, `${code}: editor-facing wording`);
    }
    const unknownCode = setup({}, () => Response.json({ error: "internal detail", code: "mystery" }, { status: 503 }));
    const unknownResponse = await handleCurationRoute(post("priming", primingQuery), "priming", unknownCode.options);
    assert.deepEqual([unknownResponse.status, (await unknownResponse.json()).code], [503, "upstream_refused"], "unknown codes get the generic line");
    const server = setup({}, () => new Response("boom " + accessToken, { status: 500 }));
    const serverResponse = await handleCurationRoute(post("publication", statusBody), "publication", server.options);
    assert.equal(serverResponse.status, 502);
    await assertNoLeak(serverResponse, "upstream 500");
    const huge = setup({}, () => new Response("x".repeat(CURATION_MAXIMUM_RESPONSE_BYTES + 1), { status: 200 }));
    assert.equal((await handleCurationRoute(post("publication", statusBody), "publication", huge.options)).status, 502, "response cap");
    const invalid = setup({}, () => new Response("not json", { status: 200, headers: pinHeaders }));
    assert.equal((await handleCurationRoute(post("priming", primingQuery), "priming", invalid.options)).status, 502);

    logged.length = 0;
    const thrown = setup({}, () => { throw new Error(`socket closed ${accessToken}`); });
    const thrownResponse = await handleCurationRoute(post("priming", primingQuery), "priming", thrown.options);
    assert.equal(thrownResponse.status, 503);
    assert.equal((await thrownResponse.clone().json()).code, "curation_unavailable");
    await assertNoLeak(thrownResponse, "thrown");
    assert.ok(!logged.join("\n").includes(accessToken), "the token is never logged");

    const slow = setup({}, (call) => new Promise<Response>((_, reject) => (call.init.signal as AbortSignal).addEventListener("abort", () => reject(new Error("aborted")))));
    const slowResponse = await handleCurationRoute(post("priming", primingQuery), "priming", { ...slow.options, timeoutMilliseconds: 20 });
    assert.equal(slowResponse.status, 503, "a timeout is a generic 503");
  }

  // Echoed scope must match.
  {
    const wrongHeaders = setup({}, () => Response.json({ data: {} }, { headers: { ...pinHeaders, "x-papyrus-binding": "binding-2" } }));
    assert.equal((await handleCurationRoute(post("priming", primingQuery), "priming", wrongHeaders.options)).status, 502, "echoed binding differs");
    const noHeaders = setup({}, () => Response.json({ data: {} }));
    assert.equal((await handleCurationRoute(post("priming", primingQuery), "priming", noHeaders.options)).status, 502, "no echoed pins");
    const wrongEnvelope = setup({}, () => Response.json({ contractVersion: "cyclotron-publication/v1", ...scope, accountId: "account-2" }, { headers: pinHeaders }));
    assert.equal((await handleCurationRoute(post("publication", statusBody), "publication", wrongEnvelope.options)).status, 502, "envelope account differs");
    const wrongContract = setup({}, () => Response.json({ contractVersion: "other", ...scope }, { headers: pinHeaders }));
    assert.equal((await handleCurationRoute(post("publication", statusBody), "publication", wrongContract.options)).status, 502);
    const staleHeaders = setup({}, () => Response.json(defaultContext(), { headers: { ...pinHeaders, "x-papyrus-binding": "binding-2" } }));
    assert.equal((await handleCurationRoute(get(), "context", staleHeaders.options)).status, 502, "context echo differs from its body");
    const bareContext = setup({}, () => Response.json(defaultContext()));
    assert.equal((await handleCurationRoute(get(), "context", bareContext.options)).status, 502, "context without echoed pins");
    const badPriming = setup({}, () => Response.json({ ...defaultContext(), priming: { listId: "", classifiers: [] } }, { headers: pinHeaders }));
    assert.equal((await (await handleCurationRoute(get(), "context", badPriming.options)).json()).priming, null, "malformed priming is dropped");
    for (const body of [{ ...defaultContext(), scope: { ...scope, accountId: "account-2" } }, { ...defaultContext(), scope: { ...scope, publicationId: "pub-2" } }, { ...defaultContext(), mode: "other" }, {}]) {
      const wrongContext = setup({}, () => Response.json(body, { headers: pinHeaders }));
      assert.equal((await handleCurationRoute(get(), "context", wrongContext.options)).status, 502, "context scope mismatch");
    }
  }

  // Authority lost while the upstream was working: the answer is dropped.
  {
    const lost = setup({}, undefined);
    lost.options.fetcher = (async () => { lost.world.removed = true; return defaultUpstream({ url: "/publication", init: {} }); }) as unknown as typeof fetch;
    const response = await handleCurationRoute(post("publication", statusBody), "publication", lost.options);
    assert.equal(response.status, 409);
    assert.equal((await response.json()).code, "account_changed");
    const downgraded = setup({}, undefined);
    downgraded.options.fetcher = (async () => { downgraded.world.role = "viewer"; return defaultUpstream({ url: "/publication", init: {} }); }) as unknown as typeof fetch;
    assert.equal((await handleCurationRoute(post("publication", { operation: "decide", payload: {} }), "publication", downgraded.options)).status, 409, "role change during the wait");
  }

  // Prospectus down is a generic 503.
  {
    const { options, upstreamCalls } = setup();
    options.resolveRuntime = async () => ({ ...(await worldRuntime({ role: "member", removed: false, refuse: false })).runtime, accounts: new ProspectusSiteAccounts(async () => { throw new Error("network"); }) });
    assert.equal((await handleCurationRoute(post("publication", statusBody), "publication", options)).status, 503);
    assert.equal(upstreamCalls.length, 0);
    options.resolveRuntime = async () => null;
    assert.equal((await handleCurationRoute(post("publication", statusBody), "publication", options)).status, 503, "sign-in unavailable");
  }

  console.error = originalError;
  await bootstrapTests();
  console.log("curation routes: ok");
}

function defaultContext() {
  return { scope, mode: "remote", priming: null, capabilities: ["read"], bindingRef: null };
}

async function bootstrapTests() {
  const session = (body: unknown, status = 200) => Response.json(body, { status });
  const signedIn = { signedIn: true, publishingAccounts: [], selectedAccountId: "account-1", cyclotronLabAccess: false };
  const make = (sessionResponse: Response | Error, contextResponse?: Response | Error) => {
    const paths: string[] = [];
    const fetcher = (async (path: string) => {
      paths.push(path);
      const answer = path.includes("/session") ? sessionResponse : contextResponse;
      if (!answer) throw new Error("unexpected context read");
      if (answer instanceof Error) throw answer;
      return answer.clone();
    }) as unknown as (input: string, init?: RequestInit) => Promise<Response>;
    return { fetcher, paths };
  };
  const good = Response.json(defaultContext());

  const ok = make(session(signedIn), good);
  assert.deepEqual((await loadCurationBootstrap("/newsroom", ok.fetcher))?.scope, scope);
  assert.deepEqual(ok.paths, ["/api/auth/prospectus/session", "/api/newsroom/curation/context"]);

  for (const [label, sessionResponse] of [
    ["no Prospectus", session({ error: "x" }, 503)],
    ["signed out", session({ signedIn: false })],
    ["no selection", session({ ...signedIn, selectedAccountId: null })],
    ["offline", new Error("offline")],
  ] as const) {
    const attempt = make(sessionResponse);
    assert.equal(await loadCurationBootstrap("/newsroom", attempt.fetcher), null, label);
    assert.deepEqual(attempt.paths, ["/api/auth/prospectus/session"], `${label}: no context read`);
  }
  for (const [label, contextResponse] of [
    ["refused", Response.json({ error: "x" }, { status: 403 })],
    ["invalid", Response.json({ scope: { accountId: "", publicationId: "p", bindingRevision: "b" }, mode: "remote", capabilities: [] })],
    ["other account", Response.json({ ...defaultContext(), scope: { ...scope, accountId: "account-9" } })],
    ["network", new Error("offline")],
  ] as const) {
    assert.equal(await loadCurationBootstrap("/newsroom", make(session(signedIn), contextResponse).fetcher), null, label);
  }
}

main().catch((error) => {
  process.stderr.write(`${error?.stack ?? error}\n`);
  process.exit(1);
});
