const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const run = (name) => promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-newsroom-section-picker.ts", name], { cwd: root });

Given("a site with the sections Methods and Security enabled and Retired disabled", function () {});
Given("a Story whose section is Security and a site whose sections have not loaded", function () {});
When("the editor opens the Section picker on a Story with no section", function () {});
When("the editor opens a Story whose section is Security", function () {});
Then("the picker offers Methods then Security and not Retired", async function () { await run("lists_sections"); });
Then("the picker shows Security and not No section", async function () { await run("shows_current"); });
Then("the picker still shows Security, and a disabled section the Story still has stays visible", async function () { await run("keeps_unlisted_current"); });
