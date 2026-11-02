const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const run = async (script, name) => promisify(execFile)(process.execPath, ["--import", "tsx", script, name], { cwd: root, maxBuffer: 8 * 1024 * 1024 });
const browser = (name) => run("scripts/test-auto-accepted-list-ui.ts", name);
const logic = (name) => run("scripts/test-auto-accepted-list.ts", name);

for (const given of [
  "a newsroom with Cyclotron acceptances, a rule acceptance and an editor's own acceptance",
  "a newsroom with more automatic acceptances than one page holds",
  "a newsroom where nothing has been accepted automatically",
  "5000 accepted References, 250 of them accepted automatically",
  "the list's database filter",
]) Given(given, function () {});

for (const when of [
  "the editor opens the References page at the address ?status=auto-accepted",
  "the editor chooses the Accepted automatically filter and reaches the end of the list",
  "the editor taps Reject on an automatically accepted card",
  "the editor opens the list on a phone",
  "the first page of the list is read",
]) When(when, function () {});

// Each outcome runs the named scenario of scripts/test-auto-accepted-list-ui.ts (a real browser, fixture data) or of
// scripts/test-auto-accepted-list.ts (the page reads, with a fake database). Nothing touches AWS.
const outcomes = [
  [["the Accepted automatically filter is selected and shows no count", "only the automatic acceptances are listed, newest first, each with who accepted it, how sure the Cyclotron was, and the reason it recorded", "the editor's own acceptance is not listed", "the cards carry the same Accept and Reject buttons, with no dropdown"], () => browser("opens_from_the_address")],
  [["the address says ?status=auto-accepted", "the next page is read from where the last stopped, and no card appears twice"], () => browser("pages_and_address")],
  [["the reason box is empty and a reason is required before anything is sent", "once the editor writes a reason and records it, the Reject is sent with that reason and the card leaves the list"], () => browser("reject_leaves_the_list")],
  [["it says that nothing has been accepted automatically yet"], () => browser("empty_state")],
  [["nothing scrolls sideways, the tap targets are large and the icons are Lucide"], () => browser("phone")],
  [["the page holds the newest automatic acceptances and only a small part of the 5000 is read"], () => logic("a page is filled from the newest end and stops there")],
  [["the next page continues where it stopped, a database page with no match is not taken for the end, and no acceptance is listed twice"], async () => {
    await logic("the next page continues where the last stopped and walks to the end");
    await logic("a database page with no match is not the end of the list");
  }],
  [["it names auto:cyclotron and auto:rule, current versions only"], () => logic("the filter names both automatic actors and only current References")],
  [["an editor's acceptance is refused even if a read returns it"], () => logic("an editor's acceptance is never listed, even from an unfiltered read")],
];
for (const [sentences, check] of outcomes) for (const sentence of sentences) Then(sentence, { timeout: 120000 }, check);
