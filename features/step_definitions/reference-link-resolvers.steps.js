const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
let report;
const run = async () => {
  report ??= (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-reference-links.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return report;
};
const passed = async (pattern) => {
  if (!pattern.test(await run())) throw new Error(`Expected a passing test matching ${pattern}`);
};
let pythonReport;
const pythonPassed = async () => {
  pythonReport ??= (await promisify(execFile)("poetry", ["run", "pytest", "-q", "procedures/newsroom/tests/test_content_actions_suggest_links.py"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  if (!/passed/.test(pythonReport)) throw new Error(`Expected passing Python tests, got ${pythonReport}`);
};

Given("the shared link examples", function () {});
for (const when of [
  "an editor links two References as related, in either order",
  "an editor tags a Reference with a concept",
  "an editor rejects a link with a reason and later accepts it",
  "an editor accepts a machine suggestion",
  "the backend schema is read",
  "a link is asked for with an unknown predicate or a Reference that does not exist",
  "links are suggested for a Reference",
]) When(when, function () {});

Then("there is one current link recorded as human, and it matches the Python writer", () => passed(/✔ byte-compatible with the Python writer: a person links two references/).then(() => passed(/✔ a second write of the same pair updates the one row/)));
Then("the link goes from the Reference to the concept and matches the Python writer", () => passed(/✔ byte-compatible with the Python writer: a person tags a reference with a concept/));
Then("the link records who decided and when, and matches the Python writer", () => passed(/✔ byte-compatible with the Python writer: a person rejects a link/));
Then("the suggestion becomes a current link and matches the Python writer", () => passed(/✔ byte-compatible with the Python writer: a person accepts a machine suggestion/));
Then("createReferenceLink and decideReferenceLink and suggestReferenceLinks are open to editors and admins only", () => passed(/✔ only editors can call the three mutations/));
Then("the request is refused in words", () => passed(/✔ bad input is refused in words/).then(() => passed(/✔ only a reference or concept link can be decided/)));
Then("the suggestion runs against the site's vector index with no embedding key", () => pythonPassed());
