const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const run = async (script, name) => (await promisify(execFile)(process.execPath, ["--import", "tsx", script, ...(name ? [name] : [])], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
const browser = (name) => run("scripts/test-reference-feed.ts", name);
const sync = (name) => run("scripts/test-reference-sync.ts", name);
const ranking = async () => (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-reference-feed-ranking.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;

for (const given of [
  "References with a ready curation card, a failed one, a failed one beside older extracted text, a degraded one that may be paywalled, and one still running",
  "a Reference with no captured text",
  "References where one has full stored text, one only a teaser, and one nothing but its link",
  "a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction",
  "References whose accepted examples show how quickly the editor acts",
  "References older than three times the learned freshness",
  "References whose pictures load, fail, or were never found",
  "the References are still loading",
  "this browser saved the last feed it showed",
  "the feed is open",
]) Given(given, function () { this.feedResult = ""; });

// Each outcome runs the named browser scenario in scripts/test-reference-feed.ts (every one covers 375 and 1440 pixels).
const outcomes = [
  ["layout", [
    "the order runs from the strongest Accept, through the item with no prediction, to the strongest Reject",
    "the first card is the large lead card, and the grid has one column on a phone and three or more on a desktop",
    "every card shows its title, dek, source, age, the Cyclotron's Accept or Reject with its confidence and icon, and large Accept and Reject buttons",
    "nothing scrolls sideways and there are no drop-downs",
  ]],
  ["grid", [
    "the Cyclotron row and the You row share the label, Accept and Reject columns exactly, on a card and in the review card, at 375 and 1440 pixels",
    "on a card as narrow as 240 pixels every icon, word and percentage fits inside its cell, the confidence wrapping onto its own line",
    "a confidence bar spans both columns, centred at 50%, filling toward Accept for an Accept-leaning prediction and toward Reject for a Reject-leaning one",
    "the fill's length is the prediction's distance from 50% doubled, and with no prediction the bar is empty and says No prediction",
    "before a vote the predicted cell is neutral with a Check or X icon",
  ]],
  ["verdict", [
    "the matching prediction cell is green with a CircleCheck and says Match, and the confidence bar is green",
    "the differing prediction cell is red with a CircleX and says Miss, and the confidence bar is red",
    "the chosen button is filled and the other is quiet, and tapping the chosen one does not unselect it",
  ]],
  ["design", [
    "no card, tab, pill, chip, panel or skeleton has a border, an outline or a rule, and surfaces differ only by tone",
    "cards are rounded rectangles with a full-bleed picture across the top, and pills are fully rounded",
    "the feed has the sections Top predictions, More for you and Least likely in large type with no lines between them",
    "on a phone the first card's picture is on the first screen",
  ]],
  ["popover", [
    "it explains best bets first, confidence, fading toward not sure, Earlier and why a rated card stays put",
    "it says how many accepted examples have been learned from, or how many more are needed",
  ]],
  ["cached", [
    "the saved cards are shown at once with a note that they are the last view",
    "answering is switched off with the reason in words, and a saved copy never answers on its own",
  ]],
  ["lifecycle", [
    "each rated card stays in its place and shows Saved",
    "the Cyclotron's chip says Match with a check or Miss with a cross, in words and an icon as well as colour",
    "Rejecting asks for a reason in words and changes nothing until one is chosen",
    "the Rated tab lists the most recent answer first, and the next visit lists the answered cards there",
  ]],
];
When("the editor opens the feed at 375 and 1440 pixels", function () { this.feedResult = ""; });
for (const action of [
  "the editor opens each of them",
  "the editor opens the full-text one at 375 pixels and shows all of the captured text",
  "the editor chooses Paste or correct the text, pastes the article and marks the capture complete",
  "the editor accepts on the grid card and then types a reason in the detail pane",
  "the editor types a reason in the detail pane before voting, then votes",
  "the editor rejects on the card and chooses the reason in the detail pane",
  "the editor opens a card and steps through the queue with Next and Previous",
  "the editor selects five items in turn, rates two, and a background refresh changes the predictions and adds a new item",
]) When(action, function () { this.feedResult = ""; });
const syncOutcomes = [
  ["curation_card", [
    "the record shows the card's status, word count, summary, GROBID fields and the curation text, and the card badge follows the curation status",
    '"No text captured" shows only when neither a card with text nor extracted text exists, with the card\'s typed reason in words',
    "a paywall phrase at the end of a long capture says it may be cut off, and a degraded card says a stage is unfinished",
  ]],
  ["correct_capture", [
    "correctReferenceCapture receives the text and the verdict, the record shows the new text and the verdict, and the summary is marked as awaiting the next run",
    "a verdict alone is saved as just a label, and nothing can be saved without a verdict",
  ]],
  ["capture_status", [
    "the title comes first, then the source's own blurb when it has one, the link, the badges and the summary, then Accept and Reject with the Why box",
    "the source's live preview sits right under its link only when the source allows being shown in a frame, with no heading and no empty box otherwise",
    "our captured record and the import details come after the rating",
    'the record says "Full text captured" with the stored text, its word count and any structured extraction, and the summary is not repeated there',
    "the stored text is Markdown shown formatted, with headings and lists as such and no Markdown syntax showing through",
    'the record says "Only 63 words — may be a teaser or paywalled" for the teaser, and "No text captured" for the one with nothing',
    "each state has its own Lucide icon as well as its words, and the record sits above the source preview",
    "every grid card carries a small badge saying Full text, how many words, or No text, before the item is opened",
  ]],
  ["vote_then_reason", ["the pane shows the vote, the green match state, and the reason is saved onto the same decision after a pause or on blur, with a Saved tick in both places"]],
  ["reason_then_vote", ['the vote carries the reason, a Reject with a typed reason saves at once under "Other", a Reject with no reason at all waits for one, and a failed save keeps what was typed']],
  ["phone_scroll", ["the captured text and every text box grow to fit their text, none of them scrolls inside itself, and the page scrolls past them"]],
  ["card_and_detail_agree", ["both show the Reject, the card shows the reason and the red or green match state with its icon"]],
  ["grid_stays_put", [
    "every card keeps its order and its position and size, and the grid does not scroll, at 375, 900 and 1440 pixels",
    "the column count stays fixed while the detail pane is open, and the pane's place is reserved beside the grid from the tablet width up, so opening it moves nothing, while below that the detail is a sheet",
    'the feed order is taken once per visit, so a re-rank never happens, and the new item waits behind a quiet "1 new item: show" pill until the editor shows it',
  ]],
  ["previous_next_selects", [
    "the grid scrolls smoothly so the selected card stays in view, on a tinted surface with a left accent bar and no outline",
    "opening a card from the grid selects it too",
  ]],
];
for (const [name, texts] of syncOutcomes) {
  for (const text of texts) {
    Then(text, { timeout: 300_000 }, async function () { assert.ok((await sync(name)).includes(`Reference sync scenario passed: ${name}`)); });
  }
}
When("the editor accepts a card, then rejects it with a reason, and rejects a card the Cyclotron expected to be rejected", function () { this.feedResult = ""; });
When("the editor votes with the Cyclotron's side and against it", function () { this.feedResult = ""; });
When("the editor opens how this feed is ranked", function () { this.feedResult = ""; });
When("the editor opens the References page while the session is still being confirmed", function () { this.feedResult = ""; });
for (const [name, texts] of outcomes) {
  for (const text of texts) {
    Then(text, { timeout: 240_000 }, async function () {
      assert.ok((await browser(name)).includes(`Reference feed scenario passed: ${name}`));
      // The same grid in the detail review card is checked by the reference editor's card layout scenario.
      if (text.includes("in the review card")) assert.ok((await run("scripts/test-reference-editor-review.ts", "card_layout")).includes("passed: card_layout"));
    });
  }
}

// "the editor opens the feed at 375 and 1440 pixels" opens every scenario that uses it; the outcomes below each run their own browser scenario.
When("the feed is ranked", { timeout: 60_000 }, async function () { this.feedResult = await ranking(); });
Then("an old prediction keeps only part of its distance from not sure and never falls below a fresh Reject", function () { assert.match(this.feedResult, /Age pulls a prediction toward uncertain/); });
Then("with fewer than ten accepted examples there is no fading and no Earlier section", function () { assert.match(this.feedResult, /Fewer than ten accepted examples means no decay/); });
Then("a card rated this visit does not move any other card", function () { assert.match(this.feedResult, /Rating one item does not move the others/); });
Then("they appear in an Earlier section after everything in the feed, and under the Earlier tab", async function () { assert.ok((await browser("earlier")).includes("passed: earlier")); });
Then("an Earlier card can be rated and stays where it is", async function () { assert.ok((await browser("earlier")).includes("passed: earlier")); });
Then("the pictures are lazy, in a fixed frame and requested with no referrer", async function () { assert.ok((await browser("images")).includes("passed: images")); });
Then("a missing or failing picture shows a soft gradient tile with the source's mark and name", async function () { assert.ok((await browser("images")).includes("passed: images")); });
Then("the page header, the tabs and card skeletons are on screen and no text says it is checking credentials", async function () { assert.ok((await browser("skeleton")).includes("passed: skeleton")); });
Then("a title shows without the site name a page tacks on its end, such as \" | Brookings\" or \" | Poverty and Development | Al Jazeera\"", async function () { assert.match(await ranking(), /A title drops the site name tacked on its end/); });
Then("a long capture that only ends without a full stop lists that as a fact but is not sent to the editor as a capture check", async function () { assert.match(await ranking(), /but a bare unpunctuated ending does not/); });
Then("the saved copy and the session summary expire, survive a blocked or full browser store, and are wiped on sign-out", async function () { assert.match(await ranking(), /The saved copy and the session display survive a return visit/); });

Then("each source's mark is the icon the newsroom found for it, or its first letter when there is none", async function () { assert.ok((await browser("images")).includes("passed: images")); });

// The icon lookup itself: scripts/test-source-icon.ts covers the ordering and the host guard.
Given("a source home page that declares its icons", function () { this.iconResult = ""; });
When("the newsroom looks for that source's icon", async function () { this.iconResult = await run("scripts/test-source-icon.ts"); });
for (const text of [
  "it prefers the touch icon, then the largest declared size, and ignores single-colour mask icons",
  "it falls back to /favicon.ico only when that is more than an empty placeholder",
  "only real host names that resolve to public addresses are ever fetched",
]) Then(text, function () { assert.match(this.iconResult, /source icon check: ok/); });

// The framing check itself: scripts/test-source-frameable.ts covers the header rules and the address guard.
Given("a source page and the headers it sends", function () { this.frameableResult = ""; });
When("the newsroom checks whether it may show that page in a frame", async function () { this.frameableResult = await run("scripts/test-source-frameable.ts"); });
for (const text of [
  "a page that sends X-Frame-Options or a frame-ancestors rule that does not allow every site is not framed, and one with neither rule is",
  "only public web addresses on the standard ports are ever fetched, so the check cannot be pointed at the server's own network",
]) Then(text, function () { assert.match(this.frameableResult, /source frameable check: ok/); });
