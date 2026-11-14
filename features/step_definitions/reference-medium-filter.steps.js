const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then, setDefaultTimeout } = require("@cucumber/cucumber");

// The browser scenario runs the same fixture the feed's other scenarios use, at 375 and 1440 pixels.
setDefaultTimeout(240_000);

const root = path.resolve(__dirname, "../..");
let run;
const scenario = () => (run ??= promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-reference-feed.ts", "medium"], { cwd: root, maxBuffer: 8 * 1024 * 1024 }).then((result) => result.stdout));
const passed = async () => assert.ok((await scenario()).includes("Reference feed scenario passed: medium"));

Given("a synthetic site with pending, accepted and rejected videos in two corpora, a starred video, an archived video and an article", function () { this.mediumResult = ""; });
When("the editor chooses Videos with Reviewed No", async function () { this.mediumResult = await scenario(); });
When("the editor chooses Videos and then each Reviewed choice, a minimum of three stars, and Captured Yes", async function () { this.mediumResult = await scenario(); });
When("the editor opens the page on medium=video and chooses Predictions, or searches", async function () { this.mediumResult = await scenario(); });
When("the editor looks at the Medium row at 375 and 1440 pixels", async function () { this.mediumResult = await scenario(); });
Then("only the pending videos are listed, newest first, across both corpora", passed);
Then("the page read the pending medium partition of each corpus and no other index", passed);
Then("the address names medium=video and keeps the rest of the address", passed);
Then("the saved Sort is unchanged, although Newest shows as chosen because the medium index is by arrival", passed);
Then("Reviewed Accepted lists the accepted videos and Reviewed Yes lists the accepted and rejected ones", passed);
Then("a minimum of three stars lists only the starred video", passed);
Then("Captured Yes with nothing captured says in words that there are no videos, with a button to show all media", passed);
Then("choosing Predictions goes back to All and removes the medium from the address", passed);
Then("the Medium row is out of the way while a search is open", passed);
Then("All and Videos each have a Lucide icon and a word, there is no drop-down and no border, and nothing scrolls sideways", passed);
