import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { App, Stack } from "aws-cdk-lib";
import { Annotations, Match, Template } from "aws-cdk-lib/assertions";
import { Code } from "aws-cdk-lib/aws-lambda";
import { defineBackend } from "@aws-amplify/backend";
import { defineSiteAuth } from "../amplify/auth/resource";
import { manageUserRole } from "../amplify/functions/manage-user-role/resource";
import { CLI_LOGIN_VERSION, bundleCliLoginBroker, bundleCliLoginPages, cliLoginRequirement } from "../amplify/cli-login/bundle";
import { addCliRemoteLogin, planCliRemoteLogin } from "../amplify/cli-login/remote-login";
import { resolveSiteBackendFeatureFlags } from "../amplify/site-backend-names";
import { handleCliLoginDiscovery, type AmplifyOutputsForCliLogin } from "../lib/cli-login-discovery";
import { handleCliLoginPage, type ForwardedRequest, type ForwardedResponse } from "../lib/cli-login-pages";
import { isStaticOrApiPath } from "../lib/staging-gated-path";

const repo = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const site = "https://shipped.example.test";
const invokerRoleArn = "arn:aws:iam::111111111111:role/example-compute-role";
const pagesArn = "arn:aws:lambda:us-east-1:111111111111:function:example-pages";

// ---- discovery ------------------------------------------------------------------------------------------------

const outputs = (overrides: Partial<AmplifyOutputsForCliLogin> = {}, redirects = [`${site}/`, "http://localhost:3001/", `${site}/cli/callback`]): AmplifyOutputsForCliLogin => ({
  auth: {
    user_pool_id: "us-east-1_Synthetic", user_pool_client_id: "synthetic-web-client", aws_region: "us-east-1",
    oauth: { domain: "shipped.auth.us-east-1.amazoncognito.com", redirect_sign_in_uri: redirects },
  },
  data: { url: "https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql" },
  custom: { cliLogin: { brokerEndpoint: "https://broker.lambda-url.us-east-1.on.aws/", remoteCallbackUri: `${site}/cli/callback`, pagesFunctionArn: pagesArn } },
  ...overrides,
});

async function discover(document: AmplifyOutputsForCliLogin) {
  const response = handleCliLoginDiscovery(new NextRequest("http://internal.invalid/.well-known/papyrus-cli.json"), { readOutputs: () => document, environment: { PAPYRUS_SITE_ORIGIN: site } });
  return { status: response.status, body: await response.json() as Record<string, unknown> };
}

// ---- the /cli/* forwarder ---------------------------------------------------------------------------------------

type Call = { arn: string; request: ForwardedRequest };

async function forward(request: NextRequest, answer: ForwardedResponse | Error | "malformed", withPages = true) {
  const calls: Call[] = [];
  const response = await handleCliLoginPage(request, {
    readOutputs: () => (withPages ? { custom: { cliLogin: { pagesFunctionArn: pagesArn } } } : { custom: { cliLogin: null } }),
    invoke: async (arn, forwarded) => {
      calls.push({ arn, request: forwarded });
      if (answer instanceof Error) throw answer;
      return (answer === "malformed" ? { nope: true } : answer) as ForwardedResponse;
    },
  });
  return { response, calls };
}

const approved: ForwardedResponse = {
  status: 303,
  headers: [["Location", "https://auth.example.test/oauth2/authorize?state=x"], ["Set-Cookie", "__Secure-cli_login_nonce=n1; Path=/cli/callback"], ["Set-Cookie", "__Secure-cli_login_csrf=; Path=/cli/approve; Max-Age=0"], ["Cache-Control", "no-store"]],
  body: "",
};

