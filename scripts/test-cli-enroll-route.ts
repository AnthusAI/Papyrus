import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { Code } from "aws-cdk-lib/aws-lambda";
import { addCliRemoteLogin, planCliEnrollment, planCliRemoteLogin } from "../amplify/cli-login/remote-login";
import { createHash, randomUUID } from "node:crypto";
import { handleCliChallenge, handleCliEnroll, type CliChallengeOptions, type CliEnrollOptions } from "../lib/prospectus-enroll";
import { ProspectusAccountsError, ProspectusSiteAccounts, type ProspectusTransport } from "../lib/prospectus-site-identity";
import { takeChallengeToken, throttleLimitsFromEnvironment, type ThrottleState, type ThrottleStore } from "../lib/cli-challenge-throttle";
import { isStaticOrApiPath } from "../lib/staging-gated-path";

const site = "https://shipped.example.test";
const invokerRoleArn = "arn:aws:iam::111111111111:role/example-compute-role";
const stageArn = "arn:aws:execute-api:us-east-1:111111111111:abc123/api";
const client = { hostedUiOrigin: "https://auth.example.test", userPoolId: "us-east-1_Synthetic", clientId: "federation-client", redirectUri: `${site}/cli/callback` };

/** A stand-in for Prospectus's resolve route: one person per challenge, the same tokens again give the same person. */
function fakeProspectus(): ProspectusTransport {
  const firstTokens = new Map<string, string>();
  return async ({ path, body, humanAccessToken }) => {
    assert.equal(path, "/v1/identities/google/resolve");
    const { challengeToken, loginState } = body as { challengeToken: string; loginState: string };
    if (challengeToken === "forged") throw new ProspectusAccountsError(401, "challenge_invalid", "detail that must not leak");
    if (loginState === "wrong") throw new ProspectusAccountsError(401, "login_state", "detail that must not leak");
    if (challengeToken === "old") throw new ProspectusAccountsError(401, "reenrollment_required", "detail that must not leak");
    if (challengeToken === "down") throw new ProspectusAccountsError(500, "internal", "stack trace that must not leak");
    const seen = firstTokens.get(challengeToken);
    if (seen && seen !== humanAccessToken) throw new ProspectusAccountsError(409, "challenge_replay", "detail that must not leak");
    firstTokens.set(challengeToken, humanAccessToken!);
    return { person: { id: "person-1", createdAt: "2026-10-31T00:00:00Z" } };
  };
}

function options(overrides: Partial<CliEnrollOptions> = {}, enabled = true): CliEnrollOptions {
  const accounts = new ProspectusSiteAccounts(fakeProspectus());
  return {
    readOutputs: () => ({ custom: { cliLogin: enabled ? { enrollment: true } : {} } }),
    resolveRuntime: async () => ({ accounts, cognitoClient: client, sealingSecret: "unused" }),
    verifyTokens: async (_client, accessToken) => {
      if (accessToken.startsWith("main")) throw new Error("wrong client");
    },
    environment: { PAPYRUS_SITE_ORIGIN: site },
    ...overrides,
  };
}

function enrollRequest(access = "access.token.one", body: Record<string, unknown> = {}, method = "POST") {
  return new NextRequest(`${site}/cli/enroll`, {
    method,
    headers: { authorization: `Bearer ${access}`, "content-type": "application/json" },
    ...(method === "POST" ? { body: JSON.stringify({ challengeToken: "v1.k.p.m", idToken: "id.token.one", loginState: "T1", ...body }) } : {}),
  });
}

async function answer(request: NextRequest, given: CliEnrollOptions = options()) {
  const response = await handleCliEnroll(request, given);
  return { status: response.status, body: await response.json() as Record<string, unknown> };
}

