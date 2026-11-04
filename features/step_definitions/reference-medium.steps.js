const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then, setDefaultTimeout } = require("@cucumber/cucumber");

// Four browsers: 375 and 1440 pixels, light and dark.
setDefaultTimeout(120_000);

const root = path.resolve(__dirname, "../..");
let run;
const scenario = () => (run ??= promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-reference-medium-card.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 }).then((result) => result.stdout));

Given("a synthetic site with a video Reference and an article Reference", function () { this.mediumResult = ""; });
When("the editor looks at the References feed cards in light and dark at 375 and 1440 pixels", async function () { this.mediumResult = await scenario(); });
Then("the video card has a \"Video\" label with a Lucide video icon and the article card has none", async function () { assert.ok((await scenario()).includes("Reference medium card passed")); });
Then("the label has no border or outline and nothing scrolls sideways", async function () { assert.ok((await scenario()).includes("Reference medium card passed")); });