const behaviours: Record<string, () => Promise<unknown>> = {
  // -- forwarding -------------------------------------------------------------------------------------------------
  async forwards_the_approval_page() {
    const request = new NextRequest("https://internal.invalid/cli/approve?t=abcdefghijklmnopqrstuv", { headers: { cookie: "a=1; b=2", "user-agent": "phone" } });
    const { response, calls } = await forward(request, { status: 200, headers: [["Content-Type", "text/html; charset=utf-8"], ["Set-Cookie", "__Secure-cli_login_csrf=c1; Path=/cli/approve"]], body: "<p>page</p>" });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].arn, pagesArn);
    assert.equal(calls[0].request.method, "GET");
    assert.equal(calls[0].request.path, "/cli/approve");
    assert.deepEqual(calls[0].request.query, { t: "abcdefghijklmnopqrstuv" });
    assert.equal(calls[0].request.headers.cookie, "a=1; b=2");
    assert.equal(calls[0].request.body, "");
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "<p>page</p>");
    assert.equal(response.headers.get("content-type"), "text/html; charset=utf-8");
    assert.deepEqual(response.headers.getSetCookie(), ["__Secure-cli_login_csrf=c1; Path=/cli/approve"]);
    return { status: response.status };
  },
  async forwards_the_approval_form_and_every_cookie_the_page_sets() {
    const request = new NextRequest("https://internal.invalid/cli/approve", {
      method: "POST", headers: { cookie: "__Secure-cli_login_csrf=c1", "content-type": "application/x-www-form-urlencoded" }, body: "t=T&csrf=c1&action=approve&confirm=yes",
    });
    const { response, calls } = await forward(request, approved);
    assert.equal(calls[0].request.method, "POST");
    assert.equal(calls[0].request.body, "t=T&csrf=c1&action=approve&confirm=yes");
    assert.equal(calls[0].request.headers["content-type"], "application/x-www-form-urlencoded");
    assert.equal(response.status, 303);
    assert.equal(response.headers.get("location"), "https://auth.example.test/oauth2/authorize?state=x");
    assert.equal(response.headers.getSetCookie().length, 2, "both Set-Cookie headers survive");
    assert.equal(response.headers.get("cache-control"), "no-store");
    return { status: response.status, cookies: response.headers.getSetCookie().length };
  },
  async forwards_the_callback() {
    const request = new NextRequest("https://internal.invalid/cli/callback?state=T.N&code=abc", { headers: { cookie: "__Secure-cli_login_nonce=N" } });
    const { response, calls } = await forward(request, { status: 200, headers: [], body: "approved" });
    assert.equal(calls[0].request.path, "/cli/callback");
    assert.deepEqual(calls[0].request.query, { state: "T.N", code: "abc" });
    assert.equal(calls[0].request.headers.cookie, "__Secure-cli_login_nonce=N");
    assert.equal(response.status, 200);
    return { status: response.status };
  },
  async a_site_without_the_pages_function_answers_not_found_and_calls_nothing() {
    const { response, calls } = await forward(new NextRequest("https://internal.invalid/cli/approve?t=T"), approved, false);
    assert.equal(response.status, 404);
    assert.equal((await response.json() as { error: string }).error, "cli_login_not_configured");
    assert.equal(calls.length, 0);
    return { status: response.status, calls: calls.length };
  },
  async other_paths_are_not_forwarded() {
    const { response, calls } = await forward(new NextRequest("https://internal.invalid/cli/other"), approved);
    assert.equal(response.status, 404);
    assert.equal(calls.length, 0);
    return { status: response.status };
  },
  async an_oversized_form_is_refused_before_invoking() {
    const request = new NextRequest("https://internal.invalid/cli/approve", { method: "POST", body: "x".repeat(70 * 1024) });
    const { response, calls } = await forward(request, approved);
    assert.equal(response.status, 413);
    assert.equal(calls.length, 0);
    return { status: response.status };
  },
  async an_unavailable_pages_function_says_so_without_details() {
    const { response } = await forward(new NextRequest("https://internal.invalid/cli/approve?t=T"), new Error("AccessDenied arn:aws:lambda:secret"));
    assert.equal(response.status, 503);
    assert.doesNotMatch(await response.text(), /AccessDenied|arn:/);
    return { status: response.status };
  },
  async a_malformed_answer_is_a_bad_gateway() {
    const { response } = await forward(new NextRequest("https://internal.invalid/cli/approve?t=T"), "malformed");
    assert.equal(response.status, 502);
    return { status: response.status };
  },
  async the_pages_are_served_at_the_site_root() {
    for (const pathname of ["/cli/approve", "/cli/callback"]) assert.equal(isStaticOrApiPath(pathname), true, `${pathname} must not be rewritten under /newsroom`);
    assert.equal(isStaticOrApiPath("/cli"), false);
    return {};
  },

  // -- discovery --------------------------------------------------------------------------------------------------
  async discovery_publishes_the_broker_when_the_site_switched_it_on() {
    const result = await discover(outputs());
    assert.equal(result.status, 200);
    assert.equal(result.body.broker_endpoint, "https://broker.lambda-url.us-east-1.on.aws/");
    assert.equal(result.body.remote_callback_uri, `${site}/cli/callback`);
    assert.equal(result.body.callback_uri, "http://localhost:3001/", "the local callback is unchanged");
    return result;
  },
  async discovery_publishes_no_broker_when_the_site_did_not_switch_it_on() {
    const result = await discover(outputs({ custom: undefined }));
    assert.equal(result.status, 200);
    assert.deepEqual(Object.keys(result.body).sort(), ["callback_uri", "client_id", "graphql_endpoint", "issuer", "oauth_domain", "publication"]);
    return result;
  },
  async discovery_publishes_no_broker_when_its_callback_is_not_registered_on_the_client() {
    const result = await discover(outputs({}, [`${site}/`, "http://localhost:3001/"]));
    assert.equal("broker_endpoint" in result.body, false);
    assert.equal("remote_callback_uri" in result.body, false);
    return result;
  },
  async discovery_publishes_no_broker_for_a_callback_on_another_origin() {
    const result = await discover(outputs({ custom: { cliLogin: { brokerEndpoint: "https://broker.example.test/", remoteCallbackUri: "https://other.example.test/cli/callback" } } }, ["http://localhost:3001/", "https://other.example.test/cli/callback"]));
    assert.equal("broker_endpoint" in result.body, false);
    return result;
  },

  // -- the switch ------------------------------------------------------------------------------------------------
  async it_is_off_for_every_site_by_default() {
    const identity = { brandId: "papyrus", amplifyAppId: "app1", amplifyBranch: "main", productionAppId: "app1" };
    assert.equal(resolveSiteBackendFeatureFlags(undefined, {}, identity).cliRemoteLogin, false, "off even on the legacy production pipeline");
    assert.equal(resolveSiteBackendFeatureFlags({}, {}, { ...identity, productionAppId: "" }).cliRemoteLogin, false);
    assert.equal(resolveSiteBackendFeatureFlags(undefined, { PAPYRUS_ENABLE_CLI_REMOTE_LOGIN: "true" }, identity).cliRemoteLogin, true);
    assert.equal(resolveSiteBackendFeatureFlags({ cliRemoteLogin: true }, {}, identity).cliRemoteLogin, true);
    assert.equal(resolveSiteBackendFeatureFlags({ cliRemoteLogin: false }, { PAPYRUS_ENABLE_CLI_REMOTE_LOGIN: "true" }, identity).cliRemoteLogin, false);
    assert.equal(planCliRemoteLogin(false, { PAPYRUS_SITE_ORIGIN: site, PAPYRUS_CLI_INVOKER_ROLE_ARN: invokerRoleArn }), undefined, "no plan, so no broker, pages function, callback or output");
    return {};
  },
  async switching_it_on_needs_the_site_origin_and_the_compute_role() {
    const plan = planCliRemoteLogin(true, { PAPYRUS_SITE_ORIGIN: site, PAPYRUS_CLI_INVOKER_ROLE_ARN: invokerRoleArn });
    assert.deepEqual(plan, { origin: site, approvalUrl: `${site}/cli/approve`, callbackUri: `${site}/cli/callback`, invokerRoleArn });
    assert.throws(() => planCliRemoteLogin(true, { PAPYRUS_CLI_INVOKER_ROLE_ARN: invokerRoleArn }), /PAPYRUS_SITE_ORIGIN/);
    assert.throws(() => planCliRemoteLogin(true, { PAPYRUS_SITE_ORIGIN: "http://shipped.example.test", PAPYRUS_CLI_INVOKER_ROLE_ARN: invokerRoleArn }), /https origin/);
    assert.throws(() => planCliRemoteLogin(true, { PAPYRUS_SITE_ORIGIN: `${site}/newsroom`, PAPYRUS_CLI_INVOKER_ROLE_ARN: invokerRoleArn }), /https origin/);
    assert.throws(() => planCliRemoteLogin(true, { PAPYRUS_SITE_ORIGIN: site }), /PAPYRUS_CLI_INVOKER_ROLE_ARN/);
    assert.throws(() => planCliRemoteLogin(true, { PAPYRUS_SITE_ORIGIN: site, PAPYRUS_CLI_INVOKER_ROLE_ARN: "*" }), /PAPYRUS_CLI_INVOKER_ROLE_ARN/);
    return {};
  },
  async the_web_client_registers_the_remote_callback_only_when_switched_on() {
    const run = (mode: string) => {
      const child = spawnSync(process.execPath, [...process.execArgv, process.argv[1], "auth-child", mode], { encoding: "utf8", env: process.env });
      assert.equal(child.status, 0, child.stderr.slice(-2000));
      return JSON.parse(/CLIENT=(.*)/.exec(child.stdout)![1]) as { CallbackURLs: string[]; LogoutURLs: string[] };
    };
    const off = run("off");
    const on = run("on");
    assert.deepEqual(on.CallbackURLs.slice(0, off.CallbackURLs.length), off.CallbackURLs, "every existing callback is kept, in order");
    assert.deepEqual(on.CallbackURLs.slice(off.CallbackURLs.length), [`${site}/cli/callback`]);
    assert.equal(off.CallbackURLs.includes(`${site}/cli/callback`), false);
    assert.deepEqual(on.LogoutURLs, off.LogoutURLs, "the remote callback is never a logout URL");
    return { off, on };
  },

  // -- one cli-login release ---------------------------------------------------------------------------------------
  async the_cli_the_broker_and_the_pages_run_the_same_cli_login_release() {
    const pyproject = fs.readFileSync(path.join(repo, "pyproject.toml"), "utf8");
    const pins = [...pyproject.matchAll(/"cli-login(?:\[linux\])? ==([0-9.]+) ; sys_platform/g)].map((match) => match[1]);
    assert.deepEqual(pins, [CLI_LOGIN_VERSION, CLI_LOGIN_VERSION], "both pyproject markers pin the release the Lambda bundles install");
    const installs: string[][] = [];
    for (const bundle of [bundleCliLoginBroker, bundleCliLoginPages]) {
      const directory = fs.mkdtempSync(path.join(os.tmpdir(), "cli-login-bundle-"));
      try {
        bundle(directory, (_python, args) => installs.push(args));
      } finally {
        fs.rmSync(directory, { recursive: true, force: true });
      }
    }
    assert.equal(installs.length, 2);
    for (const args of installs) {
      assert.equal(args.at(-1), `cli-login==${CLI_LOGIN_VERSION}`);
      assert.ok(args.includes("--no-deps") && args.includes("--target"));
    }
    const withoutDirectory = (args: string[]) => args.filter((_, index) => args[index - 1] !== "--target");
    assert.deepEqual(withoutDirectory(installs[0]), withoutDirectory(installs[1]), "the same pip arguments apart from the directory");
    assert.equal(cliLoginRequirement(), `cli-login==${CLI_LOGIN_VERSION}`);
    return {};
  },
  async the_pages_function_never_imports_papyrus_content() {
    const handler = fs.readFileSync(path.join(repo, "amplify/functions/cli-login-pages/handler.py"), "utf8");
    assert.doesNotMatch(handler, /^\s*(from|import)\s+papyrus/m, "the pages bundle ships cli-login and this handler, not papyrus_content");
    return {};
  },

  // -- the resources ----------------------------------------------------------------------------------------------
  async the_broker_keeps_its_security_properties() {
    const { template } = synthesizeBroker();
    const [brokerId, broker] = Object.entries(template.findResources("AWS::Lambda::Function")).find(([, resource]) => resource.Properties.Handler === "cli_login.broker.handler.lambda_handler")!;
    const [pagesId, pages] = Object.entries(template.findResources("AWS::Lambda::Function")).find(([, resource]) => resource.Properties.Handler === "handler.handler")!;
    assert.equal(broker.Properties.ReservedConcurrentExecutions, 10, "reserved concurrency");
    assert.ok(broker.Properties.LoggingConfig.LogGroup, "its own log group");
    assert.equal(pages.Properties.ReservedConcurrentExecutions, undefined);

    const urls = Object.values(template.findResources("AWS::Lambda::Url"));
    assert.equal(urls.length, 1);
    assert.equal(urls[0].Properties.AuthType, "NONE");
    assert.equal(urls[0].Properties.TargetFunctionArn["Fn::GetAtt"][0], brokerId);

    const permissions = Object.values(template.findResources("AWS::Lambda::Permission")).map((resource) => resource.Properties);
    const onBroker = permissions.filter((permission) => permission.FunctionName.Ref === brokerId);
    const invokes = onBroker.filter((permission) => permission.Action === "lambda:InvokeFunction");
    assert.equal(invokes.length, 2, "the broker has exactly two InvokeFunction grants");
    const publicInvoke = invokes.find((permission) => permission.Principal === "*")!;
    assert.equal(publicInvoke.InvokedViaFunctionUrl, true, "the public grant covers only calls through the function URL");
    const privateInvoke = invokes.find((permission) => permission.Principal !== "*")!;
    assert.deepEqual(privateInvoke.Principal["Fn::GetAtt"][1], "Arn");
    assert.ok(JSON.stringify(privateInvoke.Principal).includes("PagesServiceRole"), "the private operations belong to the pages function's role");
    assert.ok(onBroker.some((permission) => permission.Action === "lambda:InvokeFunctionUrl" && permission.FunctionUrlAuthType === "NONE"));
    assert.equal(onBroker.length, 3);
    const onPages = permissions.filter((permission) => permission.FunctionName.Ref === pagesId);
    assert.deepEqual(onPages.map((permission) => [permission.Action, permission.Principal]), [["lambda:InvokeFunction", invokerRoleArn]], "only the site's compute role may invoke the pages");

    const tables = Object.values(template.findResources("AWS::DynamoDB::Table"));
    assert.equal(tables.length, 1);
    assert.equal(tables[0].Properties.TimeToLiveSpecification.AttributeName, "expires_at");
    const statements = Object.values(template.findResources("AWS::IAM::Role"))
      .flatMap((role) => (role.Properties.Policies ?? []).flatMap((policy: { PolicyDocument: { Statement: unknown[] } }) => policy.PolicyDocument.Statement)) as { Action: string[]; Resource: unknown }[];
    const dynamo = Object.values(template.findResources("AWS::IAM::Policy")).flatMap((policy) => policy.Properties.PolicyDocument.Statement).concat(statements).filter((statement: { Action: string | string[] }) => JSON.stringify(statement.Action).includes("dynamodb"));
    assert.equal(dynamo.length, 1);
    assert.deepEqual(dynamo[0].Action, ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]);
    assert.deepEqual(Object.keys(dynamo[0].Resource), ["Fn::GetAtt"], "the broker's own table only");

    const filters = Object.values(template.findResources("AWS::Logs::MetricFilter"));
    assert.equal(filters.length, 1);
    assert.equal(filters[0].Properties.FilterPattern, '{ $.event = "cli_login_start_ceiling" }');
    assert.ok(filters[0].Properties.LogGroupName.Ref, "on the broker's log group");
    const transformation = filters[0].Properties.MetricTransformations[0];
    assert.equal(transformation.MetricName, "StartCeilingReached");
    assert.equal(transformation.MetricNamespace, "cli-login");
    assert.equal("Dimensions" in transformation, false, "the start-ceiling metric has no dimensions");
    const alarms = Object.values(template.findResources("AWS::CloudWatch::Alarm")).map((resource) => resource.Properties);
    const ceiling = alarms.find((alarm) => alarm.MetricName === "StartCeilingReached")!;
    assert.equal(ceiling.Namespace, "cli-login");
    assert.equal("Dimensions" in ceiling, false);
    assert.ok(alarms.some((alarm) => alarm.MetricName === "Throttles"));

    assert.equal(broker.Properties.Environment.Variables.BROKER_CLIENT_ID, "synthetic-web-client");
    assert.equal(broker.Properties.Environment.Variables.BROKER_APPROVAL_URL, `${site}/cli/approve`);
    assert.equal(broker.Properties.Environment.Variables.BROKER_CALLBACK_URI, `${site}/cli/callback`);
    assert.equal(pages.Properties.Environment.Variables.IDENTITY_PROVIDER, "Google");
    return {};
  },

  async the_broker_alarms_notify_the_sites_alarm_topic_when_one_is_configured() {
    const topicArn = "arn:aws:sns:us-east-1:111111111111:example-site-alarms";
    const { template, annotations } = synthesizeBroker(topicArn);
    const alarms = Object.values(template.findResources("AWS::CloudWatch::Alarm")).map((resource) => resource.Properties);
    assert.equal(alarms.length, 2);
    for (const alarm of alarms) {
      assert.deepEqual(alarm.AlarmActions, [topicArn]);
      assert.deepEqual(alarm.OKActions, [topicArn]);
    }
    annotations.hasNoWarning("*", Match.stringLikeRegexp("notify nobody"));
    return {};
  },

  async without_an_alarm_topic_the_synth_warns_once_and_names_the_setting() {
    const { template, annotations } = synthesizeBroker();
    const alarms = Object.values(template.findResources("AWS::CloudWatch::Alarm")).map((resource) => resource.Properties);
    assert.equal(alarms.length, 2);
    for (const alarm of alarms) {
      assert.equal("AlarmActions" in alarm, false);
      assert.equal("OKActions" in alarm, false);
    }
    const warnings = annotations.findWarning("*", Match.stringLikeRegexp("PAPYRUS_ALARM_TOPIC_ARN"));
    assert.equal(warnings.length, 1);
    assert.match(String(warnings[0].entry.data), /cms\.alarmTopicArn/);
    return {};
  },
};

