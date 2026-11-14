const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
let report;
const run = async () => {
  report ??= (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-message-hashtags.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return report;
};
const passed = async (pattern) => {
  if (!pattern.test(await run())) throw new Error(`Expected a passing test matching ${pattern}`);
};

for (const given of ["a person's Message that mentions an accepted concept by hashtag", "a person's Message that mentions an unknown hashtag"]) Given(given, function () {});
for (const when of ["the hashtags in the Message are linked", "the hashtags in the Message are linked twice", "someone else asks for its hashtags to be linked"]) When(when, function () {});

Then("one current related-to edge goes from the Message to the concept, recorded as human", () => passed(/✔ a matching hashtag becomes a current human related-to edge/).then(() => passed(/✔ running twice leaves one edge/)));
Then("the hashtag is listed on the Message as unmatched and no edge is written", () => passed(/✔ an unknown or ambiguous hashtag is listed on the message/));
Then("the request is refused in words", () => passed(/✔ only the author's own person-written message is linked/));
