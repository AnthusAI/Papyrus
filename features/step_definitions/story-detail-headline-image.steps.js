const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const exec = promisify(execFile);
let output;
const run = async () => {
  output ??= (await exec(process.execPath, ["--import", "tsx", "--test", "scripts/test-story-headline-image.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return output;
};
const passed = async (pattern) => {
  if (!pattern.test(await run())) throw new Error(`Expected a passing test matching ${pattern}`);
};

for (const given of [
  "a Story whose front matter names a site-media image", "a Story that sets thumbnail and ogImage but not image or cover", "a cover set by the cover picker, stored as a path with a leading slash",
  "a Story whose front matter sets none of the headline keys", "a media row for the picture that has no stored file yet",
  "a Story naming a file with no media row, a file the storage cannot read, or a media list that fails", "a draft whose image differs from the published version's",
]) Given(given, function () {});
for (const when of ["the Story detail opens", "the headline image is read", "the media files are listed", "the draft is open"]) When(when, function () {});

Then("the picture is shown above the editor and the preview", () => passed(/✔ a resolved picture is shown with its alt text/));
Then("its alt text is the figure's alt, else the cover's title, else the Story's title", () => passed(/✔ alt text comes from the body figure/));
Then("ogImage is the one shown", () => passed(/✔ the first of image, cover, ogImage, thumbnail/));
Then("the picture is found by the same name the media row carries", () => passed(/✔ a site-media value loses its leading slash/));
Then("it says there is no headline image and that cards and shares have no picture", () => passed(/✔ no image says so in words/));
Then("it says the headline image is still processing", () => passed(/✔ media not yet listed is loading/));
Then("it says which of the three happened, in words", () => passed(/✔ a named file with no media row/));
Then("the draft's picture is shown", () => passed(/✔ a draft version's own front matter/));