function synthesizeBroker(alarmTopicArn?: string): { template: Template; annotations: Annotations } {
  const stack = new Stack(new App(), "CliRemoteLoginTest", { env: { account: "111111111111", region: "us-east-1" } });
  addCliRemoteLogin(stack, {
    plan: planCliRemoteLogin(true, { PAPYRUS_SITE_ORIGIN: site, PAPYRUS_CLI_INVOKER_ROLE_ARN: invokerRoleArn })!,
    clientId: "synthetic-web-client",
    graphqlEndpoint: "https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql",
    authorizeEndpoint: "https://shipped.auth.us-east-1.amazoncognito.com/oauth2/authorize",
    product: "Papyrus (shipped.example.test)",
    brokerCode: Code.fromInline("def lambda_handler(event, context): pass"),
    pagesCode: Code.fromInline("def handler(event, context): pass"),
    alarmTopicArn,
  });
  return { template: Template.fromStack(stack), annotations: Annotations.fromStack(stack) };
}

function authChild(mode: string): void {
  process.env.CDK_CONTEXT_JSON = JSON.stringify({ "amplify-backend-name": "remoteloginauth", "amplify-backend-namespace": "remoteloginauth", "amplify-backend-type": "branch" });
  const backend = defineBackend({
    auth: defineSiteAuth({ redirectUrls: ["http://localhost:3001/", `${site}/`] }, mode === "on" ? [`${site}/cli/callback`] : []),
    manageUserRole,
  });
  const clients = Object.values(Template.fromStack(backend.auth.stack).findResources("AWS::Cognito::UserPoolClient")).map((resource) => resource.Properties)
    .filter((client) => client.AllowedOAuthFlowsUserPoolClient === true && client.CallbackURLs?.includes("http://localhost:3001/"));
  assert.ok(clients.length >= 1, "the web client is synthesized");
  console.log(`CLIENT=${JSON.stringify({ CallbackURLs: clients[0].CallbackURLs, LogoutURLs: clients[0].LogoutURLs })}`);
}

async function main() {
  if (process.argv[2] === "auth-child") {
    authChild(process.argv[3]);
    return;
  }
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
  console.log("cli-remote-login ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
