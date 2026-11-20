const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then, setDefaultTimeout } = require("@cucumber/cucumber");

setDefaultTimeout(120_000);

const root = path.resolve(__dirname, "../..");
const exec = promisify(execFile);
const runs = new Map();
// Each scenario's Then steps check the real browser run of the matching scenario in scripts/test-editorial-languages-admin.ts (and the logic tests beside it).
const run = (key, args) => {
  if (!runs.has(key)) runs.set(key, exec(process.execPath, ["--import", "tsx", ...args], { cwd: root, maxBuffer: 16 * 1024 * 1024 }).then((result) => result.stdout + result.stderr));
  return runs.get(key);
};
const browser = (scenario) => run(scenario, ["scripts/test-editorial-languages-admin.ts", scenario]);
const logic = () => run("logic", ["--test", "scripts/test-editorial-languages-admin-logic.ts"]);
const passes = async (output, pattern) => { if (!pattern.test(await output)) throw new Error(`Expected output matching ${pattern}`); };
const ok = (scenario) => () => passes(browser(scenario), new RegExp(`ok - ${scenario}`));

Given("the editorial checks settings of a site that writes in English, Latin American Spanish and Chinese, with only English public", function () {});
Given("the editorial checks settings of a site whose Spanish is public with its own prefix and whose Chinese uses pinyin slugs", function () {});
for (const step of [
  "the admin makes Latin American Spanish public and saves the settings",
  "the admin looks at the controls for Latin American Spanish and Chinese",
  'the admin gives Latin American Spanish the prefix "latam" and the slug policy of the original story\'s address, and saves',
  "the admin gives Latin American Spanish the prefix that Chinese already uses",
  "the admin changes only the house guidance and saves",
  "the admin removes Chinese from the languages the site writes in and saves",
]) When(step, function () {});

Then("the page says the settings were saved", ok("make_public"));
Then("the saved languages list English first and then Latin American Spanish as public", async () => { await ok("make_public")(); await passes(logic(), /✔ making a language public lists the primary first and keeps every other key/); });
Then("the saved languages keep every key the form does not show, and the house guidance is unchanged", ok("make_public"));
Then("each prefix shows its default and says which address the pages live under", ok("prefix_and_slug"));
Then("each slug policy shows its default, translated for Spanish and the title's own script for Chinese", ok("prefix_and_slug"));
Then("the saved languages hold only that prefix and that slug policy, and no public list", ok("prefix_and_slug"));
Then("the page says in words that the two languages would both be served under the same address", ok("refused"));
Then("the save button is off and nothing is saved", ok("refused"));
Then("the admin can still correct the prefix, and the message goes away and the save button comes back", async () => { await ok("refused")(); await passes(logic(), /✔ a refusal keeps the last rows so the field that caused it can be corrected/); });
Then("the saved languages are exactly the languages that were stored", ok("keeps_stored"));
Then("the saved languages no longer mention Chinese anywhere", async () => { await ok("remove_language")(); await passes(logic(), /✔ settling drops what names a language that is no longer enabled and keeps the rest/); });
Then("the Spanish settings are kept", ok("remove_language"));
