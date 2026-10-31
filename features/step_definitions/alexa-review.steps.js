const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

// Each behaviour runs scripts/test-alexa-review.ts, which asserts internally and prints the behaviour's name when it passes.
async function behaviours(...names) {
  const passed = [];
  for (const name of names) {
    const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-alexa-review.ts", name], {
      cwd: path.resolve(__dirname, "../.."),
      maxBuffer: 8 * 1024 * 1024,
    });
    passed.push(JSON.parse(result.stdout.trim().split("\n").pop()).behaviour);
  }
  return passed;
}

function step(keyword, text, ...names) {
  keyword(text, { timeout: 120_000 }, async function () {
    this.passed = [...(this.passed ?? []), ...(await behaviours(...names))];
  });
}

function pass(text) {
  Then(text, function () {
    assert.ok(this.passed && this.passed.length > 0);
  });
}

const ORDER = "best bets are ordered by P(accept) and needs my help by uncertainty";
const BEST = "an editor reviews the best bets one by one and votes are recorded as theirs";

step(Given, "unrated References with different predictions, and one with none", ORDER);
pass("best bets puts the highest P\\(accept) first and counts no prediction as a coin toss");
pass("needs my help puts the guesses closest to a coin toss first");

step(Given, "a linked editor on an Echo Show", BEST);
step(When, `they say "review the best bets" and then accept the first one and reject the second because it's off topic`, BEST);
pass("each Reference is read and shown with its place in the list");
pass("each answer is recorded under the editor's own sign-in with their name, the Cyclotron decision it answers, and for a rejection the reason in their words and its reason code");
pass("the next Reference follows each answer, with a short prompt once the full one has been heard");

step(Given, "a linked editor reviewing a Reference", "a bare reject asks why and the because answer completes it");
step(When, `they say just "reject"`, "a bare reject asks why and the because answer completes it");
pass(`Alexa asks why and records nothing until they answer "because ..."`);
pass(`a stray "because ..." outside that question checks what they meant`);

step(When, `a linked editor says "show me references"`, "without a named list it starts with what needs help and says how to switch");
pass("the review starts with what needs their help and says best bets is a word away");

step(Given, "a linked editor reviewing the best bets", BEST);
step(When, "they skip, say next, accept, undo, repeat and go back", "skip, undo, previous and repeat move without losing the editor");
pass("skip and next move on without an answer, undo reopens the last answer and reads that Reference again, and repeat and previous read again");

step(When, "they ask how many are left, why this one, who published it, for more, for help, or to send it to their phone, or say accept all", "the editor can ask where they are, why, who published it, and for the link");
pass("each question gets a plain answer and the same short prompt, the link goes to the Alexa app, and accept all is kindly refused");

step(Given, "a linked editor reviewing what needs their help", "needs my help explains a coin toss");
step(When, "they ask why this one", "needs my help explains a coin toss");
pass("Alexa says the Cyclotron's guess in percent and that it is close to a coin toss");

step(Given, "a linked editor reviewing on an Echo Show", "touch buttons on the card do what the words do");
step(When, "they touch Accept, Reject and Skip", "touch buttons on the card do what the words do");
pass("each does what the word does, and Reject still asks why");

step(Given, "a short list", "the end of a round offers the other list");
step(When, "the editor answers the last Reference", "the end of a round offers the other list");
pass("Alexa says the round is over and offers the other list, and an empty newsroom says nothing is waiting");

step(Given, "more unrated References than one session carries", "a session carries a capped queue but counts them all");
pass("the editor hears how many are waiting in all and their place among them");

step(When, "someone who has not linked their account asks to review", "not linked gets the link prompt, a reader is told review is for editors");
pass("Alexa asks them to link and sends a LinkAccount card, which an Echo Show shows as a QR code");
pass("a linked reader who is not an editor hears that review is for editors");

step(When, "the newsroom refuses the sign-in or cannot be reached while recording an answer", "a refused or failed vote records nothing and says so");
pass("nothing is recorded and the editor is told so, with a way forward");

step(Then, "accept outside a review says how to start one, a misheard answer during a review gets the short choices instead of the headlines, and stopping says unanswered References will still be waiting", "review words outside a review get a way in, and stop leaves cleanly");

step(When, "a linked editor opens the skill", "a linked editor's launch offers review first");
pass("they are offered needs my help, best bets and headlines");

step(Then, "the client reads the corpus's unrated feed index, each Reference's preview, curation card and current Cyclotron decision, and votes through reviewReferenceCuration with the editor's access token", "the newsroom client reads the feed index, attachments and decisions, and votes with the editor's token");
step(Then, "an AppSync authorization error is a refusal, never a crash", "an AppSync authorization error is a refusal, not a crash");
