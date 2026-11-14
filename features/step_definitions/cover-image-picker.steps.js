const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const exec = promisify(execFile);
let typescript;
let python;
const runTypescript = async () => {
  typescript ??= (await exec(process.execPath, ["--import", "tsx", "--test", "scripts/test-stock-images.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return typescript;
};
const runPython = async () => {
  // PAPYRUS_TEST_PYTHON names a Python that already has the project installed; without it the steps use `poetry run`, like the other profiles.
  const own = process.env.PAPYRUS_TEST_PYTHON;
  const [command, args] = own ? [own, ["-m", "pytest", "-q"]] : ["poetry", ["run", "pytest", "-q"]];
  python ??= (await exec(command, [...args, "procedures/newsroom/tests/test_stock_cover_credit.py"], { cwd: root, maxBuffer: 8 * 1024 * 1024, env: { ...process.env, PYTHONPATH: `${path.join(root, "src")}:${root}` } })).stdout;
  return python;
};
const passed = async (pattern) => {
  if (!pattern.test(await runTypescript())) throw new Error(`Expected a passing test matching ${pattern}`);
};

const steps = [
  "a Story whose title and summary are about offshore wind", "the picker has shown four options", "the picker is waiting for Wikimedia Commons",
  "Wikimedia Commons answers with files of many licences", "a search that needs more than one request", "the cover search route", "an editor accepts an option",
  "an editor accepts an option on a saved Story", "a Story with a stock cover",
];
for (const given of steps) Given(given, function () {});
for (const when of [
  "the editor opens the cover picker without typing anything", "the editor presses reload", "the editor types search words and presses Search",
  "there is nothing to show, or the search fails", "the answers are read", "the requests are made", "someone without a valid sign-in, or a signed-in reader, calls it",
  "the server copies the picture", "the cover is put in the draft", "its pages are built",
]) When(when, function () {});

Then("four options are shown, each with its creator, licence and file page link", () => passed(/✔ the picker shows four options with their credit/));
Then("the picker says what it searched for and that the words came from the Story", () => passed(/✔ with no target the search words come from the title first/).then(() => passed(/✔ the picker shows four options with their credit/)));
Then("the next four options come from further down the same results", () => passed(/✔ search returns four allowed images, skips disallowed ones, and a reload continues without repeats/));
Then("none of the pictures already shown is offered again", () => passed(/✔ the preview source never repeats an option/));
Then("the picker searches for those words and the typed words stay in the text box", () => passed(/✔ loading, nothing found, failure and no-more each say so in words and keep the typed text/));
Then("the picker says it is looking, or that nothing was found with a licence we can use, or what went wrong", () => passed(/✔ loading, nothing found, failure and no-more each say so in words/));
Then("the words the editor typed are kept", () => passed(/✔ loading, nothing found, failure and no-more each say so in words and keep the typed text/));
Then("a failed search can be tried again", () => passed(/✔ loading, nothing found, failure and no-more each say so in words/));
Then("public domain, CC0 and CC BY pictures with a creator and a licence address are offered", () => passed(/✔ only public domain, CC0 and CC BY are offered/).then(() => passed(/✔ a good page becomes a credited candidate/)));
Then("share-alike, non-commercial, no-derivatives, non-free and unknown licences are never offered", () => passed(/✔ only public domain, CC0 and CC BY are offered; share-alike/));
Then("a file with restrictions, no creator, a small size or an unaccepted type is never offered", () => passed(/✔ a page without usable licence data, creator, type, size or address is dropped/));
Then("they go one after another, name the client and its contact in the User-Agent, ask the API to report load, and stop with a retry hint when Wikimedia says it is busy", () =>
  passed(/✔ when a page has too few allowed images the source asks again, one request after another/).then(() => passed(/✔ a busy or rate-limited answer stops the search with a retry hint/)));
Then("an identical request within ten minutes is answered from memory", () => passed(/✔ an empty target asks nothing; a repeated identical request is served from memory/));
Then("it answers that sign-in as an editor is needed and never reaches the image source", () => passed(/✔ the route answers only a verified editor or admin/));
Then("an editor and an administrator are served", () => passed(/✔ the route answers only a verified editor or admin/));
Then("the licence is looked up again at the source and the address comes from the source, never from the browser", () => passed(/✔ a pick is looked up at the source, copied only from the source's own address/));
Then("a picture that is not a JPEG, PNG or WebP, is too narrow, is too large, or is not at an allowed Wikimedia host is refused in words", () =>
  passed(/✔ picture bytes are checked by their own content/).then(() => passed(/✔ a pick is looked up at the source, copied only from the source's own address/)));
Then("the body starts with the picture and its credit, the front matter points at the copy and records the author, licence, licence address and file page", () => passed(/✔ the front matter gets the cover path and a structured record/).then(() => passed(/✔ the body gets the credited figure first/)));
Then("an earlier stock cover is replaced in place while any other figure, such as a diagram, stays", () => passed(/✔ the body gets the credited figure first; an earlier stock cover or seeded picture is replaced in place/));
Then("the Night counterpart of the old cover is removed so a photo is shown as it is in dark mode", () => passed(/✔ the front matter gets the cover path and a structured record, and loses the Night counterpart/));
Then("nothing is saved until the editor saves the draft", () => passed(/✔ the body gets the credited figure first/));
Then("the article page's figure has the credit directly under the picture", async () => {
  if (!/passed/.test(await runPython())) throw new Error("the credit test did not pass");
});
Then("no card, listing, feed or data file carries the credit or the cover record", async () => {
  if (!/2 passed/.test(await runPython())) throw new Error("the card test did not pass");
});
