const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const exec = promisify(execFile);
let output;
const run = async () => {
  output ??= (await exec(process.execPath, ["--import", "tsx", "--test", "scripts/test-story-preview-heading.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return output;
};
const passed = async (pattern) => {
  if (!pattern.test(await run())) throw new Error(`Expected a passing test matching ${pattern}`);
};

for (const given of [
  "a Story saved with the title \"A Home Surveillance Drone with Cloud AI — What Could Go Wrong?\" and a deck that begins \"Ring's Drone Cam is sold as security\"",
  "a Story with a title and a deck", "a Story whose front matter has a deck and no title",
]) Given(given, function () {});
When("the Preview pane opens", function () {});

Then("the headline is the title", () => passed(/✔ the title is the headline and the deck is only the deck/));
Then("the deck follows it as the deck, whether the front matter is plain, folded over two lines, or quoted", () => passed(/✔ the title is the headline and the deck is only the deck/));
Then("the headline is drawn above the deck and no blurb line appears when the front matter has no blurb", () => passed(/✔ the Preview pane draws the headline before the deck/));
Then("the headline is the Story's address and the deck is not used as the headline", () => passed(/✔ a Story with no title still has a headline/));
