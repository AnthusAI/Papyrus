const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
let report;
const run = async () => {
  report ??= (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-message-author-enforced.ts", "scripts/test-appsync-resolvers.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return report;
};

Given("the data API schema and its message resolvers", function () {});
for (const when of [
  "a signed-in editor posts a message that names a different author, profile and time",
  "an editor, or an admin, edits a message",
  "any edit, delete or moderation is run",
  "an author deletes their message",
  "an admin and an editor each try to moderate a message",
  "an editor and an admin rename a conversation",
  "the rules on Message are read",
  "the author kind fields on Message are read",
  "the function grants and every browser writer are read",
  "the resolver files are located the way a site's deploy locates them",
  "every resolver is checked with the rules AppSync applies to its JavaScript runtime",
]) When(when, function () {});

// Each outcome is one test in scripts/test-message-author-enforced.ts.
const outcomes = [
  ["the message is stored with the editor's own sub, the server's time and a completed response status, and never replaces an existing message", /✔ a post records the signed-in user/],
  ["the write only succeeds when the stored author is the caller and the message is not deleted", /✔ nobody can edit another person's message/],
  ["a refusal says in words that only the author can edit", /✔ nobody can edit another person's message/],
  ["none of them writes authorSub, and the model offers no update and no owner rule", /✔ an author cannot reassign authorship/],
  ["the message stays, marked deleted with when and by whom, its text is untouched, and only the author's own message qualifies", /✔ an author deletes their own message softly/],
  ["the admin's soft delete is recorded as the admin's doing with no change to the text, and the editor is refused in words", /✔ an admin soft-deletes anyone's message/],
  ["moderateMessage is offered to admins only", /✔ an admin soft-deletes anyone's message/],
  ["the editor's rename is conditional on being the creator, the admin's is not, and the model itself cannot change a title or a creator", /✔ a thread is renamed by its creator or an admin only/],
  ["editors and admins can only read, and the five mutations are offered to the right groups on the right tables", /✔ the schema offers the five mutations/],
  ["the functions keep their grants and the assignment function can still create and update Messages", /✔ machine writers still work/],
  ["the conversation, forum and console chat writers post through postMessage and name no author", /✔ the browser writes only through postMessage/],
  ["every message resolver is named by an absolute path to a file that exists, wherever the package is installed", /✔ every message resolver is found by an absolute path/],
  ["none uses a construct the runtime refuses, such as a classic for loop or ++, so a site's deploy is never rolled back over it", /✔ every AppSync resolver passes the APPSYNC_JS runtime's lint rules[\s\S]*✔ the rules catch what the runtime refuses|✔ the rules catch what the runtime refuses[\s\S]*✔ every AppSync resolver passes/],
  ["a Message reads as staff unless a reader wrote it, and the public export names no reader or identity field", /✔ a Message reads as staff unless a reader wrote it/],
];
for (const [then, pattern] of outcomes) Then(then, async function () { assert.match(await run(), pattern); });
