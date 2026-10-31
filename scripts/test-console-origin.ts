import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { expandNewsroomRedirectUrls } from "../amplify/auth/redirect-urls";
import { planCliRemoteLogin } from "../amplify/cli-login/remote-login";
import { handleCliLoginDiscovery, type AmplifyOutputsForCliLogin } from "../lib/cli-login-discovery";

const siteOrigin = "https://site.example.test";
const consoleOrigin = "https://newsroom.site.example.test";
const invokerRoleArn = "arn:aws:iam::111111111111:role/example-compute-role";

function outputsFor(origin: string): AmplifyOutputsForCliLogin {
  return {
    auth: {
      user_pool_id: "us-east-1_Synthetic", user_pool_client_id: "synthetic-web-client", aws_region: "us-east-1",
      oauth: { domain: "site.auth.us-east-1.amazoncognito.com", redirect_sign_in_uri: ["http://localhost:3001/", `${origin}/cli/callback`] },
    },
    data: { url: "https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql" },
    custom: { cliLogin: { brokerEndpoint: "https://broker.example.test/", remoteCallbackUri: `${origin}/cli/callback` } },
  };
}

async function discover(environment: Record<string, string | undefined>, host: string) {
  const response = handleCliLoginDiscovery(new NextRequest(`https://${host}/.well-known/papyrus-cli.json`), {
    readOutputs: () => outputsFor(environment.PAPYRUS_CONSOLE_ORIGIN ?? siteOrigin),
    environment,
  });
  return { status: response.status, body: await response.json() as Record<string, unknown> };
}

const cases: Record<string, () => Promise<void> | void> = {
  callback_urls_include_both_origins() {
    const expanded = expandNewsroomRedirectUrls(["http://localhost:3001/", `${siteOrigin}/`, `${consoleOrigin}/`]);
    for (const origin of [siteOrigin, consoleOrigin]) {
      assert.ok(expanded.includes(`${origin}/newsroom`), `${origin}/newsroom is a callback`);
      assert.ok(expanded.includes(`${origin}/`), `${origin}/ is a callback`);
    }
  },
  broker_origin_is_the_console_origin() {
    const plan = planCliRemoteLogin(true, { PAPYRUS_SITE_ORIGIN: siteOrigin, PAPYRUS_CONSOLE_ORIGIN: consoleOrigin, PAPYRUS_CLI_INVOKER_ROLE_ARN: invokerRoleArn });
    assert.deepEqual(plan, { origin: consoleOrigin, approvalUrl: `${consoleOrigin}/cli/approve`, callbackUri: `${consoleOrigin}/cli/callback`, invokerRoleArn });
  },
  broker_origin_is_the_site_origin_without_a_console_origin() {
    const plan = planCliRemoteLogin(true, { PAPYRUS_SITE_ORIGIN: siteOrigin, PAPYRUS_CLI_INVOKER_ROLE_ARN: invokerRoleArn });
    assert.deepEqual(plan, { origin: siteOrigin, approvalUrl: `${siteOrigin}/cli/approve`, callbackUri: `${siteOrigin}/cli/callback`, invokerRoleArn });
  },
  async discovery_names_the_console_origin_on_both_hosts() {
    const environment = { PAPYRUS_SITE_ORIGIN: siteOrigin, PAPYRUS_CONSOLE_ORIGIN: consoleOrigin };
    const onConsole = await discover(environment, "newsroom.site.example.test");
    const onSite = await discover(environment, "site.example.test");
    assert.equal(onConsole.status, 200);
    assert.deepEqual(onSite.body, onConsole.body, "the public host returns the same document");
    assert.equal(onConsole.body.publication, consoleOrigin);
    assert.equal(onConsole.body.remote_callback_uri, `${consoleOrigin}/cli/callback`);
    assert.equal(onConsole.body.broker_endpoint, "https://broker.example.test/");
  },
  async discovery_is_unchanged_without_a_console_origin() {
    const result = await discover({ PAPYRUS_SITE_ORIGIN: siteOrigin }, "site.example.test");
    assert.equal(result.body.publication, siteOrigin);
    assert.equal(result.body.remote_callback_uri, `${siteOrigin}/cli/callback`);
  },
};

async function main(): Promise<void> {
  const requested = process.argv[2];
  const names = requested ? [requested] : Object.keys(cases);
  for (const name of names) {
    const run = cases[name];
    if (!run) throw new Error(`unknown case ${name}`);
    await run();
  }
  console.log(`console-origin ok (${names.length})`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
