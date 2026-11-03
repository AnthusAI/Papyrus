const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

// The browser scenarios "captured" (scripts/test-reference-feed.ts) and "captureNeeded" (scripts/test-notification-center-feed.ts), both at 375 and 1440
// pixels on fixture data with no network, and the unit scripts for the stored rule and the readers, each run once for the whole feature.
const root = path.resolve(__dirname, "../..");
const runs = new Map();
const script = (file, ...args) => {
  const key = [file, ...args].join(" ");
  if (!runs.has(key)) runs.set(key, promisify(execFile)(process.execPath, ["--import", "tsx", file, ...args], { cwd: root, maxBuffer: 8 * 1024 * 1024, env: { ...process.env, PAPYRUS_ALLOW_CROSS_ROOT: "1" } }).then((result) => result.stdout + result.stderr));
  return runs.get(key);
};
const feed = () => script("scripts/test-reference-feed.ts", "captured");
const home = () => script("scripts/test-notification-center-feed.ts", "captureNeeded");
const rule = () => script("scripts/test-capture-state.ts");
const readers = () => script("scripts/test-reference-feed-pages.ts");
const T = { timeout: 300_000 };

const given = (text) => Given(text, function () { this.captureNeededResult = ""; });
given("a synthetic site where some References are captured, some are thin, one is still being captured and some are only an address");
given("a synthetic site where sixty captured References arrived after the three we could not collect");
given("an isolated newsroom home where accepted References have stars, some are still capturing, one is rejected and one is captured");
given("records held in memory with stars, a capture state, a status and a version state");

const feedWhens = [
  "the editor looks at the Reviewed and Captured controls at 375 and 1440 pixels",
  "the editor chooses Captured Yes, then Captured No, under Quality with Reviewed Any",
  "the editor chooses Reviewed Accepted, then Reviewed Yes, and combines Accepted with Captured No",
  "the editor chooses Newest and Captured No",
  "the editor searches with Captured No and then chooses Reviewed Accepted",
  "the editor chooses Reviewed Accepted, the minimum 5 and Captured Yes",
  "the editor opens the References page on Reviewed Accepted, Captured No and Sort Quality from an address",
];
for (const text of feedWhens) When(text, T, async function () { this.out = await feed(); });
const feedThens = [
  "Reviewed reads Any, Accepted, Yes and No and Captured reads Any, Yes and No, each a button with a Lucide icon and words, with no drop-downs and no borders",
  "the saved values of Reviewed are still all, accepted, rated and unrated, Reviewed is No and Captured is Any by default, and nothing scrolls sideways",
  "Yes lists only the ones whose content is held in full, and No lists the thin, the running and the ones with no state at all, in the same order",
  "the choice is remembered in this browser",
  "Accepted leaves out the rejected Reference that Yes lists, and Accepted with Captured No lists the accepted ones we could not collect",
  "the feed keeps asking for pages until the three are reached, and none of the captured ones is listed",
  "the search was asked for Captured No and for Accepted, the matches are the ones that fit, and choosing Reviewed during a search is not saved",
  "the page says \"Nothing here has 5 stars and has been captured.\" with Show any stars and Show any Captured buttons, and Show any Captured lists the Reference again",
  "those choices are pressed and listed, nothing was saved to the browser, and changing a control inside that view is not saved either",
];
for (const text of feedThens) Then(text, T, async function () { assert.ok((await feed()).includes("Reference feed scenario passed: captured")); });

When("the stored capture state is worked out from attachments, a card with a subscribe phrase at its end, an editor's complete, an editor's incomplete and a pasted text", T, async function () { this.out = await rule(); });
Then("a doubted capture is thin, an editor's complete makes it full, an editor's incomplete or incorrect makes it thin, text a person pasted is full, and an empty or unknown value reads as none", T, async function () {
  assert.match(await rule(), /capture-state: \d+ vectors passed\./);
});

When("the editor opens the newsroom home at 375 and 1440 pixels", T, async function () { this.out = await home(); });
When("the editor opens the first one, chooses Paste or correct the text, says the capture was incomplete and saves the text", T, async function () { this.out = await home(); });
When("the read of the capture list fails", T, async function () { this.out = await home(); });
const homeThens = [
  "three are listed, most stars first and newest first within a level, and the running, the rejected and the captured ones are left out",
  "each says \"We could not collect this. Upload a PDF or paste the text.\" with the reason when it is known, the header and a To capture pill count them, and How this is ordered says why",
  "See all links to the References page on Reviewed Accepted, Captured No and Sort Newest, nothing scrolls sideways and nothing has a border",
  "the capture is saved with the text and the verdict, the Reference leaves the list at once, and the next one joins behind the new items button",
  "no capture cards and no See all are shown and the other cards are untouched",
];
for (const text of homeThens) Then(text, T, async function () { assert.ok((await home()).includes("Notification Center scenario passed: captureNeeded")); });

When("the home list is read from the star partitions and then from the rated partition", T, async function () { this.out = await readers(); });
Then("the star levels come first, the unstarred follow newest first, a read that fails still lists what was found, and the reader stops once it has enough", T, async function () {
  const out = await readers();
  assert.match(out, /pass \d+/);
  assert.match(out, /fail 0/);
});
