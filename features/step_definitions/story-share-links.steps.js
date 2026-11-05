const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
let report;
const run = async () => {
  report ??= (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-story-share.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return report;
};
const passed = async (pattern) => {
  if (!pattern.test(await run())) throw new Error(`Expected a passing test matching ${pattern}`);
};

for (const given of [
  "a share route answers a page, a redirect, a published notice and a refusal",
  "the newsroom's function answers unknown, expired, revoked, malformed or nothing at all",
  "the newsroom's function answers that this link needs a sign-in",
  "the newsroom's function answers that the Story was published",
  "the newsroom's function approves one picture and refuses another",
  "the Share a draft client in the newsroom",
]) Given(given, function () {});
for (const when of [
  "their headers are read",
  "the share route builds its response",
  "the media route builds its responses, including pages, scripts and failures standing in for pictures",
  "a link is made, listed and revoked",
]) When(when, function () {});

Then("each one says noindex, no-store and no-referrer", () => passed(/✔ every answer of a share route carries the three headers/));
Then("the status, headers and body are identical and say only that the link is not available", () => passed(/✔ an unknown, expired, revoked or malformed link is one and the same page/));
Then("the visitor is redirected to the newsroom's sign-in page for that link and no draft is sent", () => passed(/✔ a page passes through, signing in redirects, and the published notice links only to https/));
Then("a plain page links to the published address, and only an https address is accepted", () => passed(/✔ a page passes through, signing in redirects, and the published notice links only to https/));
Then("only the approved image is sent, with a sandboxing policy, and everything else is the plain refusal", () => passed(/✔ pictures are served only when approved, only as images, and never as something a browser could run/));
Then("the newsroom is asked with the chosen expiry, the version only when pinned, and a refusal is shown in its own words", () => passed(/✔ the expiry is a choice of 7, 30 or 90 days and the client asks the newsroom to create, list and revoke/));
