const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

// Each behaviour runs scripts/test-alexa-intents.ts, which asserts internally and prints the behaviour's name when it passes.
async function behaviours(...names) {
  const passed = [];
  for (const name of names) {
    const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-alexa-intents.ts", name], {
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

const HEADLINES = "launch reads the latest five headlines and asks which one";
const HEARD = "a story is read by ordinal or by number";
const MOVING = "next, previous and repeat move through the stories";

step(Given, "a site with six published stories", HEADLINES);
step(When, "a listener opens the skill", HEADLINES, "launch with nothing published says so and ends");
pass("the five newest headlines are read in order under the site's publication name");
pass("the listener is asked which story they want and the session stays open");

step(Given, "a site with no published stories", "launch with nothing published says so and ends");
pass("the skill says there are no published stories and ends");

step(Given, "the listener has heard the headlines", HEADLINES);
step(When, "they ask for the second one, or for story number four", HEARD);
pass("the skill reads that story's byline, deck and the first part of its body");
pass("it offers to say next for the next story");

step(When, "they ask for a story that is not in the list, or give no number", "a story number that does not exist is explained");
pass("the skill says how many stories there are and keeps the session open");

step(When, "they say next, previous and repeat", MOVING);
pass("the skill moves one story at a time and re-reads the current one");
pass("it says so at the first and the last story instead of going past them");

step(When, "they say repeat before choosing a story", "repeat at the headlines reads the headlines again");
pass("the headlines are read again");

step(When, "they ask for a story that was unpublished in the meantime", "a story that has gone away sends the listener back to the headlines");
pass("the skill apologises and reads fresh headlines");

step(When, "a listener asks for help", "help explains what to say");
pass("the skill explains numbers, next, previous, repeat, headlines and stop and keeps listening");

step(When, "a listener says stop or cancel", "stop and cancel say goodbye and end");
pass("the skill says goodbye and ends the session");

step(When, "a listener says something the skill cannot match", "fallback reads the headlines instead of a dead end");
pass("the skill says it did not catch that and reads the headlines, so there is always something to choose");
pass("the session stays open");

step(Given, 'a listener who reaches the skill with "ask pilobolus newsroom for the headlines"', "asking for the headlines reads them, greeting a new session");
step(When, "they ask for the headlines, the stories, the articles or the posts, or say they do not know what the stories are", "the headlines intent hears how people ask for the list");
pass("the latest headlines are read, with a welcome when the session is new");
step(Then, "asking for a story without a number reads the list instead of asking for a number", "a story number that does not exist is explained");

step(Given, "the listener is reading a story", "navigate home returns to fresh headlines");
step(When, "they ask to go home", "navigate home returns to fresh headlines");
pass("the headlines are fetched and read again");
pass("the next story is the first one");

step(When, "Alexa reports that the session ended", "session ended answers without speech");
pass("the skill answers without speaking");

step(Given, "stories whose titles, bylines and text contain ampersands, angle brackets and quotes", "ssml escapes everything it speaks");
step(When, "they are read aloud", "ssml escapes everything it speaks");
pass("the speech is well formed and never carries a raw markup character");

step(Given, "a story far longer than a minute of speech", "a long story is read in short parts with continue");
step(When, "it is read aloud", "a long story is read in short parts with continue");
pass("the first part starts with the title, byline and deck and stops at a whole sentence after about a minute");
pass("the listener can say continue for the next part, repeat for the same part, and hears when the story ends");
step(Then, 'a byline that already starts with "by" is not read as "by by"', "a byline that already says by is not doubled");

step(Given, "a sentence longer than the room there is", "one endless sentence is shortened at a word");
step(When, "it is fitted into the speech", "one endless sentence is shortened at a word");
pass("it is cut at a word boundary");

step(Given, "a Markus story with headings, lists, directives, code, an image and a table", "speech walks the Markus nodes");
step(When, "it is turned into speech", "speech walks the Markus nodes");
pass("the document's nodes are read in order and the parts that cannot be heard are described or skipped");
pass("a stored body IR is used instead of the source when there is one");

step(When, "the skill package is generated", "the interaction model carries every intent with natural samples");
pass("it holds the required built-in intents and a story intent with natural samples for ordinals and numbers");

step(Given, "a site whose public listing and Markdown twins are served", "the content source reads the public projection");
step(When, "the skill lists and reads stories", "the content source reads the public projection");
pass("the newest entries come from the listing, the body from the story's Markdown twin and older stories from the search index");
pass("a missing twin or an unlisted story is no story and a listing entry never leads to another host");
pass("a site without a public origin fails loudly instead of answering with nothing");

step(When, "a Markdown twin is read", "the twin header is split from the Markus body");
pass("its title, summary, byline and canonical link are split from the Markus body");