function synthesize(withEnrollment: boolean): Template {
  const stack = new Stack(new App(), "CliEnrollmentTest", { env: { account: "111111111111", region: "us-east-1" } });
  addCliRemoteLogin(stack, {
    plan: planCliRemoteLogin(true, { PAPYRUS_SITE_ORIGIN: site, PAPYRUS_CLI_INVOKER_ROLE_ARN: invokerRoleArn })!,
    clientId: "synthetic-web-client",
    graphqlEndpoint: "https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql",
    authorizeEndpoint: "https://shipped.auth.us-east-1.amazoncognito.com/oauth2/authorize",
    product: "Papyrus (shipped.example.test)",
    brokerCode: Code.fromInline("def lambda_handler(event, context): pass"),
    pagesCode: Code.fromInline("def handler(event, context): pass"),
    ...planCliEnrollment(withEnrollment),
  });
  return Template.fromStack(stack);
}

const behaviours: Record<string, () => Promise<unknown>> = {
  async the_route_resolves_a_person_for_the_right_tokens_and_state() {
    const result = await answer(enrollRequest());
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, { person: { id: "person-1" } });
    return result;
  },
  async a_replay_with_other_tokens_is_refused_and_the_same_tokens_return_the_same_person() {
    const given = options();
    const first = await answer(enrollRequest("access.token.one"), given);
    const same = await answer(enrollRequest("access.token.one"), given);
    const other = await answer(enrollRequest("access.token.two"), given);
    assert.deepEqual(same.body, first.body);
    assert.equal(other.status, 409);
    assert.equal(other.body.error, "challenge_replay");
    return { first, same, other };
  },
  async a_login_on_the_main_web_client_cannot_enroll() {
    const result = await answer(enrollRequest("main.web.client"));
    assert.equal(result.status, 403);
    assert.equal(result.body.error, "login_not_enrollable");
    return result;
  },
  async error_responses_name_no_service_detail_beyond_the_code() {
    const cases: [Record<string, unknown>, number, string][] = [
      [{ challengeToken: "forged" }, 401, "challenge_invalid"],
      [{ loginState: "wrong" }, 401, "login_state"],
      [{ challengeToken: "old" }, 401, "reenrollment_required"],
      [{ challengeToken: "down" }, 503, "unavailable"],
      [{ loginState: "has.a.dot" }, 400, "invalid_request"],
    ];
    for (const [body, status, code] of cases) {
      const result = await answer(enrollRequest("access.token.one", body));
      assert.equal(result.status, status);
      assert.equal(result.body.error, code);
      assert.doesNotMatch(JSON.stringify(result.body), /must not leak|stack trace|detail/);
    }
    const noBearer = await answer(new NextRequest(`${site}/cli/enroll`, { method: "POST", body: "{}" }));
    assert.equal(noBearer.status, 400);
    return { cases: cases.length };
  },
  async a_site_that_did_not_switch_enrollment_on_answers_404_and_calls_nothing() {
    let asked = false;
    const result = await answer(enrollRequest(), options({ resolveRuntime: async () => { asked = true; return null; } }, false));
    assert.equal(result.status, 404);
    assert.equal(asked, false);
    const unregistered = await answer(enrollRequest(), options({ resolveRuntime: async () => null }));
    assert.equal(unregistered.status, 503);
    assert.equal((await answer(enrollRequest("access.token.one", {}, "GET"), options())).status, 405);
    assert.equal(isStaticOrApiPath("/cli/enroll"), true);
    return result;
  },
  async a_login_challenge_is_bound_to_a_digest_and_validated_before_it_is_answered() {
    const seen: unknown[] = [];
    const good = { challengeId: randomUUID(), nonce: "n".repeat(43), expiresAt: 1_000_000_100, challengeToken: `v1.k1.${"p".repeat(40)}.${"m".repeat(43)}` };
    let central: Record<string, unknown> = good;
    const accounts = new ProspectusSiteAccounts(async ({ path, method, body }) => {
      seen.push({ path, method, body });
      return central;
    });
    const given = (overrides: Partial<CliChallengeOptions> = {}): CliChallengeOptions => options({
      resolveRuntime: async () => ({ accounts, cognitoClient: client, sealingSecret: "unused" }),
      ...overrides,
    }) as CliChallengeOptions & { takeToken: () => Promise<boolean> };
    const ask = async (query: string, extra: Partial<CliChallengeOptions> = {}, method = "GET") => {
      const response = await handleCliChallenge(new NextRequest(`${site}/cli/challenge${query}`, { method }), { ...given(), takeToken: async () => true, nowInSeconds: () => 1_000_000_000, ...extra });
      return { status: response.status, body: await response.json() as Record<string, unknown> };
    };
    const digest = createHash("sha256").update("transaction-1").digest("hex");
    const fromDigest = await ask(`?loginStateDigest=${digest}`);
    assert.equal(fromDigest.status, 200);
    assert.deepEqual(fromDigest.body, good);
    const fromState = await ask("?state=abc_DEF-123");
    assert.equal(fromState.status, 200);
    assert.deepEqual(seen, [
      { path: "/v1/identities/google/challenge", method: "POST", body: { loginStateDigest: digest } },
      { path: "/v1/identities/google/challenge", method: "POST", body: { loginStateDigest: createHash("sha256").update("abc_DEF-123").digest("hex") } },
    ]);
    for (const query of ["", "?state=has.dot", `?loginStateDigest=${digest.toUpperCase()}`, `?loginStateDigest=${digest.slice(1)}`, `?state=x&loginStateDigest=${digest}`]) {
      assert.equal((await ask(query)).status, 400, query);
    }
    assert.equal((await ask(`?loginStateDigest=${digest}`, {}, "POST")).status, 405);
    for (const bad of [{ challengeId: "not-a-uuid" }, { nonce: "short" }, { expiresAt: 999_999_999 }, { expiresAt: 1_000_000_301 }, { challengeToken: "forged" }, { challengeToken: undefined }]) {
      central = { ...good, ...bad };
      const refused = await ask(`?loginStateDigest=${digest}`);
      assert.equal(refused.status, 503, JSON.stringify(bad));
      assert.equal(refused.body.error, "unavailable");
    }
    central = good;
    assert.equal((await handleCliChallenge(new NextRequest(`${site}/cli/challenge?state=x`), options({}, false))).status, 404);
    const down = await handleCliChallenge(new NextRequest(`${site}/cli/challenge?state=x`), { ...options({ resolveRuntime: async () => { throw new Error("boom"); } }), takeToken: async () => true });
    assert.equal(down.status, 503);
    assert.doesNotMatch(JSON.stringify(await down.json()), /boom/);
    assert.equal(isStaticOrApiPath("/cli/challenge"), true);
    return fromDigest;
  },
  async the_challenge_route_is_throttled_per_site_and_fails_closed() {
    const answered: unknown[] = [];
    const accounts = new ProspectusSiteAccounts(async () => { answered.push(1); return {}; });
    const refusedBy = async (takeToken: () => Promise<boolean>) => {
      const response = await handleCliChallenge(new NextRequest(`${site}/cli/challenge?state=abc`), {
        ...options({ resolveRuntime: async () => ({ accounts, cognitoClient: client, sealingSecret: "unused" }) }), takeToken,
      });
      return { status: response.status, retryAfter: response.headers.get("retry-after"), body: await response.json() as Record<string, unknown> };
    };
    const empty = await refusedBy(async () => false);
    assert.equal(empty.status, 429);
    assert.equal(empty.body.error, "rate_limited");
    assert.equal(empty.retryAfter, "1");
    assert.equal(answered.length, 0, "a refused request never reaches Prospectus");
    assert.equal((await refusedBy(async () => { throw new Error("table down"); })).status, 503);

    let stored: ThrottleState | null = null;
    const store: ThrottleStore = {
      read: async () => stored,
      writeIfUnchanged: async (previous, next) => {
        if (JSON.stringify(previous) !== JSON.stringify(stored)) return false;
        stored = next;
        return true;
      },
    };
    const limits = throttleLimitsFromEnvironment({});
    assert.deepEqual(limits, { ratePerSecond: 1, burst: 2 });
    assert.deepEqual(throttleLimitsFromEnvironment({ PAPYRUS_CLI_CHALLENGE_RATE_PER_SECOND: "5", PAPYRUS_CLI_CHALLENGE_BURST: "10" }), { ratePerSecond: 5, burst: 10 });
    assert.deepEqual(throttleLimitsFromEnvironment({ PAPYRUS_CLI_CHALLENGE_RATE_PER_SECOND: "-1", PAPYRUS_CLI_CHALLENGE_BURST: "x" }), { ratePerSecond: 1, burst: 2 });
    const start = 10_000_000;
    const outcomes = [
      await takeChallengeToken(store, limits, start),
      await takeChallengeToken(store, limits, start),
      await takeChallengeToken(store, limits, start),
      await takeChallengeToken(store, limits, start + 500),
      await takeChallengeToken(store, limits, start + 1000),
      await takeChallengeToken(store, limits, start + 60_000),
    ];
    assert.deepEqual(outcomes, [true, true, false, false, true, true]);
    let raced = 0;
    const contended: ThrottleStore = { read: async () => ({ millitokens: 2000, updatedAtMilliseconds: 1 }), writeIfUnchanged: async () => { raced += 1; return false; } };
    assert.equal(await takeChallengeToken(contended, limits, 2), false);
    assert.ok(raced >= 2, "a lost race is retried, then refused");
    return { outcomes };
  },
  async enrollment_is_off_unless_switched_on_and_off_synthesizes_unchanged() {
    assert.equal(planCliEnrollment(false), undefined);
    const stack = new Stack(new App(), "Unchanged", { env: { account: "111111111111", region: "us-east-1" } });
    addCliRemoteLogin(stack, {
      plan: planCliRemoteLogin(true, { PAPYRUS_SITE_ORIGIN: site, PAPYRUS_CLI_INVOKER_ROLE_ARN: invokerRoleArn })!,
      clientId: "synthetic-web-client",
      graphqlEndpoint: "https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql",
      authorizeEndpoint: "https://shipped.auth.us-east-1.amazoncognito.com/oauth2/authorize",
      product: "Papyrus (shipped.example.test)",
      brokerCode: Code.fromInline("def lambda_handler(event, context): pass"),
      pagesCode: Code.fromInline("def handler(event, context): pass"),
    });
    const without = Template.fromStack(stack).toJSON();
    assert.deepEqual(without.Resources, synthesize(false).toJSON().Resources);
    assert.doesNotMatch(JSON.stringify(without), /SITE_CHALLENGE_ORIGIN|ChallengeThrottle|execute-api/);
    const on = synthesize(true);
    assert.match(JSON.stringify(on.toJSON()), /SITE_CHALLENGE_ORIGIN/);
    on.resourceCountIs("AWS::DynamoDB::Table", 2);
    on.hasResourceProperties("AWS::DynamoDB::Table", {
      TimeToLiveSpecification: { AttributeName: "expiresAt", Enabled: true },
      BillingMode: "PAY_PER_REQUEST",
    });
    assert.doesNotMatch(JSON.stringify(on.toJSON()), /execute-api:Invoke/, "the pages function holds no Prospectus access");
    return { ok: true };
  },
};

async function main() {
  const requested = process.argv[2];
  if (requested) {
    if (!behaviours[requested]) throw new Error(`unknown behaviour ${requested}`);
    console.log(JSON.stringify(await behaviours[requested]()));
    return;
  }
  for (const [name, run] of Object.entries(behaviours)) {
    await run();
    console.log(`ok  ${name}`);
  }
  console.log("cli-enroll-route ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
