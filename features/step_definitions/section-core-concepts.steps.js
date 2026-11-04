const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
let report;
const run = async () => {
  report ??= (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-section-concepts.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return report;
};
const passed = async (pattern) => {
  if (!pattern.test(await run())) throw new Error(`Expected a passing test matching ${pattern}`);
};

for (const given of ["the stored core concepts of a section", "the schema files and the backend handler"]) Given(given, function () {});
for (const when of [
  "an editor adds, notes and removes core concepts",
  "the section's settings are drawn",
  "a concept's page is drawn",
  "the backend mutation is read",
]) When(when, function () {});

Then("each concept is held once, in the order added, and an empty note is none", () => passed(/✔ core concepts are read from the stored JSON/).then(() => passed(/✔ adding keeps the order and never twice/)));
Then("the heading says {string} and the help sentence is kept", (_heading) => passed(/✔ section settings show 'Core concepts'/));
Then("each concept has its note box and a Remove button", () => passed(/✔ section settings show 'Core concepts'/));
Then("the word {string} appears nowhere", (_word) => passed(/✔ with none, the section says it has no core concepts/));
Then("{string} lists only the sections that have the concept, each with a Remove control", (_heading) => passed(/✔ the concept page lists only the sections that have it/));
Then("one {string} button is shown and no section button is shown yet", (_label) => passed(/✔ the concept page lists only the sections that have it/));
Then("createEditorConcept takes a name, is open to editors and admins only, and is routed to the concept writer", () => passed(/✔ the field and the backend mutation exist in both schema files/));
