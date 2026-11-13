const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const exec = promisify(execFile);
const runs = new Map();
// Each scenario's Then steps check the real browser run of the matching scenario in scripts/test-visual-style-admin.ts (and the logic tests beside it).
const run = (command, args) => {
  const key = [command, ...args].join(" ");
  if (!runs.has(key)) runs.set(key, exec(process.execPath, ["--import", "tsx", ...args], { cwd: root, maxBuffer: 16 * 1024 * 1024 }).then((result) => result.stdout + result.stderr));
  return runs.get(key);
};
const browser = (scenario) => run("browser", ["scripts/test-visual-style-admin.ts", scenario]);
const logic = () => run("logic", ["--test", "scripts/test-visual-style-admin-logic.ts"]);
const passes = async (output, pattern) => { if (!pattern.test(await output)) throw new Error(`Expected output matching ${pattern}`); };

Given("the visual style page of a publication that has a saved style", function () {});
Given("the visual style page of a publication that has no saved style", function () {});
for (const step of [
  "the editor chooses when pictures are reviewed, edits the summary and saves", "the editor opens the Image types page", "the editor adds a type that starts from another one",
  "the editor retires the type and then brings it back", "the editor opens a type that extends another", "the editor moves a source down and saves the guidance",
  "the editor opens a type and adds a good example and a picture to avoid", "the editor removes a picture", "the editor drafts a starting style",
]) When(step, function () {});

const ok = (scenario) => () => passes(browser(scenario), new RegExp(`ok - ${scenario}`));
Then("each change is a new version and the page says so in words", ok("brand_page"));
Then('the selected review choice says "selected" in words, not only by its look', ok("brand_page"));
Then("a colour without a valid hex value is refused in plain words before anything is saved", ok("brand_page"));
Then("a change made on top of someone else's newer version is refused and the page reloads", ok("stale_edit"));
Then("each type shows its family, use, thumbnail or not, smallest size, sources in order and how many examples it has", ok("image_types_list"));
Then("the new type extends the other and does not copy its example pictures", async () => { await ok("image_types_list")(); await passes(logic(), /✔ adding a type: a key from the name/); });
Then("a name that is already taken, or empty, is refused in plain words", ok("image_types_list"));
Then("it moves to Retired types and returns, and its key never changes", ok("image_types_list"));
Then("the rules in effect show the brand, the family, the parent type and this type, each line saying where it came from", ok("type_page"));
Then("what this type took off its parent is listed in words", ok("type_page"));
Then("the binding rules are shown as rules that cannot be loosened", ok("type_page"));
Then("the sources are reordered and the guidance is saved as new versions", ok("type_page"));
Then("a picture that is not PNG, JPEG or WebP, or is over 10 MB, is refused in plain words before it is uploaded", ok("examples_grid"));
Then("a note is required, and sending the picture to the image model is off until the editor turns it on", ok("examples_grid"));
Then("each example says whether it is good or to avoid, and whether it is sent to the image model, in words", ok("examples_grid"));
Then("a type shown as a thumbnail also shows each example at its smallest size", ok("examples_grid"));
Then("the page says older versions of the style still list it", ok("examples_grid"));
Then("a child type does not show its parent's examples", ok("examples_grid"));
Then("the page says the publication has no image style guidelines, so generated images will look unpredictable, and says where to fix it", ok("no_style"));
Then("it says pictures can still be searched for and made without a style", ok("no_style"));
Then("the draft is shown, nothing is saved, and saving it makes the first version", ok("no_style"));
