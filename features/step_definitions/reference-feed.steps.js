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
  "References of very different ages with predictions",
  "an old unrated Reference with a strong prediction",
  "a feed with References that were accepted automatically or by an editor",
  "References whose pictures load, fail, or were never found",
  "the References are still loading",
  "this browser saved the last feed it showed",
  "the feed is open",
  "a Reference the Cyclotron accepted automatically, one a monitor's rule accepted, and another that an editor accepted",
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
    "the prediction bar, the Accept and Reject buttons and the reason field are all the same width, on a card and in the review card, at 375 and 1440 pixels",
    "there is no second row of prediction cells: the predicted side is marked on the button itself",
    "the confidence bar is centred at 50%, filling toward Accept for an Accept-leaning prediction and toward Reject for a Reject-leaning one",
    "the fill's length is the prediction's distance from 50% doubled, and with no prediction the bar is empty and says No prediction",
    "the confidence is printed in the bar and on no button, moving beside the fill when the fill is too short to hold it",
    "before an answer the predicted button carries its own tone and says Predicted, with no border anywhere",
  ]],
  ["verdict", [
    "the chosen button says Confirmed when it agrees with the prediction and Overturned when it does not",
    "the marker on the predicted side and the confidence bar turn green for a confirmation and red for an overturn",
    "the chosen button itself is never tinted by the verdict: it is the same fill either way",
    "the chosen button is filled and the other is quiet, and tapping the chosen one does not unselect it",
  ]],
  ["design", [
    "no card, button, pill, chip, panel or skeleton has a border, an outline or a rule, and surfaces differ only by tone",
    "cards are rounded rectangles with a full-bleed picture across the top, and pills are fully rounded",
    "the feed is one list in rank order with no section headings, the predicted Rejects last",
    "on a phone the first card's picture is on the first screen",
  ]],
  ["auto", [
    "the automatically accepted card says Accepted automatically with a Lucide icon, one accepted by a monitor's rule says so too, and the editor's accept carries no such mark",
    "both read as accepted, and the editor can still change either",
  ]],
  ["popover", [
    "it explains Best bets, Newest, Unrated only, Include rated and why a rated card stays put",
    "it says that age does not change the order",
  ]],
  ["cached", [
    "the saved cards are shown at once with a note that they are the last view",
    "answering is switched off with the reason in words, and a saved copy never answers on its own",
  ]],
  ["lifecycle", [
    "each rated card stays in its place and shows Saved",
    "the answered button says Confirmed or Overturned, in words and a marker as well as colour",
    "Rejecting asks for a written reason in words and changes nothing until one is given",
    "while an answer is being saved the button says Sending, or Updating when it changes a saved answer, and never says it is unrecorded",
    "choosing Include rated keeps the answered cards where they were",
  ]],
];
When("the editor opens the feed at 375 and 1440 pixels", function () { this.feedResult = ""; });
When("the editor chooses Include rated at 375 and 1440 pixels", function () { this.feedResult = ""; });
for (const action of [
  "the editor opens each of them",
  "the editor opens the full-text one at 375 pixels and shows all of the captured text",
  "the editor chooses Paste or correct the text, pastes the article and marks the capture complete",
  "the editor chooses Upload a PDF, marks the capture incomplete and chooses a PDF, at 375 and 1440 pixels",
  "the editor accepts on the grid card and then types a reason in the detail pane",
  "the editor types a reason in the detail pane before voting, then votes",
  "the editor rejects on the card and chooses the reason in the detail pane",
  "the editor opens a card and steps through the queue with Next and Previous",
  "the editor opens a long reference and scrolls its detail to the bottom at 375, 390 and 1440 pixels",
  "the editor scrolls a long reference to the bottom and then selects another with a card, with Next and with Previous",
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
  ["upload_pdf", [
    "the PDF is stored as an attachment of the Reference, correctReferenceCapture receives its id and the verdict, and the record shows the new text with the line \"Text from a PDF you uploaded\"",
    "a refusal from the server and a failed upload each show in words, and no upload button appears without the correction action",
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
    "the column count stays fixed while the detail pane is open: from the tablet width up the pane appears beside the grid with the first selection and then holds its place, so moving between items moves nothing, while below that the detail is a sheet",
    'the feed order is taken once per visit, so a re-rank never happens, and the new item waits behind a quiet "1 new item: show" pill until the editor shows it',
  ]],
  ["detail_bar_fixed", [
    "the Previous and Next buttons are still in view, above the tab bar on a phone and at the bottom of the detail pane on a desktop",
    "the bar is in the same place at the top, part way down and at the bottom of the detail",
    "the last of the detail's content ends above the bar, so nothing is covered by it",
  ]],
  ["detail_opens_at_top", [
    "each newly selected reference is scrolled to the top and its headline is in view above the bar, on a phone and on a desktop",
    "a refresh of the reference that stays open does not move its scroll position",
  ]],
  ["previous_next_selects", [
    "the grid scrolls smoothly so the selected card stays in view, on a tinted surface with a thick ring drawn outside it on every side, which takes no space in the grid and is never cut off at the feed's edge",
    "opening a card from the grid selects it too",
    "before any card is selected there is no Detail pane and the feed has the whole width",
  ]],
];
for (const [name, texts] of syncOutcomes) {
  for (const text of texts) {
    Then(text, { timeout: 300_000 }, async function () { assert.ok((await sync(name)).includes(`Reference sync scenario passed: ${name}`)); });
  }
}
When("the editor accepts a card, then rejects it with a written reason, and rejects a card that was predicted Reject", function () { this.feedResult = ""; });
When("the editor answers with the predicted side and against it", function () { this.feedResult = ""; });
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
Then("an old strong Accept still ranks above a new weaker one, and an old Reject never rises above a new Accept", function () { assert.match(this.feedResult, /Best bets is the Cyclotron's own confidence: age never changes it/); });
Then("ties go to the newest item and then to a stable order", function () { assert.match(this.feedResult, /Ties in Best bets go to the newest item/); });
Then("a card rated this visit does not move any other card", function () { assert.match(this.feedResult, /The feed order is taken once and kept, in both sorts/); });
Then("it stays in the one list where its original confidence puts it, and last when sorted by Newest, with no Earlier section and no tabs", async function () { assert.ok((await browser("aged")).includes("passed: aged")); });
Then("an old card can be rated and stays where it is", async function () { assert.ok((await browser("aged")).includes("passed: aged")); });
Then("Best bets and Unrated only are pressed, and each choice is a pair of buttons with an icon and words", async function () { assert.ok((await browser("sorting")).includes("passed: sorting")); });
Then("choosing Newest orders the cards by arrival, newest first, whatever the predictions say", async function () { assert.ok((await browser("sorting")).includes("passed: sorting")); });
Then("the answered cards join the same list in the active sort, each showing its recorded vote", async function () { assert.ok((await browser("sorting")).includes("passed: sorting")); });
Then("the page remembers Newest and Include rated for this browser, with no tabs on the page", async function () { assert.ok((await browser("sorting")).includes("passed: sorting")); });
When("the editor chooses Include rated and reloads the page", function () { this.feedResult = ""; });
Then("the pictures are lazy, in a fixed frame and requested with no referrer", async function () { assert.ok((await browser("images")).includes("passed: images")); });
Then("a missing or failing picture shows a soft gradient tile with the source's mark and name", async function () { assert.ok((await browser("images")).includes("passed: images")); });
Then("the page header, the sort and show buttons and card skeletons are on screen and no text says it is checking credentials", async function () { assert.ok((await browser("skeleton")).includes("passed: skeleton")); });
Then("a title shows without the site name a page tacks on its end, such as \" | Brookings\" or \" | Poverty and Development | Al Jazeera\"", async function () { assert.match(await ranking(), /A title drops the site name tacked on its end/); });
Then("a long capture that only ends without a full stop lists that as a fact but is not sent to the editor as a capture check", async function () { assert.match(await ranking(), /but a bare unpunctuated ending does not/); });
Then("the saved copy and the session summary expire, survive a blocked or full browser store, and are wiped on sign-out", async function () { assert.match(await ranking(), /The saved copy and the session display survive a return visit/); });

Then("each source's mark is the icon the newsroom found for it, or its first letter when there is none", async function () { assert.ok((await browser("images")).includes("passed: images")); });

// The icon lookup itself: scripts/test-source-icon.ts covers the ordering and the host guard.
Given("a source home page that declares its icons", function () { this.iconResult = ""; });
When("the newsroom looks for that source's icon", async function () { this.iconResult = await run("scripts/test-source-icon.ts"); });
for (const text of [
  "it prefers the touch icon, then the largest declared size, and ignores single-colour mask icons",
  "it falls back to the site's favicon.ico only when that is more than an empty placeholder",
  "only real host names that resolve to public addresses are ever fetched",
]) Then(text, function () { assert.match(this.iconResult, /source icon check: ok/); });

// The framing check itself: scripts/test-source-frameable.ts covers the header rules and the address guard.
Given("a source page and the headers it sends", function () { this.frameableResult = ""; });
When("the newsroom checks whether it may show that page in a frame", async function () { this.frameableResult = await run("scripts/test-source-frameable.ts"); });
for (const text of [
  "a page that sends X-Frame-Options or a frame-ancestors rule that does not allow every site is not framed, and one with neither rule is",
  "only public web addresses on the standard ports are ever fetched, so the check cannot be pointed at the server's own network",
]) Then(text, function () { assert.match(this.frameableResult, /source frameable check: ok/); });

// Paging: scripts/test-newsroom-all-pages.ts drives the loader the feed uses with three overlapping pages and a looping token.
Given("a newsroom with more References than one page of the backend's list holds", function () { this.pagingResult = ""; });
When("the editor opens the References feed", async function () { this.pagingResult = await run("scripts/test-newsroom-all-pages.ts"); });
for (const then of [
  "the feed reads page after page until the backend says there are no more",
  "each Reference appears once even when two pages overlap",
  "a page token that repeats stops the read with a message instead of looping",
]) Then(then, function () { assert.match(this.pagingResult, /newsroom all-pages: ok/); });

// Predictions per visible Reference: the browser scenario "predictions" (390 and 1440) and scripts/test-reference-predictions.ts.
const predictionUnit = async () => (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-reference-predictions.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
for (const given of [
  "a newsroom with 60 References and 20,000 relation records, more than any fixed page budget could read",
  "a feed where the prediction read for one Reference is refused",
  "a feed where every prediction read is refused",
  "a newsroom with about 16,000 relations held by subject",
]) Given(given, function () { this.predictionResult = ""; });
When("the editor opens the feed", { timeout: 300_000 }, async function () { this.predictionResult = await browser("predictions"); });
When("the feed has loaded", { timeout: 300_000 }, async function () { this.predictionResult = await browser("predictions"); });
When("the feed windows its References and reads their predictions", { timeout: 120_000 }, async function () { this.predictionResult = await predictionUnit(); });
for (const then of [
  "predictions are read for the 24 References on the first page, one read each, and for no other Reference",
  "every one of those cards shows its prediction and confidence",
  "nothing says that predictions are unavailable or that the activity feed is incomplete",
  "scrolling to the end reads the next page's predictions only, and its cards join after the first page without moving it",
  "that card says Prediction unavailable and offers Retry, in words and an icon",
  "every other card shows its prediction, and no message about predictions appears for the page",
  "choosing Retry reads that one prediction again and the card shows it",
  "every Reference still shows its title, source, age and its Accept and Reject buttons",
  "each card says Prediction unavailable with Retry, and the feed is never left as grey skeletons",
  "the order is the server's own, newest first, because nothing can rank them yet",
]) Then(then, function () { assert.match(this.predictionResult, /Reference feed scenario passed: predictions/); });
for (const then of [
  "only the shown References are read, at most a few reads are in flight at once, and one failing read fails only its own Reference",
  "the window is the newest pages of unanswered items plus the answered ones that arrived since, and it only ever grows",
  "a later page is ranked after everything already placed, while a new arrival waits behind the new-items pill",
]) Then(then, function () { assert.match(this.predictionResult, /(^|\n)ℹ fail 0/); });
