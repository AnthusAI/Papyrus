const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then, setDefaultTimeout } = require("@cucumber/cucumber");

setDefaultTimeout(240_000);

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
  "the admin looks at the files of the site's guidelines", "the admin changes the tone file, looks at what would change, gives a reason and accepts",
  "the admin adds a rule file, fills in its severity, words to avoid, longest text and prose, removes another rule file and rejects a change to a third",
  "the admin opens a section tab, adds a tone file and a lexicon file, and accepts with a reason",
  "the admin opens a section tab", "an editor opens the page", "the admin changes a file and gives no reason, or only blank spaces",
  "the admin opens the voice examples file, searches the published Stories, picks one, says what it shows and saves",
]) When(step, function () {});

Then("every field file and every rule file is listed by name, marked as a field file or a rule file", ok("files_listed"));
Then("each file says its severity in words: error, warning or guidance", ok("files_listed"));
Then("a rule that derives a check names it and says whether it is on, and a rule with only prose says it needs judgement", ok("files_listed"));
Then("a field the site locks says in words that sections cannot change it", ok("files_listed"));
Then("opening a rule file shows its description, severity, words to avoid, patterns and body", ok("files_listed"));
Then("the preview names the file that changed and the field that changed", ok("site_edit"));
Then("the page says it saved version 2 and the save names the version it replaces", ok("site_edit"));
Then("the set is sent as files, and every file the admin did not touch is sent exactly as it was read", async () => { await ok("site_edit")(); await passes(logic(), /✔ an edit keeps the other bytes/); });
Then("the history lists both versions with who, when and why", ok("site_edit"));
Then("picking two versions shows what changed between them in words", async () => { await ok("site_edit")(); await passes(logic(), /✔ changes between two versions are described in plain words/); });
Then("a name that is not lowercase words joined by hyphens, is a field file's name or is already taken is refused in words", async () => { await ok("rule_files")(); await passes(logic(), /✔ a new rule file is guidance with a permanent id/); });
Then("a new rule starts as guidance and says a check is derived when it is saved as an error or a warning", ok("rule_files"));
Then("a file that is refused when saved shows the problem under that file, naming the key", ok("rule_files"));
Then("a rejected change puts the saved file back, and a removed file says it is deleted when the admin accepts", async () => { await ok("rule_files")(); await passes(logic(), /✔ what changed since the saved set is told per folder/); });
Then("the preview lists the added and removed files and the check that would be created", ok("rule_files"));
Then("the saved rule file has its front matter written in the file form and the removed file is gone from the set", async () => { await ok("rule_files")(); await passes(logic(), /✔ front matter is written the way the file form writes it/); });
Then("the section's set holds only its own files, with the section as their scope, and none of the site-only files is offered", async () => { await ok("section_override")(); await passes(logic(), /✔ a section is offered only the field files it may add/); });
Then("the In effect page says for every field whether it came from the site, this section or both", async () => { await ok("section_override")(); await passes(logic(), /✔ each field says where it came from in words/); });
Then("prose and word lists show the site's lines first and the section's after them", ok("section_override"));
Then('a field the site locks says "Locked by site" and is not offered as a file to add', async () => { await ok("locked_field")(); await passes(logic(), /✔ the fields the site locks are read from its locked file/); });
Then("a field the site leaves open can be added and shows the site's value as a hint", ok("locked_field"));
Then("on the Site tab the same field can be changed and says in words that sections cannot change it", ok("locked_field"));
Then("the page says in words that it is read only", ok("editor_read_only"));
Then("every box is disabled and there is no save button, no way to add or remove a file and no Story picker", ok("editor_read_only"));
Then("the history can still be read", ok("editor_read_only"));
Then("the save button stays off and the page says a reason is needed", async () => { await ok("reason_required")(); await passes(logic(), /✔ a reason is required and blank spaces are not one/); });
Then("Reject all changes puts the saved set back and the page says no file has changed", ok("reason_required"));
Then("nothing is sent to be saved", ok("reason_required"));
Then("the picker narrows to the matching Stories", async () => { await ok("exemplar_pick")(); await passes(logic(), /✔ the Story picker narrows by title/); });
Then("the saved voice examples file lists the Story with the note", async () => { await ok("exemplar_pick")(); await passes(logic(), /✔ the voice examples of an exemplars file/); });
Then("the page says the publication has no writing guidelines yet", ok("empty_and_checks"));
Then("the first save expects no earlier version and makes version 1", ok("empty_and_checks"));
Then("only the editorial checks drawn from these guidelines are listed, with a link to Editorial checks", async () => { await ok("empty_and_checks")(); await passes(logic(), /✔ derived checks are the ones whose source names this document/); });
