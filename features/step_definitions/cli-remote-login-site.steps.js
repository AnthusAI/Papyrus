const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { When, Then } = require("@cucumber/cucumber");

// Each behaviour runs scripts/test-cli-remote-login.ts, which asserts internally and prints its result.
async function behaviours(...names) {
  const results = [];
  for (const name of names) {
    const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-cli-remote-login.ts", name],
      { cwd: path.resolve(__dirname, "../.."), maxBuffer: 8 * 1024 * 1024 });
    results.push(JSON.parse(result.stdout));
  }
  return results;
}

function when(text, ...names) {
  When(text, { timeout: 120_000 }, async function () { this.results = await behaviours(...names); });
}

function then(text) {
  Then(text, function () { assert.ok(this.results && this.results.length > 0); });
}

when("no site has set the remote CLI login flag", "it_is_off_for_every_site_by_default");
then("remote CLI login is off for every site, the original production site included");
then("no broker, pages function, Cognito callback or output is planned");
when("a site turns remote CLI login on", "switching_it_on_needs_the_site_origin_and_the_compute_role");
then("it must name its public https origin and the Amplify compute role that serves its pages");
when("the site's web client is synthesized with and without the feature", "the_web_client_registers_the_remote_callback_only_when_switched_on");
then("the feature only adds the site's remote callback after the existing callbacks, and never a logout URL");
when("a site's broker is synthesized", "the_broker_keeps_its_security_properties");
then("the public URL takes no credentials and only the pages function's role may invoke the private operations");
then("the broker is bounded, reads and writes only its own table, and alarms on its start ceiling and throttling");
then("only the site's compute role may invoke the pages function");
when("a site's broker is synthesized with an alarm topic", "the_broker_alarms_notify_the_sites_alarm_topic_when_one_is_configured");
then("both broker alarms notify that topic when they fire and when they recover");
when("a site's broker is synthesized without an alarm topic", "without_an_alarm_topic_the_synth_warns_once_and_names_the_setting");
then("the alarms carry no notification and synth warns once naming the alarm topic setting");
when("the Lambda bundles are built", "the_cli_the_broker_and_the_pages_run_the_same_cli_login_release", "the_pages_function_never_imports_papyrus_content");
then("the broker and the pages install the exact release that pyproject.toml pins for the CLI");
then("the pages function does not import papyrus_content");
when("a site that turned it on serves its login file", "discovery_publishes_the_broker_when_the_site_switched_it_on");
Then("it names the broker and the site's own remote callback", function () {
  assert.equal(this.results[0].status, 200);
  assert.ok(this.results[0].body.broker_endpoint.startsWith("https://"));
  assert.ok(this.results[0].body.remote_callback_uri.endsWith("/cli/callback"));
});
Then("a site that did not publishes no broker, and so does a site whose client lacks the callback", async function () {
  const results = await behaviours(
    "discovery_publishes_no_broker_when_the_site_did_not_switch_it_on",
    "discovery_publishes_no_broker_when_its_callback_is_not_registered_on_the_client",
    "discovery_publishes_no_broker_for_a_callback_on_another_origin");
  for (const result of results) assert.equal(result.body.broker_endpoint, undefined);
});
when("the browser opens the approval page and submits the form", "forwards_the_approval_page", "forwards_the_approval_form_and_every_cookie_the_page_sets", "forwards_the_callback", "the_pages_are_served_at_the_site_root");
then("the request reaches the pages function with its method, path, query, cookies and body");
then("the page, its redirect and every cookie it sets reach the browser");
then("the pages are served at the site root");
when("the browser opens the approval page of a site that did not turn it on", "a_site_without_the_pages_function_answers_not_found_and_calls_nothing");
Then("the answer is {string} and nothing is invoked", function (answer) {
  assert.equal(answer, "not found");
  assert.equal(this.results[0].status, 404);
  assert.equal(this.results[0].calls, 0);
});
when("the pages function is unavailable or answers nonsense", "an_unavailable_pages_function_says_so_without_details", "a_malformed_answer_is_a_bad_gateway");
then("the browser is told sign-in is unavailable without any detail");
