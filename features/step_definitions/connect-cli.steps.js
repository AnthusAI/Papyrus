const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then, setDefaultTimeout } = require("@cucumber/cucumber");

setDefaultTimeout(180_000);

const root = path.resolve(__dirname, "../..");
const runs = new Map();
// Each scenario of the script runs once per test run, however many steps name it.
const run = (name) => { if (!runs.has(name)) runs.set(name, promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-connect-cli.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 })); return runs.get(name); };

for (const given of [
  "a synthetic site whose sign-in file is published",
  "a synthetic site that names a remote sign-in broker and one that does not",
  "a synthetic site that names a remote sign-in broker",
]) Given(given, function () { this.connectResult = ""; });

// Each outcome runs the named scenario in scripts/test-connect-cli.ts, which covers 375 and 1440 pixels in light and dark.
const outcomes = [
  ["commands", [
    "the sign-in command names the site's host, and the check and sign-out commands name it too",
    "a site with its console on its own host gets that host, because the sign-in file names it",
    "a site that does not publish the sign-in file gets no commands and a plain explanation",
  ]],
  ["remote", [
    "the first site shows the remote command straight after install, for an agent on a cloud computer approved from a phone, and says to open the link yourself",
    "the second shows no remote command and says approving from a phone is not switched on",
    "a site with no sign-in file shows no command at all",
  ]],
  ["copy", [
    "exactly that command is copied",
    "the button changes its icon and says Copied, so the change is not colour alone",
  ]],
  ["design", [
    "no element has a visible border, outline or shadow and nothing scrolls sideways",
    "the panels are rounded rectangles that differ from the page only by tone",
    "there are no drop-downs and every icon is a Lucide icon",
  ]],
  ["prose", [
    "it says the agent acts as the editor and can do what the editor can do and nothing more",
    "it says how to end the sign-in on that computer",
    "it never says Organization or desk",
  ]],
];
for (const [name, steps] of outcomes) for (const step of steps) Then(step, async function () { await run(name); });
for (const when of [
  "the page is built for it",
  "the editor opens the page at 375 and 1440 pixels",
  "the editor presses the copy button of the remote command",
  "the editor opens the page at 375 and 1440 pixels, in light and dark",
  "the editor reads the page",
]) When(when, function () {});
