const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const exec = promisify(execFile);
const runs = new Map();
// Each scenario's Then steps check the real browser run of the matching scenario in scripts/test-writing-guidelines-admin.ts (and the logic tests beside it).
const run = (key, args) => {
  if (!runs.has(key)) runs.set(key, exec(process.execPath, ["--import", "tsx", ...args], { cwd: root, maxBuffer: 16 * 1024 * 1024 }).then((result) => result.stdout + result.stderr));
  return runs.get(key);
};
const browser = (scenario) => run(scenario, ["scripts/test-writing-guidelines-admin.ts", scenario]);
const logic = () => run("logic", ["--test", "scripts/test-writing-guidelines-admin-logic.ts"]);
const passes = async (output, pattern) => { if (!pattern.test(await output)) throw new Error(`Expected output matching ${pattern}`); };
const ok = (scenario) => () => passes(browser(scenario), new RegExp(`ok - ${scenario}`));

Given("the writing guidelines page of a publication that has site guidelines", function () {});
Given("the writing guidelines page of a publication that has no site guidelines", function () {});
for (const step of [
  "the admin changes the tone, looks at what would change, gives a reason and saves", "the admin opens a section tab, adds a tone and a word to avoid, and saves with a reason",
  "the admin opens a section tab", "an editor opens the page", "the admin changes a field and gives no reason, or only blank spaces",
  "the admin searches the published Stories, picks one, says what it shows and saves",
]) When(step, function () {});

Then("the page says it saved version 2 and the save names the version it replaces", ok("site_edit"));
Then("the binding rules are carried over untouched", async () => { await ok("site_edit")(); await passes(logic(), /✔ an empty field is left out, and fields the form does not edit are carried over/); });
Then("the history lists both versions with who, when and why", ok("site_edit"));
Then("picking two versions shows what changed between them in words", async () => { await ok("site_edit")(); await passes(logic(), /✔ changes between two versions are described in plain words/); });
Then("the section's document holds only its additions, without the site's locks or binding rules", async () => { await ok("section_override")(); await passes(logic(), /✔ a section's document never carries the site-only fields/); });
Then("the In effect page says for every field whether it came from the site, this section or both", async () => { await ok("section_override")(); await passes(logic(), /✔ each field says where it came from in words/); });
Then("prose and word lists show the site's lines first and the section's after them", ok("section_override"));
Then('a field the site locks says "Locked by site" and cannot be edited', ok("locked_field"));
Then("a field the site leaves open can be set and shows the site's value as a hint", ok("locked_field"));
Then("on the Site tab the same field can be changed and says in words that it is locked", ok("locked_field"));
Then("the page says in words that it is read only", ok("editor_read_only"));
Then("every box is disabled and there is no save button and no Story picker", ok("editor_read_only"));
Then("the history can still be read", ok("editor_read_only"));
Then("the save button stays off and the page says a reason is needed", async () => { await ok("reason_required")(); await passes(logic(), /✔ a reason is required and blank spaces are not one/); });
Then("nothing is sent to be saved", ok("reason_required"));
Then("the picker narrows to the matching Stories", async () => { await ok("exemplar_pick")(); await passes(logic(), /✔ the Story picker narrows by title/); });
Then("the saved document lists the Story with the note", ok("exemplar_pick"));
Then("the page says the publication has no writing guidelines yet", ok("empty_and_checks"));
Then("the first save expects no earlier version and makes version 1", ok("empty_and_checks"));
Then("only the editorial checks drawn from these guidelines are listed, with a link to Editorial checks", async () => { await ok("empty_and_checks")(); await passes(logic(), /✔ derived checks are the ones whose source names this document/); });
