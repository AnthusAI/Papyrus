import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { Code } from "aws-cdk-lib/aws-lambda";
import { addCliRemoteLogin, planCliEnrollment, planCliRemoteLogin } from "../amplify/cli-login/remote-login";
import { createHash } from "node:crypto";
import { handleCliChallenge, handleCliEnroll, type CliEnrollOptions } from "../lib/prospectus-enroll";
import { ProspectusAccountsError, ProspectusSiteAccounts, type ProspectusTransport } from "../lib/prospectus-site-identity";
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
  const enrollment = planCliEnrollment(withEnrollment, { PAPYRUS_PROSPECTUS_ACCOUNTS_API_STAGE_ARN: stageArn });
  addCliRemoteLogin(stack, {
    plan: planCliRemoteLogin(true, { PAPYRUS_SITE_ORIGIN: site, PAPYRUS_CLI_INVOKER_ROLE_ARN: invokerRoleArn })!,
    clientId: "synthetic-web-client",
    graphqlEndpoint: "https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql",
    authorizeEndpoint: "https://shipped.auth.us-east-1.amazoncognito.com/oauth2/authorize",
    product: "Papyrus (shipped.example.test)",
    brokerCode: Code.fromInline("def lambda_handler(event, context): pass"),
    pagesCode: Code.fromInline("def handler(event, context): pass"),
    ...enrollment,
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
  async a_local_login_challenge_is_bound_to_the_digest_of_its_own_state() {
    const seen: unknown[] = [];
    const accounts = new ProspectusSiteAccounts(async ({ path, method, body }) => {
      seen.push({ path, method, body });
      return { challengeId: "id", nonce: "n".repeat(43), expiresAt: 1, challengeToken: "v1.k.p.m" };
    });
    const given = options({ resolveRuntime: async () => ({ accounts, cognitoClient: client, sealingSecret: "unused" }) });
    const ask = async (query: string, method = "GET") => {
      const response = await handleCliChallenge(new NextRequest(`${site}/cli/challenge${query}`, { method }), given);
      return { status: response.status, body: await response.json() as Record<string, unknown> };
    };
    const good = await ask("?state=abc_DEF-123");
    assert.equal(good.status, 200);
    assert.deepEqual(good.body, { nonce: "n".repeat(43), challengeToken: "v1.k.p.m" });
    assert.deepEqual(seen, [{ path: "/v1/identities/google/challenge", method: "POST", body: { loginStateDigest: createHash("sha256").update("abc_DEF-123").digest("hex") } }]);
    assert.equal((await ask("")).status, 400);
    assert.equal((await ask("?state=has.dot")).status, 400);
    assert.equal((await ask("?state=x", "POST")).status, 405);
    const off = await handleCliChallenge(new NextRequest(`${site}/cli/challenge?state=x`), options({}, false));
    assert.equal(off.status, 404);
    const down = await handleCliChallenge(new NextRequest(`${site}/cli/challenge?state=x`), options({ resolveRuntime: async () => { throw new Error("boom"); } }));
    assert.equal(down.status, 503);
    assert.doesNotMatch(JSON.stringify(await down.json()), /boom/);
    assert.equal(isStaticOrApiPath("/cli/challenge"), true);
    return good;
  },
  async enrollment_is_off_unless_switched_on_and_off_synthesizes_unchanged() {
    assert.equal(planCliEnrollment(false, { PAPYRUS_PROSPECTUS_ACCOUNTS_API_STAGE_ARN: stageArn }), undefined);
    assert.throws(() => planCliEnrollment(true, {}), /PAPYRUS_PROSPECTUS_ACCOUNTS_API_STAGE_ARN/);
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
    const planOff = synthesize(false).toJSON();
    assert.deepEqual(without.Resources, planOff.Resources);
    assert.doesNotMatch(JSON.stringify(without), /PROSPECTUS_ACCOUNTS_API|execute-api/);
    const on = synthesize(true);
    const json = JSON.stringify(on.toJSON());
    assert.match(json, /PROSPECTUS_ACCOUNTS_API/);
    on.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: { Statement: [{ Action: "execute-api:Invoke", Effect: "Allow", Resource: `${stageArn}/POST/v1/identities/google/challenge` }] },
    });
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
