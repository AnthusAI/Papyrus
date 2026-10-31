const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { When, Then } = require("@cucumber/cucumber");

async function behaviours(...names) {
  const results = [];
  for (const name of names) {
    const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-cli-enroll-route.ts", name],
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

when("the CLI posts a valid challenge, its tokens and the transaction to the enroll route", "the_route_resolves_a_person_for_the_right_tokens_and_state");
then("the route answers with the Person's id and nothing else");
when("the same challenge is posted again, first with the same tokens and then with other tokens", "a_replay_with_other_tokens_is_refused_and_the_same_tokens_return_the_same_person");
then("the same tokens return the same Person");
then("the other tokens are refused as challenge_replay");
when("a login made on the main web client posts to the enroll route", "a_login_on_the_main_web_client_cannot_enroll");
then("the route refuses it as login_not_enrollable before asking Prospectus");
when("Prospectus refuses an enrollment in each documented way", "error_responses_name_no_service_detail_beyond_the_code");
then("the route passes through only challenge_invalid, login_state, challenge_replay or reenrollment_required with their status");
then("any other failure is answered as unavailable without the service's message");
when("a site has not switched enrollment on", "a_site_that_did_not_switch_enrollment_on_answers_404_and_calls_nothing", "enrollment_is_off_unless_switched_on_and_off_synthesizes_unchanged");
then("the enroll route answers 404 and calls nothing");
then("the site's pages function gets no challenge origin, throttle table or Prospectus access, so its stack is unchanged");
when("the challenge route is asked for a remote login's digest or a local login's state", "a_login_challenge_is_bound_to_a_digest_and_validated_before_it_is_answered");
then("Prospectus is asked for a challenge bound to exactly 64 lowercase hex characters, never an unbound one");
then("a challenge without a uuid4 id, a well-formed nonce, an expiry within 300 seconds and a signed token is answered as unavailable");
when("more challenges are asked for than the site's bucket allows", "the_challenge_route_is_throttled_per_site_and_fails_closed");
then("the route answers 429 and never reaches Prospectus");
then("the bucket is one request per second with a burst of two unless the site sets its own, and a storage failure refuses the request");
